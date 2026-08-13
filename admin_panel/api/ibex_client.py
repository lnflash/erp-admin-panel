"""Read-only client for the IBEX Hub API.

Used by the wallet-census background job to page through every organization
account and read its live balance. Authentication is OAuth2 client-credentials
(NOT email/password): a token is fetched from the auth domain and sent to the
hub as a RAW ``Authorization`` header value (no ``Bearer`` prefix).

Verified against the ibex-client library and the Flash backend:
  * token endpoint  POST {auth_domain}/oauth/token  (grant_type=client_credentials)
  * hub base        {hub_url}
  * bulk list       GET  {hub_url}/v2/account?expand=true&page=N&limit=100
  * balances are dollars, present only when expand=true (absent => zero)
  * currencyId 3 => USD, 29 => USDT (BTC is not held in IBEX)

Config (site_config.json / frappe.conf):
  ibex_client_id, ibex_client_secret          (required)
  ibex_environment                             (optional, "production" | "sandbox";
                                                default "production" — URLs baked in)
  ibex_auth_domain, ibex_hub_url, ibex_audience(optional per-field overrides)
"""

import time

import frappe
import requests

from .census_core import PageLimitExceeded, sweep_pages

# Verified URLs per environment (from the ibex-client library). Any field can
# still be overridden via config for a bespoke staging setup. Note the sandbox
# audience is a different host from production.
_ENVIRONMENTS = {
	"production": {
		"auth_domain": "https://auth.hub.poweredbyibex.io",
		"hub_url": "https://ibexhub-api.poweredbyibex.io",
		"audience": "https://ibexhub.ibexmercado.com",
	},
	"sandbox": {
		"auth_domain": "https://auth.hub.sandbox.poweredbyibex.io",
		"hub_url": "https://ibexhub-api.sandbox.poweredbyibex.io",
		"audience": "https://api-sandbox.poweredbyibex.io",
	},
}

# Bulk-endpoint page size. Valid range is [10, 100]; 100 minimizes round-trips.
PAGE_LIMIT = 100

# Courtesy throttle between bulk reads. The read path is not rate-limited nearly
# as tightly as account creation, but we stay polite (~1 req/s).
REQUEST_INTERVAL_SECONDS = 1.0

# One-shot backoff before retrying a request that hit a 429.
RATE_LIMIT_BACKOFF_SECONDS = 2.0

# Hard cap on bulk-list pagination — defensive against a misbehaving API
# paging forever (10k pages * 100/page = 1M accounts, far above org size).
MAX_PAGES = 10000

_session = None


def _get_session() -> requests.Session:
	global _session
	if _session is None:
		_session = requests.Session()
	return _session


class IbexError(Exception):
	"""IBEX Hub API error."""


class IbexClient:
	"""Read-mostly (two gated treasury writes) IBEX Hub client with client-credentials auth."""

	def __init__(self):
		env = frappe.conf.get("ibex_environment") or "production"
		defaults = _ENVIRONMENTS.get(env, {})

		self.auth_domain = frappe.conf.get("ibex_auth_domain") or defaults.get("auth_domain")
		self.hub_url = frappe.conf.get("ibex_hub_url") or defaults.get("hub_url")
		self.audience = frappe.conf.get("ibex_audience") or defaults.get("audience")
		self.client_id = frappe.conf.get("ibex_client_id")
		self.client_secret = frappe.conf.get("ibex_client_secret")

		missing = [
			key
			for key, val in {
				"ibex_client_id": self.client_id,
				"ibex_client_secret": self.client_secret,
				"ibex_hub_url": self.hub_url,
				"ibex_auth_domain": self.auth_domain,
				"ibex_audience": self.audience,
			}.items()
			if not val
		]
		if missing:
			raise ValueError(f"IBEX config missing from site_config.json: {', '.join(missing)}")

		self._session = _get_session()
		self._token = None
		self._token_expires_at = 0.0

	def _fetch_token(self) -> str:
		"""Fetch a fresh client-credentials access token and cache it to its TTL."""
		resp = self._session.post(
			f"{self.auth_domain}/oauth/token",
			data={
				"grant_type": "client_credentials",
				"client_id": self.client_id,
				"client_secret": self.client_secret,
				"audience": self.audience,
			},
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			timeout=30,
		)
		if not resp.ok:
			raise IbexError(f"IBEX token request failed: {resp.status_code} {resp.text[:200]}")
		body = resp.json()
		token = body.get("access_token")
		if not token:
			raise IbexError("IBEX token response missing access_token")
		# Refresh a minute early to avoid using a token that expires mid-request.
		self._token = token
		self._token_expires_at = time.time() + max(int(body.get("expires_in", 3600)) - 60, 0)
		return token

	def _get_token(self) -> str:
		if not self._token or time.time() >= self._token_expires_at:
			return self._fetch_token()
		return self._token

	def _get(self, path: str, params: dict, allow_not_found: bool = False) -> requests.Response:
		"""GET with a raw-token Authorization header.

		Refetches + retries once on 401 (expired token) and backs off once on
		429 (rate limit). When allow_not_found is set, a 404 is returned to the
		caller instead of raising (drained IBEX accounts can 404 on reads).
		"""
		url = f"{self.hub_url}{path}"
		resp = self._session.get(url, params=params, headers={"Authorization": self._get_token()}, timeout=30)
		if resp.status_code == 401:
			self._fetch_token()
			resp = self._session.get(
				url, params=params, headers={"Authorization": self._get_token()}, timeout=30
			)
		if resp.status_code == 429:
			time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
			resp = self._session.get(
				url, params=params, headers={"Authorization": self._get_token()}, timeout=30
			)
		if allow_not_found and resp.status_code == 404:
			return resp
		if not resp.ok:
			raise IbexError(f"IBEX GET {path} failed: {resp.status_code} {resp.text[:200]}")
		return resp

	def _post(self, path: str, body: dict) -> requests.Response:
		"""POST with the same raw-token auth + 401/429 handling as _get.

		Only the two treasury calls below use this — the client is otherwise
		read-only by design.

		Write policy — two deliberately different tiers:
		  * VALUE-MOVING writes (pay_invoice, and add_invoice used as the
		    receiver leg of a wallet-to-wallet transfer) move treasury funds and
		    require a System-Manager-gated endpoint plus a System Transfer Log
		    record (see transfer_between_system_wallets).
		  * INBOUND-ONLY receive-invoice creation (add_invoice called on its own
		    so an external payer can fund a wallet — create_funding_invoice) moves
		    NO treasury money on creation; the payer's later payment only credits
		    us. It is therefore financial-gated (System Manager OR Accounts
		    Manager), bounded by a fat-finger cap, and audit_log'd rather than
		    Transfer-Log'd. Do NOT widen this carve-out to any write that debits a
		    system wallet.
		Never add a NEW write here without matching one of these two tiers.
		"""
		url = f"{self.hub_url}{path}"
		headers = {"Authorization": self._get_token()}
		resp = self._session.post(url, json=body, headers=headers, timeout=30)
		if resp.status_code == 401:
			self._fetch_token()
			headers = {"Authorization": self._get_token()}
			resp = self._session.post(url, json=body, headers=headers, timeout=30)
		if resp.status_code == 429:
			time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
			resp = self._session.post(url, json=body, headers=headers, timeout=30)
		if not resp.ok:
			raise IbexError(f"IBEX POST {path} failed: {resp.status_code} {resp.text[:200]}")
		return resp

	def add_invoice(self, account_id: str, amount: float, memo: str = "", expiration: int = 45) -> dict:
		"""Create an LN invoice ON one of our own accounts: POST /v2/invoice/add.

		amount is in the account's MAJOR units (dollars for USD/USDT — same
		as toIbex() in the flash backend). IBEX silently caps non-msat
		receive invoices at 60s expiration; we pay immediately, so 45s.
		Returns the response dict; bolt11 at invoice.bolt11.
		"""
		resp = self._post(
			"/v2/invoice/add",
			{"accountId": account_id, "amount": amount, "memo": memo, "expiration": expiration},
		)
		return resp.json()

	def pay_invoice(self, account_id: str, bolt11: str) -> dict:
		"""Pay a bolt11 FROM one of our own accounts: POST /v2/invoice/pay.

		Amount omitted — the invoice face value is paid. This is the same
		add-invoice-on-receiver / pay-from-sender primitive the flash
		cutover code uses for treasury moves.
		"""
		resp = self._post("/v2/invoice/pay", {"accountId": account_id, "bolt11": bolt11})
		return resp.json()

	def get_invoice_from_hash(self, invoice_hash: str) -> dict:
		"""Look up ONE invoice by its payment hash: GET /invoice/from-hash/{hash}.

		Read-only. Used by the funding receipt poll to confirm THIS specific
		invoice settled at IBEX — never a wallet-balance delta, which on an
		actively-transacting treasury wallet (bankowner's float grows with every
		cashout) would misread routine inflow as the funding payment.

		A 404 means the hub does not (yet) know the hash — returned as
		{not_found: True} so the poll keeps waiting instead of erroring. Note the
		path has no /v2 prefix (the hub serves from-hash under /invoice/...),
		matching the ibex-client library and the flash backend's settle verifier.
		The settled state lives at response state.id == 1 (SETTLED); see
		ibex_status.invoice_settled.
		"""
		resp = self._get(f"/invoice/from-hash/{invoice_hash}", {}, allow_not_found=True)
		if resp.status_code == 404:
			return {"hash": invoice_hash, "not_found": True}
		return resp.json()

	def get_account_details(self, account_id: str) -> dict:
		"""Live single-account read: GET /v2/account/{id}. balance in dollars.

		Drained/empty accounts can 404 ("Balance not found") — treated as zero.
		"""
		resp = self._get(f"/v2/account/{account_id}", {}, allow_not_found=True)
		if resp.status_code == 404:
			return {"id": account_id, "balance": 0.0, "not_found": True}
		return resp.json()

	def get_account_transactions(
		self, account_id: str, limit: int = 25, page: int = 0, sort: str = "settledAt"
	) -> list[dict]:
		"""Recent transactions for an account, newest first. Paged.

		NOTE: this endpoint is **0-indexed** (page 0 is the first page), unlike
		the 1-indexed bulk /v2/account endpoint. Getting this wrong silently
		returns an empty list.
		"""
		resp = self._get(
			f"/v2/transaction/account/{account_id}/all",
			{"limit": limit, "page": page, "sort": sort},
			allow_not_found=True,
		)
		if resp.status_code == 404:
			return []
		data = resp.json()
		return data if isinstance(data, list) else []

	def list_accounts_page(self, page: int, limit: int = PAGE_LIMIT) -> list[dict]:
		"""Return one page of org accounts, balances included (dollars)."""
		resp = self._get("/v2/account", {"expand": "true", "page": page, "limit": limit})
		data = resp.json()
		if not isinstance(data, list):
			raise IbexError(f"IBEX /v2/account returned non-list: {type(data).__name__}")
		return data

	def iter_all_accounts(self, progress_cb=None):
		"""Yield every org account across all pages, pacing between requests.

		Pages until an EMPTY page via census_core.sweep_pages — the prod hub
		silently caps the page size (limit=100 returns 25), so a short batch
		must never be read as "last page". progress_cb(pages_done,
		accounts_seen) is called after each page so the caller can persist
		scan progress for the UI.
		"""

		def fetch(page):
			if page > 1:
				time.sleep(REQUEST_INTERVAL_SECONDS)
			return self.list_accounts_page(page, PAGE_LIMIT)

		seen = 0
		try:
			for page, batch in sweep_pages(fetch, MAX_PAGES):
				for account in batch:
					seen += 1
					yield account
				if progress_cb:
					progress_cb(page, seen)
		except PageLimitExceeded as exc:
			raise IbexError(str(exc)) from exc

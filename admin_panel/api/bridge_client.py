"""Read-only client for the Bridge.xyz API (KYC customers).

Used by the bridge-kyc desk page to list every Bridge customer and read one
customer's full KYC/KYB state (endorsements, missing requirements). Auth is a
static ``Api-Key`` header. Endpoints used (verified against prod 2026-07-31):

  * bulk list   GET {api_url}/customers?limit=100[&starting_after=<id>]
                (newest first; response is {"count": N, "data": [...]})
  * detail      GET {api_url}/customers/{id}

Pagination terminates ONLY on an empty page — a short page is NOT proof of the
end (the IBEX hub silently caps page sizes and that inference truncated the
first wallet census; see census_core.sweep_pages for the same rule).

Config (site_config.json / frappe.conf):
  bridge_api_key  (required)
  bridge_api_url  (optional, default production https://api.bridge.xyz/v0)
"""

import re
import time
from urllib.parse import quote

import frappe
import requests

# Bulk-endpoint page size (Bridge maximum).
PAGE_LIMIT = 100

# One-shot backoff before retrying a request that hit a 429.
RATE_LIMIT_BACKOFF_SECONDS = 2.0

# Hard cap on pagination — defensive against a misbehaving API paging forever
# (200 pages * 100/page = 20k customers, far above current volume of ~40).
MAX_PAGES = 200

_DEFAULT_API_URL = "https://api.bridge.xyz/v0"

# Bridge customer ids are UUIDs. Endpoints validate against this before an id
# is ever placed in a URL path — anything looser would let a caller reach
# arbitrary Bridge API endpoints (query/path injection) through our key.
CUSTOMER_ID_RE = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

_session = None


def _get_session() -> requests.Session:
	global _session
	if _session is None:
		_session = requests.Session()
	return _session


class BridgeApiError(Exception):
	"""Bridge.xyz API error."""


class BridgeClient:
	"""Read-only Bridge.xyz client. Never add writes here — KYC state is owned
	by the flash backend + Bridge dashboard; this page only observes it."""

	def __init__(self):
		self.api_url = (frappe.conf.get("bridge_api_url") or _DEFAULT_API_URL).rstrip("/")
		self.api_key = frappe.conf.get("bridge_api_key")
		if not self.api_key:
			raise ValueError("bridge_api_key is not configured in site_config.json")
		self._session = _get_session()

	def _get(self, path: str, params: dict | None = None) -> dict:
		"""GET with the Api-Key header; backs off once on 429."""
		url = f"{self.api_url}{path}"
		headers = {"Api-Key": self.api_key}
		resp = self._session.get(url, params=params or {}, headers=headers, timeout=30)
		if resp.status_code == 429:
			time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
			resp = self._session.get(url, params=params or {}, headers=headers, timeout=30)
		if not resp.ok:
			raise BridgeApiError(f"Bridge GET {path} failed: {resp.status_code} {resp.text[:200]}")
		return resp.json()

	def list_customers(self) -> list:
		"""Every Bridge customer, newest first. Terminates only on an empty page."""
		customers = []
		starting_after = None
		for _ in range(MAX_PAGES):
			params = {"limit": PAGE_LIMIT}
			if starting_after:
				params["starting_after"] = starting_after
			batch = self._get("/customers", params).get("data") or []
			if not batch:
				return customers
			customers.extend(batch)
			starting_after = batch[-1].get("id")
			if not starting_after:
				raise BridgeApiError("Bridge customer page contained an entry without an id")
		raise BridgeApiError(f"Bridge customer pagination exceeded {MAX_PAGES} pages")

	def get_customer(self, customer_id: str) -> dict:
		"""One customer's full record, including endorsements/requirements.

		The id is percent-encoded (defense in depth — the endpoint validates
		UUID shape first) so it can never smuggle path segments or a query
		string into the request.
		"""
		return self._get(f"/customers/{quote(str(customer_id), safe='')}")

	def list_virtual_accounts(self, customer_id: str) -> list:
		"""A customer's Bridge virtual accounts (US deposit instructions)."""
		encoded = quote(str(customer_id), safe="")
		return self._get(f"/customers/{encoded}/virtual_accounts").get("data") or []

	def list_external_accounts(self, customer_id: str) -> list:
		"""A customer's linked external bank accounts (Plaid/Bridge)."""
		encoded = quote(str(customer_id), safe="")
		return self._get(f"/customers/{encoded}/external_accounts").get("data") or []

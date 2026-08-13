"""System accounts treasury: bankowner / funder / dealer / rewards live balances,
activity, cashout-payables coverage, and gated fund movement.

Money-flow facts this module leans on (verified in the flash codebase):
- wallets.id in mongo IS the IBEX account id, for system accounts too.
- A cashout is the USER paying an LN invoice created on the bankowner
  IBEX account — the full amount lands in bankowner; the fee is retained
  spread. The fiat leg (JMD from the physical bank) is what the Cashout
  doctype tracks as a payable.
- So: bankowner float GROWS with each cashout; "coverage" is float minus
  the USD-equivalent of unpaid cashouts (Pending / Draft / In Progress).
- Treasury moves between our own accounts = add_invoice on the receiver,
  pay_invoice from the sender (the cutover primitive).
"""

import math

import frappe
import requests

from .auth import audit_log, require_financial, require_roles
from .common import handle_api_errors
from .ibex_client import IbexClient
from .mongo_reader import load_accounts, load_wallets

SYSTEM_ROLES = ("bankowner", "funder", "dealer", "rewards")

# Cashouts whose fiat leg has not been paid out yet.
OUTSTANDING_CASHOUT_STATUSES = ("Pending", "Draft", "In Progress")

# Hard ceiling on a single transfer unless site_config raises it.
DEFAULT_TRANSFER_CAP_USD = 100.0

# Fat-finger ceiling on a single funding invoice. Funding brings money IN (no
# treasury outflow), so this is a sanity bound, not a risk limit — generous and
# separately configurable via site_config system_funding_cap_usd.
DEFAULT_FUNDING_CAP_USD = 100000.0

CURRENCY_BY_ID = {0: "BTC", 3: "USD", 29: "USDT"}

# IBEX pay-invoice status: 2 = SUCCEEDED (verified against the hub).
_IBEX_STATUS_SUCCEEDED = 2
_SETTLED_NAMES = {"SUCCEEDED", "SETTLED", "COMPLETE", "COMPLETED"}
_FAILED_NAMES = {"FAILED", "CANCELLED", "CANCELED", "EXPIRED"}


def _payment_nodes(payment):
	"""The payment envelope plus its nested transaction.payment, if any."""
	if not isinstance(payment, dict):
		return []
	nodes = [payment]
	inner = (payment.get("transaction") or {}).get("payment")
	if isinstance(inner, dict):
		nodes.append(inner)
	return nodes


def _payment_settled(payment):
	"""Did the LN payment affirmatively settle?

	Returns True (settled), False (affirmatively failed), or None (ambiguous —
	treat as unconfirmed, never as success). Fail-safe by design: an unknown
	response shape yields None so money is never reported moved on a guess.
	"""
	nodes = _payment_nodes(payment)
	for node in nodes:
		status = node.get("status")
		name = (status.get("name") if isinstance(status, dict) else None) or ""
		if name.upper() in _SETTLED_NAMES:
			return True
		if name.upper() in _FAILED_NAMES:
			return False
	for node in nodes:
		if node.get("statusId") == _IBEX_STATUS_SUCCEEDED:
			return True
		if isinstance(node.get("status"), int) and node["status"] == _IBEX_STATUS_SUCCEEDED:
			return True
	for node in nodes:
		fr = node.get("failureReason")
		if fr not in (None, 0):
			return False
	return None


def _payment_hash(payment):
	for node in _payment_nodes(payment):
		h = node.get("hash")
		if h:
			return h
	return ""


def _watchlist_map():
	"""Merge the two watchlist sources into {lowercased ref: {...}}.

	- `System Watchlist` doctype rows: UI-managed, each carries a per-account
	  `allow_transfers` opt-in (default off) and is removable from the page.
	- `system_watchlist` in site_config: legacy view-only list, never
	  transfer-eligible and not UI-managed.

	A ref may be a username or a mongo account id. Doctype rows win over
	config on the same ref.
	"""
	watch = {}
	for x in frappe.conf.get("system_watchlist") or []:
		watch[str(x).lower()] = {"ref": str(x), "allow_transfers": False, "managed": False, "label": None}
	for row in frappe.get_all("System Watchlist", fields=["account_ref", "label", "allow_transfers"]):
		watch[str(row.account_ref).lower()] = {
			"ref": str(row.account_ref),
			"allow_transfers": bool(row.allow_transfers),
			"managed": True,
			"label": row.label,
		}
	return watch


def _resolve_system_accounts():
	"""All role accounts + the watchlist, with their wallets.

	Role accounts (bankowner/funder/dealer/rewards) are always transfer-eligible.
	Watchlist accounts are VIEW-ONLY unless their doctype row has
	allow_transfers set — a deliberate per-account opt-in.
	"""
	accounts = load_accounts()
	wallets = load_wallets()

	by_account = {}
	for wallet_id, w in wallets.items():
		by_account.setdefault(w["account_id"], []).append(
			{"wallet_id": wallet_id, "mongo_currency": w.get("currency")}
		)

	watch = _watchlist_map()

	resolved = []
	for account_id, acc in accounts.items():
		role = (acc.get("role") or "user").lower()
		is_role_account = role in SYSTEM_ROLES
		username = str(acc.get("username") or "")
		# An account can match a watch entry by id OR username; prefer a managed
		# (doctype) entry so a legacy config entry can't mask a transfers-on row.
		candidates = [c for c in (watch.get(account_id.lower()), watch.get(username.lower())) if c]
		watch_entry = None
		if candidates:
			watch_entry = sorted(candidates, key=lambda c: 0 if c["managed"] else 1)[0]
		is_watch = watch_entry is not None
		if not (is_role_account or is_watch):
			continue
		allow_transfers = bool(watch_entry and watch_entry["allow_transfers"])
		resolved.append(
			{
				"account_id": account_id,
				"username": acc.get("username"),
				"role": role if is_role_account else "watchlist",
				"status": acc.get("status"),
				# role accounts always transferable; watchlist only on opt-in
				"transferable": is_role_account or allow_transfers,
				"allow_transfers": allow_transfers,
				"watch_managed": bool(watch_entry and watch_entry["managed"]),
				# the exact ref stored on the doctype row, so the page's
				# toggle/remove buttons hit the right record (id- or name-added)
				"watch_ref": watch_entry["ref"] if watch_entry else None,
				"wallets": sorted(by_account.get(account_id, []), key=lambda w: w["wallet_id"]),
			}
		)
	# bankowner first, then funder, dealer, rewards, watchlist
	order = {"bankowner": 0, "funder": 1, "dealer": 2, "rewards": 3, "watchlist": 4}
	resolved.sort(key=lambda a: (order.get(a["role"], 9), a["username"] or ""))
	return resolved


def _outstanding_payables():
	"""USD-equivalent of cashouts whose fiat payout hasn't happened.

	user_receives is denominated in `currency` (USD or JMD). For JMD rows
	the USD side is user_pays - flash_fee (what actually left the user's
	wallet minus our retained fee); fall back to user_receives / rate.
	"""
	rows = frappe.get_all(
		"Cashout",
		filters={"status": ["in", list(OUTSTANDING_CASHOUT_STATUSES)]},
		fields=["user_pays", "flash_fee", "user_receives", "currency", "exchange_rate"],
	)
	total = 0.0
	for r in rows:
		if (r.currency or "USD") == "JMD":
			usd = (r.user_pays or 0.0) - (r.flash_fee or 0.0)
			if not usd and r.exchange_rate:
				usd = (r.user_receives or 0.0) / r.exchange_rate
		else:
			usd = r.user_receives or 0.0
		total += max(usd, 0.0)
	return {"count": len(rows), "usd": round(total, 2)}


@frappe.whitelist()
@require_financial()
@handle_api_errors
def get_system_accounts():
	"""Live treasury snapshot: every system/watchlist wallet with its IBEX
	balance, plus payables coverage. Small N — fetched live, no snapshotting."""
	client = IbexClient()
	accounts = _resolve_system_accounts()

	bankowner_float = 0.0
	funder_float = 0.0
	for acc in accounts:
		for w in acc["wallets"]:
			details = client.get_account_details(w["wallet_id"])
			# Normalize to UPPERCASE: the mongo_currency fallback is title-case
			# ("Usdt"/"Btc"), which would fail the USD/USDT float check below and
			# the BTC exclusion in the transfer picker.
			currency = (
				CURRENCY_BY_ID.get(details.get("currencyId")) or w.get("mongo_currency") or "USD"
			).upper()
			balance = float(details.get("balance") or 0.0)
			w["currency"] = currency
			w["balance"] = balance
			w["not_found"] = bool(details.get("not_found"))
			# BTC balances are sats — never dollars; exclude from float math.
			if currency in ("USD", "USDT"):
				if acc["role"] == "bankowner":
					bankowner_float += balance
				elif acc["role"] == "funder":
					funder_float += balance

	payables = _outstanding_payables()
	return {
		"accounts": accounts,
		"payables": payables,
		"totals": {
			"bankowner_float": round(bankowner_float, 2),
			"funder_float": round(funder_float, 2),
			"free_float": round(bankowner_float - payables["usd"], 2),
		},
		"transfer_cap_usd": float(frappe.conf.get("system_transfer_cap_usd") or DEFAULT_TRANSFER_CAP_USD),
		"now": str(frappe.utils.now_datetime()),
	}


@frappe.whitelist()
@require_financial()
@handle_api_errors
def get_system_account_activity(wallet_id, page=0, limit=20):
	"""Recent IBEX transactions for ONE system/watchlist wallet.

	Membership is re-derived server-side — this endpoint must not become a
	generic read-any-wallet proxy."""
	wallet_id = frappe.utils.cstr(wallet_id)
	known = {w["wallet_id"] for acc in _resolve_system_accounts() for w in acc["wallets"]}
	if wallet_id not in known:
		frappe.throw("Not a system-account wallet", frappe.PermissionError)
	limit = max(1, min(int(limit or 20), 50))
	page = max(0, int(page or 0))
	raw = IbexClient().get_account_transactions(wallet_id, limit=limit, page=page)
	# Same normalized shape as customer.get_customer_detail transactions,
	# so the page reuses the census tx-table rendering unchanged.
	transactions = [
		{
			"id": tx.get("id"),
			"created_at": tx.get("createdAt"),
			"amount": tx.get("amount"),
			"network_fee": tx.get("networkFee"),
			"currency": CURRENCY_BY_ID.get(tx.get("currencyId")),
			"type_id": tx.get("transactionTypeId"),
		}
		for tx in raw
	]
	return {"wallet_id": wallet_id, "page": page, "transactions": transactions}


@frappe.whitelist()
@require_financial()
@handle_api_errors
def create_funding_invoice(wallet_id, amount_usd, memo=None):
	"""Generate a Lightning receive invoice so an EXTERNAL payer can fund a
	system wallet (bankowner/funder/dealer/rewards) from the page.

	No treasury money moves here — an invoice is created ON the wallet's IBEX
	account; the payer's Lightning payment credits it directly at IBEX. This is
	the inbound cousin of transfer_between_system_wallets and reuses the same
	sanctioned add_invoice (/v2/invoice/add) write — no new IBEX write path.

	Denominated (USD/USDT) IBEX receive invoices are capped at ~60s expiry by
	the hub, so the page counts down and regenerates — expiry_utc is returned
	for that. Returns only display fields, never the raw IBEX response.
	"""
	wallet_id = frappe.utils.cstr(wallet_id)
	try:
		amount = float(amount_usd)
	except (TypeError, ValueError):
		frappe.throw("Amount must be a number")
	# math.isfinite rejects NaN/inf, which slip past `amount > cap` (NaN
	# comparisons are always False) and would reach IBEX.
	if not math.isfinite(amount) or amount <= 0:
		frappe.throw("Amount must be a positive number")
	cap = float(frappe.conf.get("system_funding_cap_usd") or DEFAULT_FUNDING_CAP_USD)
	if amount > cap:
		frappe.throw(f"Amount exceeds the funding cap of ${cap:,.2f} (site_config system_funding_cap_usd)")

	# Membership re-derived server-side — never a generate-invoice-for-any-wallet
	# proxy.
	wallet = None
	for acc in _resolve_system_accounts():
		for w in acc["wallets"]:
			if w["wallet_id"] == wallet_id:
				wallet = {**w, "role": acc["role"]}
				break
		if wallet:
			break
	if not wallet:
		frappe.throw("Not a system-account wallet", frappe.PermissionError)
	# A denominated invoice on a BTC (sats) wallet means a different unit; the
	# page only offers Fund on USD/USDT rows, but guard the backend too.
	if (wallet.get("mongo_currency") or "").upper() == "BTC":
		frappe.throw("Funding invoices are USD/USDT only (BTC wallets use a different rail).")

	memo = frappe.utils.cstr(memo or "Treasury funding")
	# expiration=60 requests the hub's max window for a denominated invoice.
	invoice = IbexClient().add_invoice(wallet_id, amount, memo=memo, expiration=60)
	inv = invoice.get("invoice") or {}
	bolt11 = inv.get("bolt11")
	if not bolt11:
		raise ValueError(f"IBEX add_invoice returned no bolt11: {str(invoice)[:200]}")
	currency = (
		CURRENCY_BY_ID.get(invoice.get("currencyId")) or wallet.get("mongo_currency") or "USD"
	).upper()
	frappe.logger().info(f"funding_invoice wallet={wallet_id} amount={amount} by={frappe.session.user}")
	return {
		"wallet_id": wallet_id,
		"amount_usd": round(amount, 2),
		"currency": currency,
		"bolt11": bolt11,
		"expiry_utc": inv.get("expiryDateUtc"),
	}


@frappe.whitelist()
@require_financial()
@handle_api_errors
def get_system_wallet_balance(wallet_id):
	"""Live balance for ONE system wallet — a cheap single-wallet read for the
	funding modal's receipt poll (get_system_accounts fetches every wallet, too
	heavy to poll). Membership re-derived server-side."""
	wallet_id = frappe.utils.cstr(wallet_id)
	known = {w["wallet_id"] for acc in _resolve_system_accounts() for w in acc["wallets"]}
	if wallet_id not in known:
		frappe.throw("Not a system-account wallet", frappe.PermissionError)
	details = IbexClient().get_account_details(wallet_id)
	currency = (CURRENCY_BY_ID.get(details.get("currencyId")) or "USD").upper()
	return {
		"wallet_id": wallet_id,
		"currency": currency,
		"balance": float(details.get("balance") or 0.0),
		"not_found": bool(details.get("not_found")),
	}


@frappe.whitelist()
@require_roles(["System Manager"])
@handle_api_errors
def transfer_between_system_wallets(from_wallet_id, to_wallet_id, amount_usd, memo=None):
	"""Move funds between two ROLE wallets (bankowner/funder/dealer/rewards only —
	watchlist accounts are view-only). add_invoice on the receiver,
	pay_invoice from the sender; every attempt is a System Transfer Log doc.

	Capped per-transfer by site_config system_transfer_cap_usd
	(default DEFAULT_TRANSFER_CAP_USD). Raise deliberately, never in code.
	"""
	from_wallet_id = frappe.utils.cstr(from_wallet_id)
	to_wallet_id = frappe.utils.cstr(to_wallet_id)
	try:
		amount = float(amount_usd)
	except (TypeError, ValueError):
		frappe.throw("Amount must be a number")
	memo = frappe.utils.cstr(memo or "ERP treasury transfer")

	if from_wallet_id == to_wallet_id:
		frappe.throw("Sender and receiver are the same wallet")
	# math.isfinite rejects NaN/inf, which slip past `amount > cap` (NaN
	# comparisons are always False) and would reach IBEX.
	if not math.isfinite(amount) or amount <= 0:
		frappe.throw("Amount must be a positive number")
	cap = float(frappe.conf.get("system_transfer_cap_usd") or DEFAULT_TRANSFER_CAP_USD)
	if amount > cap:
		frappe.throw(
			f"Amount exceeds the per-transfer cap of ${cap:,.2f} (site_config system_transfer_cap_usd)"
		)

	transferable = {
		w["wallet_id"]: {**w, "role": acc["role"], "username": acc["username"]}
		for acc in _resolve_system_accounts()
		if acc["transferable"]
		for w in acc["wallets"]
	}
	if from_wallet_id not in transferable:
		frappe.throw("Sender is not a transfer-enabled system wallet")
	if to_wallet_id not in transferable:
		frappe.throw("Receiver is not a transfer-enabled system wallet")

	# Idempotency guard: a timed-out or otherwise unresolved prior transfer
	# from this wallet may have moved money we can't confirm. Block a new one
	# until it's reconciled, so a retry after a "Pending" can't double-spend.
	unresolved = frappe.db.get_value(
		"System Transfer Log",
		{"from_wallet": from_wallet_id, "status": ["in", ["Draft", "Pending"]]},
	)
	if unresolved:
		frappe.throw(
			f"A prior transfer from this wallet is unresolved ({unresolved}). "
			"Verify its outcome in the System Transfer Log before starting another."
		)

	log = frappe.get_doc(
		{
			"doctype": "System Transfer Log",
			"from_wallet": from_wallet_id,
			"to_wallet": to_wallet_id,
			"amount_usd": amount,
			"memo": memo,
			"status": "Draft",
			"initiated_by": frappe.session.user,
		}
	)
	log.insert(ignore_permissions=True)
	frappe.db.commit()

	client = IbexClient()
	# Step 1: create the invoice on the receiver. A failure here moved no money.
	try:
		invoice = client.add_invoice(to_wallet_id, amount, memo=memo)
		bolt11 = (invoice.get("invoice") or {}).get("bolt11")
		if not bolt11:
			raise ValueError(f"IBEX add_invoice returned no bolt11: {str(invoice)[:200]}")
	except Exception as e:
		log.db_set("status", "Failed")
		log.db_set("error", str(e)[:500])
		frappe.db.commit()
		raise

	# Step 2: pay it from the sender. A network timeout/connection error here
	# is INDETERMINATE — the LN payment may still settle server-side — so it is
	# NOT a failure. Mark Pending (the idempotency guard then blocks retries)
	# and tell the operator to reconcile.
	try:
		payment = client.pay_invoice(from_wallet_id, bolt11)
	except requests.exceptions.RequestException as e:
		log.db_set("status", "Pending")
		log.db_set("error", f"Indeterminate (network): {e}"[:500])
		frappe.db.commit()
		frappe.throw(
			"The payment outcome is UNKNOWN — the request timed out but the funds "
			"may have moved. Check balances and the System Transfer Log before retrying."
		)
	except Exception as e:
		log.db_set("status", "Failed")
		log.db_set("error", str(e)[:500])
		frappe.db.commit()
		raise

	# A 200 from IBEX means the pay request was accepted, not that it settled.
	# Only an affirmative SUCCEEDED marks Paid; an affirmative failure marks
	# Failed; anything ambiguous stays Pending for the operator to resolve.
	settled = _payment_settled(payment)
	if settled is True:
		log.db_set("status", "Paid")
		log.db_set("ibex_payment_hash", frappe.utils.cstr(_payment_hash(payment))[:140])
		frappe.db.commit()
		audit_log(
			"system_transfer",
			"System Transfer Log",
			log.name,
			{"from": from_wallet_id, "to": to_wallet_id, "amount_usd": amount},
		)
		return {"success": True, "log": log.name, "status": "Paid"}
	elif settled is False:
		log.db_set("status", "Failed")
		log.db_set("error", f"IBEX reported the payment not settled: {str(payment)[:400]}")
		frappe.db.commit()
		frappe.throw("IBEX did not settle the payment (see the System Transfer Log).")
	else:
		log.db_set("status", "Pending")
		log.db_set("error", f"IBEX settlement ambiguous: {str(payment)[:400]}")
		frappe.db.commit()
		frappe.throw(
			"IBEX accepted the payment but its settlement is unconfirmed. "
			"Check balances and the System Transfer Log before retrying."
		)


def _find_watchlist_doc(account_ref):
	ref = frappe.utils.cstr(account_ref).strip()
	name = frappe.db.get_value("System Watchlist", {"account_ref": ref})
	return ref, name


@frappe.whitelist()
@require_roles(["System Manager"])
@handle_api_errors
def add_watchlist_entry(account_ref, label=None):
	"""Add an ops account to the watchlist (view-only until opted into
	transfers). account_ref is a username or mongo account id and must
	resolve to a real account in mongo."""
	ref = frappe.utils.cstr(account_ref).strip()
	if not ref:
		frappe.throw("Account reference is required")

	accounts = load_accounts()
	known = ref in accounts or any(str(a.get("username") or "") == ref for a in accounts.values())
	if not known:
		frappe.throw(f"No account found for '{ref}' (username or mongo id)")
	if frappe.db.exists("System Watchlist", {"account_ref": ref}):
		frappe.throw(f"'{ref}' is already on the watchlist")

	doc = frappe.get_doc(
		{
			"doctype": "System Watchlist",
			"account_ref": ref,
			"label": frappe.utils.cstr(label or "") or None,
			"allow_transfers": 0,
			"added_by": frappe.session.user,
		}
	)
	doc.insert(ignore_permissions=True)
	audit_log("watchlist_add", "System Watchlist", doc.name, {"account_ref": ref})
	return {"success": True, "name": doc.name}


@frappe.whitelist()
@require_roles(["System Manager"])
@handle_api_errors
def remove_watchlist_entry(account_ref):
	"""Remove an account from the watchlist. Does not touch the account or
	its funds — only stops it from appearing on this page."""
	ref, name = _find_watchlist_doc(account_ref)
	if not name:
		frappe.throw(f"'{ref}' is not on the watchlist")
	frappe.delete_doc("System Watchlist", name, ignore_permissions=True)
	audit_log("watchlist_remove", "System Watchlist", name, {"account_ref": ref})
	return {"success": True}


@frappe.whitelist()
@require_roles(["System Manager"])
@handle_api_errors
def set_watchlist_transfers(account_ref, allow):
	"""Flip the per-account transfer opt-in. When on, the account becomes a
	valid transfer endpoint (still capped, still logged); when off it is
	view-only."""
	ref, name = _find_watchlist_doc(account_ref)
	if not name:
		frappe.throw(f"'{ref}' is not on the watchlist")
	allow_flag = 1 if frappe.utils.cint(allow) else 0
	frappe.db.set_value("System Watchlist", name, "allow_transfers", allow_flag)
	audit_log(
		"watchlist_transfers_" + ("on" if allow_flag else "off"),
		"System Watchlist",
		name,
		{"account_ref": ref},
	)
	return {"success": True, "allow_transfers": bool(allow_flag)}

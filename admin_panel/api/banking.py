"""Customer banking overview for the Account Hub "Banking" tab.

One endpoint, two sources:
  * ERPNext Bank Account records — the cashout rails, looked up exactly the
    way Cashout.validate does (party_type="Customer", party=erpParty).
  * Bridge — the US virtual account (full deposit instructions) and any
    linked external accounts, via the account's bridgeCustomerId in mongo.

Partial-tolerant on purpose (the Account Hub lesson): a Bridge or mongo
failure is reported inside the payload instead of failing the whole call, so
ERP bank accounts still render when the other side is down or unconfigured.
"""

import frappe
from frappe.utils import cstr

from .auth import require_admin
from .banking_core import slim_external_account, slim_virtual_account
from .bridge_client import CUSTOMER_ID_RE, BridgeApiError, BridgeClient
from .common import handle_api_errors
from .mongo_reader import find_account


def _erp_bank_accounts(erp_party):
	return frappe.get_all(
		"Bank Account",
		filters={"party_type": "Customer", "party": erp_party},
		fields=[
			"name",
			"account_name",
			"bank",
			"bank_account_no",
			"branch_code",
			"account_type",
			"currency",
			"is_default",
			"disabled",
		],
		order_by="is_default desc, creation asc",
	)


def _bridge_banking(account_ref):
	"""Bridge side of the payload. Never raises — errors are reported in-band."""
	try:
		account = find_account(account_ref)
	except Exception as e:  # mongo unconfigured/unreachable — degrade, don't fail the tab
		return {"linked": False, "error": f"mongo lookup failed: {e}"}
	if not account or not account.get("bridgeCustomerId"):
		return {"linked": False}

	customer_id = str(account["bridgeCustomerId"])
	if not CUSTOMER_ID_RE.fullmatch(customer_id):
		return {"linked": True, "customer_id": customer_id, "error": "stored bridgeCustomerId is not a UUID"}

	try:
		client = BridgeClient()
		return {
			"linked": True,
			"customer_id": customer_id,
			"kyc_status": account.get("bridgeKycStatus"),
			"virtual_accounts": [slim_virtual_account(v) for v in client.list_virtual_accounts(customer_id)],
			"external_accounts": [
				slim_external_account(e) for e in client.list_external_accounts(customer_id)
			],
		}
	except (BridgeApiError, ValueError) as e:
		return {"linked": True, "customer_id": customer_id, "error": str(e)}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_customer_banking(erp_party=None, account_ref=None):
	"""Full banking picture for one customer: ERP cashout accounts + Bridge."""
	erp_party = cstr(erp_party).strip()
	account_ref = cstr(account_ref).strip()
	if not erp_party and not account_ref:
		frappe.throw("erp_party or account_ref is required")

	return {
		"success": True,
		"erp_party": erp_party or None,
		"bank_accounts": _erp_bank_accounts(erp_party) if erp_party else [],
		"bridge": _bridge_banking(account_ref) if account_ref else {"linked": False},
	}

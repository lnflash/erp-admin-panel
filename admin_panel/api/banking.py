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

from .auth import audit_log, require_admin
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


# ---- Admin write endpoints (Banking tab) -----------------------------------
#
# flash's cashout GraphQL exposes bank accounts with NonNull bank / branch /
# account-number / type / currency fields — a single null-ish value can blank
# the customer's ENTIRE bankAccounts list in the app, and cashout validation
# only accepts JMD or USD. Everything is enforced here so an admin edit can
# never break a customer's cashout. Multiple accounts per customer are fully
# supported by the app (cashout takes an explicit bankAccountId).

ALLOWED_CURRENCIES = ("JMD", "USD")
ALLOWED_ACCOUNT_TYPES = ("Chequing", "Savings")


def _validate_bank_fields(bank_name, account_number, account_type, currency):
	bank_name = cstr(bank_name).strip()
	account_number = cstr(account_number).strip()
	account_type = cstr(account_type).strip()
	currency = cstr(currency).strip().upper()
	if not bank_name:
		frappe.throw("bank_name is required")
	if not account_number:
		frappe.throw("account_number is required")
	if account_type not in ALLOWED_ACCOUNT_TYPES:
		frappe.throw("account_type must be one of: " + ", ".join(ALLOWED_ACCOUNT_TYPES))
	if currency not in ALLOWED_CURRENCIES:
		frappe.throw("currency must be JMD or USD — cashout accepts nothing else")
	return bank_name, account_number, account_type, currency


def _ensure_bank_master(bank_name):
	"""Mirror of _create_erp_records: the Bank master must exist before linking."""
	if not frappe.db.exists("Bank", bank_name):
		frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)


def _owned_bank_account(bank_account_id, erp_party, for_update=False):
	"""Load a Bank Account and verify ownership (mirror of Cashout.validate and
	the ENG-509 approve flow) — party_type Customer + party must match."""
	bank_account = frappe.get_doc("Bank Account", cstr(bank_account_id).strip(), for_update=for_update)
	if bank_account.party_type != "Customer" or bank_account.party != erp_party:
		frappe.throw("Bank Account does not belong to this customer.")
	return bank_account


@frappe.whitelist()
@require_admin()
@handle_api_errors
def add_bank_account(
	erp_party,
	bank_name,
	account_number,
	account_type,
	currency,
	bank_branch=None,
	account_name=None,
	set_default=0,
):
	"""Create an additional cashout bank account for a customer.

	The first account for a customer becomes the default automatically.
	"""
	from frappe.utils import cint

	erp_party = cstr(erp_party).strip()
	if not erp_party or not frappe.db.exists("Customer", erp_party):
		frappe.throw("Unknown ERP customer — the account needs an ERP party first.")
	bank_name, account_number, account_type, currency = _validate_bank_fields(
		bank_name, account_number, account_type, currency
	)
	if frappe.db.exists("Bank Account", {"bank_account_no": account_number}):
		frappe.throw("A bank account with this account number already exists.")

	_ensure_bank_master(bank_name)
	existing = frappe.get_all(
		"Bank Account", filters={"party_type": "Customer", "party": erp_party}, pluck="name"
	)
	make_default = 1 if (cint(set_default) or not existing) else 0

	doc = frappe.get_doc(
		{
			"doctype": "Bank Account",
			"account_name": cstr(account_name).strip() or erp_party,
			"bank": bank_name,
			"bank_account_no": account_number,
			"branch_code": cstr(bank_branch).strip(),
			"account_type": account_type,
			"currency": currency,
			"is_company_account": 0,
			"is_default": make_default,
			"party_type": "Customer",
			"party": erp_party,
		}
	)
	doc.insert(ignore_permissions=True)
	if make_default:
		for name in existing:
			frappe.db.set_value("Bank Account", name, "is_default", 0)
	frappe.db.commit()

	audit_log(
		"add_bank_account",
		"Bank Account",
		doc.name,
		{
			"party": erp_party,
			"bank": bank_name,
			"bank_account_no": account_number,
			"currency": currency,
			"is_default": make_default,
		},
	)
	return {"success": True, "bank_account": doc.name}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def update_bank_account(
	bank_account_id,
	erp_party,
	bank_name,
	account_number,
	account_type,
	currency,
	bank_branch=None,
	account_name=None,
):
	"""Patch a customer's bank account in place (admin-initiated edit).

	Unlike the ENG-509 approve flow (which locks currency), a valid currency is
	required on every save — deliberately, so support can also HEAL records
	whose empty currency blanks the app's bankAccounts list.
	`name` and `is_default` are intentionally left untouched.
	"""
	erp_party = cstr(erp_party).strip()
	bank_name, account_number, account_type, currency = _validate_bank_fields(
		bank_name, account_number, account_type, currency
	)
	bank_account = _owned_bank_account(bank_account_id, erp_party, for_update=True)

	if frappe.db.exists(
		"Bank Account", {"bank_account_no": account_number, "name": ("!=", bank_account.name)}
	):
		frappe.throw("Another bank account already uses this account number.")

	_ensure_bank_master(bank_name)
	old_values = {
		"bank": bank_account.bank,
		"branch_code": bank_account.branch_code,
		"account_type": bank_account.account_type,
		"bank_account_no": bank_account.bank_account_no,
		"currency": bank_account.currency,
	}
	bank_account.bank = bank_name
	bank_account.branch_code = cstr(bank_branch).strip()
	bank_account.account_type = account_type
	bank_account.bank_account_no = account_number
	bank_account.currency = currency
	if cstr(account_name).strip():
		bank_account.account_name = cstr(account_name).strip()
	bank_account.save(ignore_permissions=True)
	frappe.db.commit()

	audit_log(
		"update_bank_account",
		"Bank Account",
		bank_account.name,
		{
			"party": erp_party,
			"old": old_values,
			"new": {
				"bank": bank_name,
				"branch_code": cstr(bank_branch).strip(),
				"account_type": account_type,
				"bank_account_no": account_number,
				"currency": currency,
			},
		},
	)
	return {"success": True}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def set_default_bank_account(bank_account_id, erp_party):
	"""Make one of the customer's bank accounts the default (clears the rest)."""
	erp_party = cstr(erp_party).strip()
	bank_account = _owned_bank_account(bank_account_id, erp_party)
	others = frappe.get_all(
		"Bank Account",
		filters={"party_type": "Customer", "party": erp_party, "name": ("!=", bank_account.name)},
		pluck="name",
	)
	for name in others:
		frappe.db.set_value("Bank Account", name, "is_default", 0)
	frappe.db.set_value("Bank Account", bank_account.name, "is_default", 1)
	frappe.db.commit()

	audit_log("set_default_bank_account", "Bank Account", bank_account.name, {"party": erp_party})
	return {"success": True}

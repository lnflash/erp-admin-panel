"""Bridge.xyz KYC status endpoints for the bridge-kyc desk page.

On-demand, live reads: every call hits Bridge + mongo directly (no snapshot
doctype — current volume is ~40 customers, one page). The overview joins
Bridge customers (source of truth for KYC state) to Flash accounts by
bridgeCustomerId; the detail endpoint returns one customer's full endorsement
and missing-requirements breakdown.
"""

import re
from datetime import datetime, timezone

import frappe
from frappe.utils import cstr

# Bridge customer ids are UUIDs. Validated before the id is ever placed in a
# URL path — anything looser would let a caller reach arbitrary Bridge API
# endpoints (query/path injection) through our key.
CUSTOMER_ID_RE = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

from .auth import require_admin
from .bridge_client import BridgeClient
from .bridge_kyc_core import build_detail, build_overview
from .common import handle_api_errors
from .mongo_reader import load_bridge_accounts


def _now_iso():
	"""UTC ISO stamp, comparable to Bridge's Z timestamps client-side."""
	return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_kyc_overview():
	"""All Bridge customers (live) joined to Flash accounts, plus status tallies."""
	customers = BridgeClient().list_customers()
	accounts = load_bridge_accounts()
	overview = build_overview(customers, accounts)
	overview["success"] = True
	overview["now"] = _now_iso()
	return overview


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_kyc_customer(customer_id):
	"""One customer's live KYC detail (endorsements, missing items, rejections)."""
	customer_id = cstr(customer_id).strip()
	if not CUSTOMER_ID_RE.fullmatch(customer_id):
		frappe.throw("customer_id must be a Bridge customer UUID")
	customer = BridgeClient().get_customer(customer_id)
	return {"success": True, "now": _now_iso(), "customer": build_detail(customer)}

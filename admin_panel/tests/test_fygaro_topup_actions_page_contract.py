"""Contract tests for the operator Complete / Cancel actions on card top-ups.

These actions are record-only: an operator who has already sent (or decided not
to send) a Fygaro card top-up to the user's wallet stamps the audit row's status
from the Transfer Requests page. The tests below pin the whitelisted API
functions, their Fygaro + Fiat-Received guards, the new ``Cancelled`` status,
and the drawer buttons.

The admin_panel test suite runs without a Frappe bench (no site, no DB), so a
Bridge Transfer Request document cannot be instantiated here. We assert the
source contract instead, matching the existing page-contract style.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
PAGE_DIR = ADMIN_PANEL / "admin_panel" / "page" / "transfer_requests"
DOCTYPE_JSON = (
	ADMIN_PANEL / "admin_panel" / "doctype" / "bridge_transfer_request" / "bridge_transfer_request.json"
)


def read_text(path):
	return path.read_text()


def test_doctype_status_gains_cancelled_option():
	doctype = json.loads(DOCTYPE_JSON.read_text())
	status_field = next(f for f in doctype["fields"] if f["fieldname"] == "status")

	assert status_field["options"] == "Pending\nFiat Received\nSettled\nCompleted\nFailed\nCancelled"
	# Backward compatible: the pre-existing states are untouched, Cancelled is
	# appended so historical rows keep their status.
	assert status_field["options"].startswith("Pending\nFiat Received\nSettled\nCompleted\nFailed")


def test_admin_api_exposes_record_only_topup_actions():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert "def complete_fygaro_topup(request_id, final_amount=None, wallet_id=None):" in api_py
	assert "def cancel_fygaro_topup(request_id, reason=None):" in api_py


def test_topup_actions_use_financial_decorator_stack():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")
	normalized = " ".join(api_py.split())

	# These stamp a top-up Completed / Cancelled — the same money-credited trust
	# boundary as settling a cashout — so they must carry @require_financial(),
	# which excludes the weaker Flash Admin role, exactly like the cashout
	# settlement endpoints (create_cashout_request, confirm_cashout_payment,
	# complete_cashout).
	for fn in ("complete_fygaro_topup", "cancel_fygaro_topup"):
		assert (
			f"@frappe.whitelist() @require_financial() @handle_api_errors def {fn}(" in normalized
		), f"{fn} must carry the whitelist/require_financial/handle_api_errors stack"


def test_topup_actions_wire_the_core_eligibility_guard():
	"""The loader must delegate the allow/reject decision to fygaro_topup_core.

	Correctness of the allow/reject matrix itself is covered behaviorally in
	test_fygaro_topup_core.py; this only pins that admin_api actually calls it
	(rather than re-implementing a drifting inline guard).
	"""
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	# The pure predicate lives in the core module and is called from the loader.
	assert "from .fygaro_topup_core import rejection_reason" in api_py
	assert "reason = rejection_reason(doc.provider, doc.status, action)" in api_py
	assert "_load_fygaro_topup_for_status_action" in api_py
	# The row is looked up by the unique request_id, not the docname, under a
	# for_update lock so a concurrent double-complete serializes.
	assert 'frappe.db.get_value("Bridge Transfer Request", {"request_id": request_id}, "name")' in api_py
	assert 'frappe.get_doc("Bridge Transfer Request", name, for_update=True)' in api_py


def test_complete_sets_completed_and_optional_amount_and_wallet():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert 'doc.status = "Completed"' in api_py
	assert "doc.final_amount = final_amount" in api_py
	assert "doc.wallet_id = wallet_id" in api_py


def test_cancel_sets_cancelled_and_optional_reason():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert 'doc.status = "Cancelled"' in api_py
	assert "doc.failure_reason = reason" in api_py


def test_topup_actions_are_record_only():
	"""No money movement: these must not settle, submit, or touch IBEX/GraphQL."""
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")
	# Isolate the two functions' bodies to keep the negative assertions honest.
	start = api_py.index("def complete_fygaro_topup(")
	end = api_py.index("def _get_cashout_for_action(")
	block = api_py[start:end]

	# Concrete call syntax only — prose in the docstrings ("no money moves, no
	# IBEX") legitimately names these systems while explaining what is skipped.
	for forbidden in (
		"_settle_cashout(",
		"create_payment_journal_entry(",
		".submit()",
		"ibex_client",
		"graphql_client",
		"send_cashout_notification(",
	):
		assert forbidden not in block, f"record-only actions must not reference {forbidden}"


def test_drawer_renders_actions_only_for_fygaro_fiat_received():
	js = read_text(PAGE_DIR / "transfer_requests.js")
	normalized = " ".join(js.split())

	assert (
		'const showFygaroActions = req.provider === "Fygaro" && req.status === "Fiat Received"' in normalized
	)
	assert "btn-complete-fygaro" in js
	assert "btn-cancel-fygaro" in js
	assert "Mark Completed" in js
	# The actions block is empty (not rendered) when the guard is false.
	assert "const fygaroActions = showFygaroActions" in normalized


def test_drawer_action_methods_guard_and_call_backend():
	js = read_text(PAGE_DIR / "transfer_requests.js")
	normalized = " ".join(js.split())

	assert "complete_fygaro_topup(req)" in js
	assert "cancel_fygaro_topup(req)" in js
	# Client-side guard mirrors the server guard.
	assert 'if (!req || req.provider !== "Fygaro" || req.status !== "Fiat Received") return;' in normalized
	assert "admin_panel.api.admin_api.complete_fygaro_topup" in js
	assert "admin_panel.api.admin_api.cancel_fygaro_topup" in js
	# Complete prompts for the credited amount; cancel confirms then optionally
	# collects a reason.
	assert "default: req.amount" in js
	assert "Cancel this card top-up? It will not be credited." in js
	# Success path refreshes the list and closes the drawer so the buttons and
	# badge update.
	assert "this.close_details();" in js
	assert "this.load_requests();" in js


def test_cancelled_status_has_muted_badge_class():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert 'CANCELLED: "Cancelled"' in js
	assert '[BridgeStatus.CANCELLED]: "cashout-badge-cancelled"' in js

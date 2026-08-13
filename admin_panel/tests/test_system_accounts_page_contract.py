"""Contract tests for the System Accounts treasury page + API.

The invariants that matter here are the money ones: read endpoints carry
the financial gate, the transfer endpoint is System-Manager-only with a
cap and a role-wallet-only guard, and every attempt lands in the
append-only System Transfer Log.
"""

import json
import re
from pathlib import Path

ADMIN_PANEL = Path(__file__).resolve().parents[1]
API_PY = (ADMIN_PANEL / "api" / "system_accounts.py").read_text()
IBEX_PY = (ADMIN_PANEL / "api" / "ibex_client.py").read_text()
PAGE_JS = (ADMIN_PANEL / "admin_panel" / "page" / "system_accounts" / "system_accounts.js").read_text()
SETUP_PY = (ADMIN_PANEL / "admin_panel" / "setup.py").read_text()


def test_read_endpoints_carry_the_financial_gate():
	for fn in ("get_system_accounts", "get_system_account_activity"):
		stack = f"@frappe.whitelist()\n@require_financial()\n@handle_api_errors\ndef {fn}("
		assert stack in API_PY, f"{fn} must be whitelisted + require_financial + handle_api_errors"


def test_transfer_endpoint_is_system_manager_only_with_cap_and_role_guard():
	stack = (
		'@frappe.whitelist()\n@require_roles(["System Manager"])\n'
		"@handle_api_errors\ndef transfer_between_system_wallets("
	)
	assert stack in API_PY
	assert "system_transfer_cap_usd" in API_PY
	assert "DEFAULT_TRANSFER_CAP_USD" in API_PY
	# only transfer-enabled wallets qualify (role accounts + opted-in watch)
	assert 'if acc["transferable"]' in API_PY
	assert '"Sender is not a transfer-enabled system wallet"' in API_PY
	assert '"Receiver is not a transfer-enabled system wallet"' in API_PY


def test_watchlist_is_opt_in_for_transfers():
	# role accounts always transferable; watchlist only when allow_transfers
	assert '"transferable": is_role_account or allow_transfers' in API_PY
	# management endpoints are all System Manager only
	for fn in ("add_watchlist_entry", "remove_watchlist_entry", "set_watchlist_transfers"):
		stack = f'@frappe.whitelist()\n@require_roles(["System Manager"])\n@handle_api_errors\ndef {fn}('
		assert stack in API_PY, f"{fn} must be whitelisted + System Manager + handle_api_errors"
	# adding validates the account actually exists in mongo
	assert "No account found for" in API_PY
	# config watchlist stays view-only (managed=False), never opt-in-able
	assert '"managed": False' in API_PY


def test_every_transfer_attempt_is_logged_before_money_moves():
	insert_pos = API_PY.index('"doctype": "System Transfer Log"')
	pay_pos = API_PY.index("client.add_invoice(")
	assert insert_pos < pay_pos, "the log doc must be inserted before any IBEX call"
	assert 'log.db_set("status", "Failed")' in API_PY
	assert 'log.db_set("status", "Paid")' in API_PY


def test_transfer_cap_is_actually_enforced():
	# the cap must be COMPARED and throw, not merely referenced — otherwise
	# enforcement could be deleted with the presence-only tests still green
	assert "if amount > cap:" in API_PY
	assert "exceeds the per-transfer cap" in API_PY


def test_paid_only_on_confirmed_settlement():
	# a 200 from IBEX is not proof of settlement — Paid must gate on an
	# affirmative _payment_settled() is True, never on absence of an exception
	assert "_payment_settled(payment)" in API_PY
	assert "if settled is True:" in API_PY
	# helper is fail-safe: unknown shape returns None (ambiguous), not success
	assert "def _payment_settled(" in API_PY
	assert "return None" in API_PY


def test_indeterminate_pay_is_pending_not_failed():
	# a network timeout/connection error is NOT a failure (the LN payment may
	# still settle) — it must mark Pending so the idempotency guard blocks retry
	assert "except requests.exceptions.RequestException" in API_PY
	assert 'log.db_set("status", "Pending")' in API_PY


def test_transfer_has_idempotency_guard():
	# a new transfer from a wallet with an unresolved (Draft/Pending) prior
	# transfer must be refused, so a retry after a timeout cannot double-spend
	assert '"status": ["in", ["Draft", "Pending"]]' in API_PY
	assert "unresolved" in API_PY


def test_transfer_rejects_non_finite_amount():
	# NaN/inf slip past `amount > cap` (NaN comparisons are False); math.isfinite
	# must gate the amount before it can reach IBEX
	assert "math.isfinite(amount)" in API_PY


def test_transfer_does_not_leak_raw_ibex_response():
	# the raw pay_invoice response carries the LN preimage; the endpoint must
	# return only what the UI needs, not the whole blob
	assert 'return {"success": True, "log": log.name, "status": "Paid"}' in API_PY
	assert '"payment": payment' not in API_PY


def test_activity_endpoint_revalidates_wallet_membership():
	assert '"Not a system-account wallet"' in API_PY
	assert "frappe.PermissionError" in API_PY


def test_funding_invoice_is_financial_gated_membership_checked_and_capped():
	stack = "@frappe.whitelist()\n@require_financial()\n@handle_api_errors\ndef create_funding_invoice("
	assert (
		stack in API_PY
	), "create_funding_invoice must be whitelisted + require_financial + handle_api_errors"
	# reuses the sanctioned add_invoice write — no new IBEX write path
	assert "IbexClient().add_invoice(" in API_PY
	# membership re-derived server-side — not a generate-for-any-wallet proxy
	assert '"Not a system-account wallet"' in API_PY
	# fat-finger ceiling: configurable AND actually compared, not just referenced
	assert "system_funding_cap_usd" in API_PY
	assert "DEFAULT_FUNDING_CAP_USD" in API_PY
	assert "exceeds the funding cap" in API_PY
	# returns only display fields — never the raw IBEX invoice blob
	assert '"invoice": invoice' not in API_PY


def test_wallet_balance_read_is_financial_gated_and_membership_checked():
	stack = "@frappe.whitelist()\n@require_financial()\n@handle_api_errors\ndef get_system_wallet_balance("
	assert stack in API_PY
	assert '"Not a system-account wallet"' in API_PY


def test_funding_ui_is_wired_and_usd_usdt_only():
	assert "admin_panel.api.system_accounts.create_funding_invoice" in PAGE_JS
	assert "admin_panel.api.system_accounts.get_system_wallet_balance" in PAGE_JS
	assert "sa-fund-btn" in PAGE_JS
	# Fund is only offered on USD/USDT rows — BTC uses a different rail
	assert 'w.currency === "USD" || w.currency === "USDT"' in PAGE_JS


def test_ibex_client_write_surface_is_exactly_the_two_invoice_calls():
	assert '"/v2/invoice/add"' in IBEX_PY
	assert '"/v2/invoice/pay"' in IBEX_PY
	posts = re.findall(r"self\._post\(\s*\n?\s*\"([^\"]+)\"", IBEX_PY)
	assert set(posts) <= {"/v2/invoice/add", "/v2/invoice/pay"}, f"unexpected IBEX write endpoints: {posts}"


def test_page_gates_and_wiring():
	assert 'SA_VIEW_ROLES = ["System Manager", "Accounts Manager"]' in PAGE_JS
	assert "Flash Admin" not in PAGE_JS  # view tier matches require_financial
	assert 'frappe.user_roles.includes("System Manager")' in PAGE_JS  # transfer control gate
	assert "admin_panel.api.system_accounts.get_system_accounts" in PAGE_JS
	assert "admin_panel.api.system_accounts.get_system_account_activity" in PAGE_JS
	assert "admin_panel.api.system_accounts.transfer_between_system_wallets" in PAGE_JS
	assert "frappe.confirm(" in PAGE_JS  # transfers are review-then-confirm


def test_page_css_stays_scoped():
	css = PAGE_JS[PAGE_JS.index("SA_CSS") : PAGE_JS.index("frappe.pages")]
	leaks = re.findall(r"\n\s+(\.(?:form-control|modern-[a-z-]+|sa-[a-z-]+)[^\n{]*)\{", css)
	assert not leaks, f"unscoped selectors in system_accounts CSS: {leaks}"


def test_page_is_registered_everywhere():
	assert '"name": "system-accounts"' in SETUP_PY
	workspace = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
	links = workspace[0]["links"] if isinstance(workspace, list) else workspace["links"]
	assert any(l.get("link_type") == "Page" and l.get("link_to") == "system-accounts" for l in links)
	page_json = json.loads(
		(ADMIN_PANEL / "admin_panel" / "page" / "system_accounts" / "system_accounts.json").read_text()
	)
	assert page_json["name"] == "system-accounts"
	assert page_json["title"] == "System Accounts"


def test_transfer_log_doctype_is_append_only():
	dt = json.loads(
		(
			ADMIN_PANEL / "admin_panel" / "doctype" / "system_transfer_log" / "system_transfer_log.json"
		).read_text()
	)
	assert dt["in_create"] == 1  # no desk New button
	for perm in dt["permissions"]:
		assert (
			not perm.get("write") and not perm.get("create") and not perm.get("delete")
		), f"System Transfer Log must be read-only via desk: {perm}"

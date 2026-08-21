import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
PAGE_DIR = ADMIN_PANEL / "admin_panel" / "page" / "transfer_requests"


def read_text(path):
	return path.read_text()


def workspace_links():
	workspace = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
	return workspace["links"]


def test_admin_dashboard_routes_transfer_requests_card_to_custom_page():
	"""The dashboard renders its tiles from the nav registry now, so the
	destination is asserted there rather than in the page markup."""
	from admin_panel.api.nav_core import by_route

	link = by_route()["transfer-requests"]

	assert link["kind"] == "page"
	assert link["label"] == "Transfer Requests"
	# The raw doctype list is a separate tile; the operator queue is the page.
	assert by_route()["bridge-transfer-request"]["kind"] == "doctype"


def test_setup_registers_transfer_requests_page_not_cashout_requests():
	setup_py = read_text(ADMIN_PANEL / "admin_panel" / "setup.py")

	assert '"name": "transfer-requests"' in setup_py
	assert '"title": "Transfer Requests"' in setup_py
	assert '"name": "cashout-requests"' not in setup_py
	assert 'delete_doc("Page", "cashout-requests"' in setup_py


def test_transfer_requests_page_fixture_replaces_cashout_requests_page():
	page_json = json.loads((PAGE_DIR / "transfer_requests.json").read_text())

	assert page_json["name"] == "transfer-requests"
	assert page_json["page_name"] == "transfer-requests"
	assert page_json["title"] == "Transfer Requests"
	assert not (ADMIN_PANEL / "admin_panel" / "page" / "cashout_requests").exists()


def test_transfer_requests_js_registers_page_and_bridge_tab():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert 'frappe.pages["transfer-requests"]' in js
	assert "TransferRequestsManager" in js
	assert "Cashouts" in js
	assert "Bridge" in js
	assert "get_bridge_transfer_requests" in js


def test_workspace_keeps_doctype_links_and_removes_cashout_requests_page_link():
	links = workspace_links()

	assert any(link["link_type"] == "DocType" and link["link_to"] == "Cashout" for link in links)
	assert any(
		link["link_type"] == "DocType" and link["link_to"] == "Bridge Transfer Request" for link in links
	)
	assert any(
		link["link_type"] == "Page"
		and link["label"] == "Transfer Requests"
		and link["link_to"] == "transfer-requests"
		for link in links
	)
	assert not any(
		link["link_type"] == "Page"
		and (link["label"] == "Cashout Requests" or link["link_to"] == "cashout-requests")
		for link in links
	)


def test_admin_api_exposes_bridge_transfer_requests_read_only_endpoint():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert "def get_bridge_transfer_requests" in api_py
	assert '"Bridge Transfer Request"' in api_py
	assert "transaction_type" in api_py
	assert "failure_reason" in api_py


def test_transfer_requests_cashout_tab_has_account_management_style_action_buttons():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert "create_request_row(req, showActions = true)" in js
	assert '"Actions"' in js
	assert "modern-icon-btn" in js
	assert "btn-quick-create" in js
	assert "btn-quick-confirm" in js
	assert "btn-quick-complete" in js
	assert "e.stopPropagation()" in js
	assert 'closest("button")' in js
	assert "create_cashout_request(req)" in js
	assert "confirm_cashout_payment(req)" in js
	assert "complete_cashout(req)" in js


def test_transfer_requests_bridge_tab_stays_read_only_without_actions_column():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert "const cashoutHeaders" in js
	assert "const bridgeHeaders" in js
	# Both audit tabs (Bridge + Card Top-Ups) share bridgeHeaders; only the
	# cashout tab gets the actions column.
	assert 'const headers = this.active_type !== "cashout" ? bridgeHeaders : cashoutHeaders' in js
	normalized = " ".join(js.split())
	assert (
		'const bridgeHeaders = [ "Request ID", "Payer", "Type", "Amount", "Status", "Failure", "Last Seen", ]'
		in normalized
	)


def test_admin_api_exposes_cashout_action_endpoints():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert "def create_cashout_request" in api_py
	assert "def confirm_cashout_payment" in api_py
	assert "def complete_cashout" in api_py
	assert "confirmation_code" in api_py


def test_cashout_completion_calls_flash_notification_mutation():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")
	graphql_client_py = read_text(ADMIN_PANEL / "api" / "graphql_client.py")

	assert "CASHOUT_NOTIFICATION_SEND_MUTATION" in graphql_client_py
	assert "cashoutNotificationSend" in graphql_client_py
	assert "def send_cashout_notification" in graphql_client_py
	assert "_send_cashout_completion_notification" in api_py
	assert "send_cashout_notification(" in api_py
	assert "_cashout_notification_amount_cents" in api_py
	assert "Flash notification sent" in api_py


def test_cashout_completion_lookup_ignores_invalid_flash_identifiers():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")
	graphql_client_py = read_text(ADMIN_PANEL / "api" / "graphql_client.py")

	assert '"INVALID_INPUT"' in graphql_client_py
	assert "def _is_flash_username_candidate" in api_py
	assert "_is_flash_username_candidate(username)" in api_py


def test_cashout_payment_bank_entry_sets_required_reference_fields():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")
	cashout_py = read_text(ADMIN_PANEL / "admin_panel" / "doctype" / "cashout" / "cashout.py")

	assert "def create_payment_journal_entry(self, reference_no=None, reference_date=None)" in cashout_py
	assert "payment_reference_no = reference_no or self.transaction_id or self.name" in cashout_py
	assert '"cheque_no": payment_reference_no' in cashout_py
	assert '"cheque_date": payment_reference_date' in cashout_py
	assert "doc.create_payment_journal_entry(reference_no=confirmation_code" in api_py
	assert "frappe.msgprint" not in cashout_py


def test_cashout_details_render_remarks_from_cashout_record():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert '<span class="detail-label">Remarks</span>' in js
	assert "detail-remarks" in js
	assert 'panel.find(".detail-remarks").text(req.remarks || "-")' in js


def test_audit_rows_carry_payer_identity_and_search_covers_raw_payload():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert "def _attach_payer_identity" in api_py
	assert "_attach_payer_identity([dict(record) for record in records])" in api_py
	assert "load_payer_identities" in api_py
	assert "build_payer_fields" in api_py
	# Ref collection and identity matching are pure + unit-tested in
	# transfer_identity_core, not hand-rolled in the IO layer.
	assert "collect_lookup_refs" in api_py
	assert "match_account_identity" in api_py
	assert '["raw_payload_json", "like", like_query]' in api_py


def test_audit_table_and_detail_drawer_render_payer_identity():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	# The table's Payer column must go through payerValue so provider-sourced
	# (unverified checkout) values are labeled in the table, not only the drawer.
	normalized = " ".join(js.split())
	assert (
		'const payerDisplay = this.payerValue(req, "payer_username") || '
		'this.payerValue(req, "payer_name") || "-"' in normalized
	)
	assert "req.payer_username || req.payer_name" not in js
	assert "payerValue(req, field, format)" in js
	for field in ("payer_name", "payer_username", "payer_email", "payer_phone"):
		assert f'this.payerValue(req, "{field}"' in js
	assert "(from provider)" in js

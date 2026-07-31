import re
from pathlib import Path

ACCOUNT_HUB_JS = (
	Path(__file__).resolve().parents[1] / "admin_panel" / "page" / "account_hub" / "account_hub.js"
)


def source():
	return ACCOUNT_HUB_JS.read_text()


def test_filter_local_list_contains_matches_all_identity_fields():
	"""The default list filters inline with case-insensitive contains-matching
	across username / phone / email / account id, and an empty query restores
	the full list."""
	js = source()
	body = js.split("filter_local_list(query) {", 1)[1].split("\n\t}", 1)[0]
	assert "this.render_result_list(this.default_results)" in body
	for field in ("username", "phone_number", "email", "name"):
		assert f"r.{field}" in body, f"filter must match on {field}"
	assert body.count(".toLowerCase().includes(q)") == 4


def test_search_input_filters_inline_and_debounces_remote_exact_search():
	"""Typing filters the local default list instantly; the remote exact search
	runs only behind the debounce so keystrokes never spam the API. Both paths
	are load-bearing: local for responsiveness, remote for accounts that are
	not in the default list."""
	js = source()
	handler = re.search(
		r'searchInput\.on\("input", \(\) => \{(?P<body>.*?)\n\t\t\}\);',
		js,
		re.DOTALL,
	)
	assert handler, "Expected Account Hub search input handler"
	body = handler.group("body")
	assert "this.filter_local_list(val)" in body
	assert "debouncedSearch()" in body
	assert "perform_search_with_query" not in body, "remote call must go through the debounce wrapper"
	assert "const debouncedSearch = debounce(" in js


def test_result_clicks_stay_on_account_hub_and_select_account():
	"""Clicking a result selects the account in place — it must never route off
	to a Form view (the regression this file exists to prevent)."""
	js = source()
	assert 'item.on("click", () => this.on_result_click(account, item));' in js
	body = js.split("on_result_click(account, itemEl) {", 1)[1].split("\n\t}", 1)[0]
	assert 'removeClass("active")' in body
	assert 'itemEl.addClass("active")' in body
	assert "frappe.set_route('Form', 'Account Upgrade Request'" not in js
	assert 'frappe.set_route("Form"' not in js


def test_search_error_path_surfaces_server_message_before_generic():
	"""Not-found searches return a friendly 404 body; the error callback must
	show that message rather than always claiming a connection problem."""
	js = source()

	assert "const serverMsg =" in js
	assert "err.responseJSON" in js
	assert 'serverMsg || "Could not reach the server.' in js


def test_graphql_client_treats_invalid_account_id_as_not_found():
	client_py = (ACCOUNT_HUB_JS.parents[3] / "api" / "graphql_client.py").read_text()

	assert "_is_not_found_error" in client_py
	assert "InvalidAccountIdError" in client_py
	assert "UNEXPECTED_CLIENT_ERROR" in client_py


def test_graphql_client_lookups_tolerate_partial_responses():
	"""A resolved account node with field-level errors (e.g. Kratos 404 on
	owner.email) must be returned with nulls, not raised — the admin panel
	exists to inspect broken accounts."""
	client_py = (ACCOUNT_HUB_JS.parents[3] / "api" / "graphql_client.py").read_text()

	assert "GraphQL partial response" in client_py
	assert "if allow_not_found:" in client_py

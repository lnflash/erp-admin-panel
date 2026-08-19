"""Source-level contract for the specific-user target on the Alert Users page.

Scope is deliberately narrow: the things a running test cannot observe — the
decorator stack wrapping each whitelisted endpoint, the doctype schema, and the
rendered markup. Everything behavioural lives next door and is exercised for
real:

* ``test_admin_api_send_user_alert.py`` calls ``send_user_alert`` /
  ``get_user_alerts`` against a stubbed frappe and a canned GraphQL client.
* ``test_alert_users_page_behavior.py`` runs alert_users.js under Node and
  asserts on which endpoint the page called with which arguments.

Do not grow this file with ``assert "<literal source line>" in source`` checks
for behaviour those two cover — a source grep passes just as happily when the
line is present and wrong.
"""

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
API_PY = ADMIN_PANEL / "api" / "admin_api.py"
PAGE_JS = ADMIN_PANEL / "admin_panel" / "page" / "alert_users" / "alert_users.js"
PAGE_JSON = ADMIN_PANEL / "admin_panel" / "page" / "alert_users" / "alert_users.json"
DOCTYPE_JSON = ADMIN_PANEL / "admin_panel" / "doctype" / "user_alerts" / "user_alerts.json"


def read_text(path):
	return path.read_text()


def load_doctype():
	return json.loads(DOCTYPE_JSON.read_text())


# --- User Alerts doctype ---


def test_doctype_gains_optional_target_username_field():
	doctype = load_doctype()
	field = next(f for f in doctype["fields"] if f["fieldname"] == "target_username")

	assert field["fieldtype"] == "Data"
	# Optional on purpose: broadcast rows have no target.
	assert not field.get("reqd")
	assert "target_username" in doctype["field_order"]


def test_doctype_existing_fields_are_untouched():
	doctype = load_doctype()
	fieldnames = [f["fieldname"] for f in doctype["fields"]]

	# Backward compatible: the broadcast fields keep their names and the tag
	# stays required, so historical broadcast rows still validate.
	for existing in ("title", "message", "tag", "sent_by", "sent_on"):
		assert existing in fieldnames
	tag_field = next(f for f in doctype["fields"] if f["fieldname"] == "tag")
	assert tag_field["reqd"] == 1


def test_doctype_read_stays_system_manager_only():
	# get_user_alerts reads with frappe.get_all (ignore_permissions), so this
	# is the gate for Desk / API list views only — the endpoint carries its own
	# @require_admin(). Widening this role would expose DIRECT rows, which name
	# the customer support messaged privately.
	doctype = load_doctype()

	assert [p["role"] for p in doctype["permissions"]] == ["System Manager"]


# --- endpoint decorator stacks ---


def test_send_user_alert_carries_the_admin_stack():
	normalized = " ".join(read_text(API_PY).split())

	# Same trust boundary as the topic broadcast: an admin-only push send.
	# Order matters — the role check must sit outside handle_api_errors so a
	# refusal surfaces as a PermissionError rather than a generic 500.
	assert (
		"@frappe.whitelist() @require_admin() @handle_api_errors "
		"def send_user_alert(username, title, message):" in normalized
	)


def test_get_user_alerts_carries_the_admin_stack():
	normalized = " ".join(read_text(API_PY).split())

	assert (
		"@frappe.whitelist() @require_admin() @handle_api_errors "
		"def get_user_alerts(limit=10):" in normalized
	)


def test_get_alert_types_carries_the_admin_stack():
	# The Page doc below carries no roles, so /app/alert-users opens for every
	# logged-in user; each endpoint it calls is its own trust boundary. This one
	# makes the panel mint an admin JWT and run a Flash admin query.
	normalized = " ".join(read_text(API_PY).split())

	assert "@frappe.whitelist() @require_admin() @handle_api_errors def get_alert_types():" in normalized


def test_the_page_doc_grants_no_roles_of_its_own():
	# Pins the premise the gates above rest on: Frappe's Page.is_permitted()
	# short-circuits to True when "roles" is empty, so page-level access is not a
	# second line of defence for any of these endpoints. If this list ever gains
	# roles, that is a deliberate change — not a licence to drop a decorator.
	page_doc = json.loads(PAGE_JSON.read_text())

	assert page_doc["roles"] == []


# --- GraphQL client ---


def _stub_missing_modules():
	# graphql_client imports frappe / jwt / requests at module level; none are
	# importable outside a bench environment. Stub whichever are missing so the
	# real module under test can be imported and exercised directly.
	for name in ("frappe", "jwt", "requests"):
		if name not in sys.modules:
			try:
				__import__(name)
			except ImportError:
				sys.modules[name] = types.ModuleType(name)


def test_client_send_user_alert_calls_user_notification_send():
	_stub_missing_modules()
	from admin_panel.api.graphql_client import GraphQLClient

	captured = {}
	client = GraphQLClient.__new__(GraphQLClient)

	def fake_execute(query, variables=None):
		captured["query"] = query
		captured["variables"] = variables
		return {"data": {"userNotificationSend": {"errors": [], "success": True}}}

	client.execute_query = fake_execute

	result = client.send_user_alert("jaceth2009", "Update Flash", "Please update your app.")

	assert result == {"errors": [], "success": True}
	assert "userNotificationSend" in captured["query"]
	assert captured["variables"] == {
		"input": {
			"username": "jaceth2009",
			"title": "Update Flash",
			"body": "Please update your app.",
		}
	}


def test_client_send_user_alert_returns_empty_dict_when_payload_missing():
	_stub_missing_modules()
	from admin_panel.api.graphql_client import GraphQLClient

	client = GraphQLClient.__new__(GraphQLClient)
	client.execute_query = lambda query, variables=None: {"data": {}}

	assert client.send_user_alert("jaceth2009", "t", "b") == {}


# --- rendered markup ---


def test_page_has_audience_selector_and_username_input():
	# The page harness drives elements by selector, so the markup that supplies
	# them is not covered there.
	page_js = read_text(PAGE_JS)

	assert 'id="alert-audience"' in page_js
	assert '<option value="all">' in page_js
	assert '<option value="user">' in page_js
	assert 'id="alert-username"' in page_js
	# Hidden until "Specific user" is picked.
	assert 'id="username-group" style="display: none;"' in page_js

	# Mirrors the endpoint's username<=50 bound, so the field cannot compose a
	# payload the server will only reject after the operator hits send.
	username_input = " ".join(page_js.split()).split('id="alert-username"', 1)[1].split(">", 1)[0]
	assert 'maxlength="50"' in username_input


def test_topic_options_escape_the_topic():
	# The rendered <option> template itself, which the harness observes only
	# through its output. A topic containing a double quote would otherwise
	# truncate the value attribute, so $tagSelect.val() would return a different
	# topic than the one displayed — and the broadcast would go out under it.
	page_js = read_text(PAGE_JS)

	assert "const safeTopic = frappe.utils.escape_html(topic);" in page_js
	assert '<option value="${safeTopic}">${safeTopic}</option>' in page_js
	assert '<option value="${topic}">' not in page_js

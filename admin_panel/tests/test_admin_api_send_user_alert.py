"""Behavioral tests for the single-user push path in admin_api.

``send_user_alert`` reaches one named customer's devices and writes a DIRECT
audit row naming them; ``get_user_alerts`` reads those rows back. Both are
exercised for real here — stubbed frappe, canned GraphQL client — so that a
swapped argument, a dropped audit insert, a gutted bounds check or a missing
role gate fails in this file instead of in production. Its broadcast sibling
``send_alert`` shares the input-guard shape, so the cases that keep the two
from drifting apart live here too. The source-level contract (decorator stack,
page markup, doctype schema) lives in
test_alert_users_user_target_contract.py.

admin_api pulls in frappe / jwt / requests (directly and via auth, common,
graphql_client, bridge_client, ibex_client); none are importable outside a
bench environment. Install functional stubs BEFORE importing the module under
test, mirroring test_admin_api_id_document_url.py.
"""

import sys
import types

import pytest


def _ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


frappe = _ensure_module("frappe")
if not hasattr(frappe, "whitelist"):
	frappe.whitelist = lambda *args, **kwargs: (lambda func: func)
if not hasattr(frappe, "session"):
	# "Administrator" short-circuits require_roles' role lookup.
	frappe.session = types.SimpleNamespace(user="Administrator")
if not hasattr(frappe, "get_roles"):
	frappe.get_roles = lambda user=None: ["System Manager"]
if not hasattr(frappe, "ValidationError"):
	frappe.ValidationError = type("ValidationError", (Exception,), {})
if not hasattr(frappe, "PermissionError"):
	frappe.PermissionError = type("PermissionError", (Exception,), {})
if not hasattr(frappe, "response"):
	frappe.response = {}
if not hasattr(frappe, "throw"):

	def _throw(message, exc=None):
		raise (exc or frappe.ValidationError)(message)

	frappe.throw = _throw

_requests = _ensure_module("requests")
if not hasattr(_requests, "exceptions"):
	_requests.exceptions = types.SimpleNamespace(RequestException=type("RequestException", (Exception,), {}))

_ensure_module("jwt")

from admin_panel.api import admin_api
from admin_panel.api.graphql_client import GraphQLError

USERNAME = "jaceth2009"
TITLE = "Update Flash"
MESSAGE = "Please update your app to the latest version."


class StubDoc:
	"""Stands in for the document frappe.get_doc returns.

	``insert_error`` makes the audit write fail the way the real doctype does
	when a mandatory field is blank or the DB is unhappy — the branch that
	decides whether a delivered push is reported as sent or as failed.
	"""

	def __init__(self, payload, insert_error=None):
		self.payload = payload
		self.insert_calls = []
		self.insert_error = insert_error

	def insert(self, **kwargs):
		self.insert_calls.append(kwargs)
		if self.insert_error is not None:
			raise self.insert_error
		return self


@pytest.fixture()
def api_env(monkeypatch):
	"""Stub the frappe surfaces the endpoints touch and record what they do."""
	response = {}
	errors = []
	docs = []
	commits = []
	queries = []
	columns = {"target_username": True}
	insert_error = {"exc": None}
	error_logs = []
	log_error_failure = {"exc": None}

	monkeypatch.setattr(frappe, "response", response, raising=False)
	monkeypatch.setattr(
		frappe,
		"logger",
		lambda: types.SimpleNamespace(error=errors.append, warning=lambda *a, **k: None),
		raising=False,
	)
	# A non-Administrator with an admin role, so require_admin's role lookup
	# actually runs instead of short-circuiting.
	monkeypatch.setattr(frappe, "session", types.SimpleNamespace(user="ops@getflash.io"), raising=False)
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["Flash Admin"], raising=False)

	def get_doc(payload):
		doc = StubDoc(payload, insert_error["exc"])
		docs.append(doc)
		return doc

	def get_all(doctype, **kwargs):
		queries.append({"doctype": doctype, **kwargs})
		return [{"title": "Scheduled maintenance"}]

	def log_error(message=None, title=None):
		# Frappe's own signature is (title, message) but it swaps the two when the
		# first argument is a multi-line traceback, which is how every call site in
		# this app passes them. Record both slots rather than guessing.
		error_logs.append({"message": message, "title": title})
		if log_error_failure["exc"] is not None:
			raise log_error_failure["exc"]

	monkeypatch.setattr(frappe, "get_doc", get_doc, raising=False)
	monkeypatch.setattr(frappe, "get_all", get_all, raising=False)
	monkeypatch.setattr(frappe, "log_error", log_error, raising=False)
	monkeypatch.setattr(
		frappe,
		"get_traceback",
		lambda *a, **k: 'Traceback (most recent call last):\n  ValidationError: "Title is mandatory"',
		raising=False,
	)
	monkeypatch.setattr(
		frappe,
		"db",
		types.SimpleNamespace(
			commit=lambda: commits.append(True),
			has_column=lambda doctype, column: columns.get(column, True),
		),
		raising=False,
	)
	monkeypatch.setattr(
		frappe,
		"utils",
		types.SimpleNamespace(now_datetime=lambda: "2026-08-19 12:00:00.000000"),
		raising=False,
	)

	env = types.SimpleNamespace(
		response=response,
		errors=errors,
		docs=docs,
		commits=commits,
		queries=queries,
		columns=columns,
		error_logs=error_logs,
	)
	# Arm the next audit insert to blow up, so the delivered-but-unaudited branch
	# is entered for real rather than asserted about via a source grep.
	env.fail_insert = lambda exc: insert_error.__setitem__("exc", exc)
	# Arm frappe.log_error itself to blow up — the case where the audit insert
	# failed because the DB is gone, so the durable record cannot be written
	# either. The endpoint still has to report the delivery.
	env.fail_log_error = lambda exc: log_error_failure.__setitem__("exc", exc)
	return env


def install_client(monkeypatch, result=None, raises=None):
	"""Replace GraphQLClient with a stub recording the exact call it received."""
	sent = []

	class StubClient:
		def send_user_alert(self, username, title, message):
			sent.append({"username": username, "title": title, "message": message})
			if raises is not None:
				raise raises
			return result if result is not None else {"errors": [], "success": True}

	monkeypatch.setattr(admin_api, "GraphQLClient", StubClient)
	return sent


def install_broadcast_client(monkeypatch, result=None):
	"""Replace GraphQLClient with a stub recording send_alert (broadcast) calls."""
	sent = []

	class StubClient:
		def send_alert(self, alert_type, title, message):
			sent.append({"alert_type": alert_type, "title": title, "message": message})
			return result if result is not None else {"errors": [], "success": True}

	monkeypatch.setattr(admin_api, "GraphQLClient", StubClient)
	return sent


def install_topics_client(monkeypatch, topics=("EMERGENCY", "MARKETING")):
	"""Replace GraphQLClient with a stub recording get_notification_topics calls."""
	fetched = []

	class StubClient:
		def get_notification_topics(self):
			fetched.append(True)
			return list(topics)

	monkeypatch.setattr(admin_api, "GraphQLClient", StubClient)
	return fetched


# --- happy path ---


def test_sends_the_exact_username_title_message_triple(monkeypatch, api_env):
	# The single most destructive silent edit here is swapping two of the three
	# arguments — every recipient would get the message body as their
	# notification title, and nothing else in the flow would complain.
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert sent == [{"username": USERNAME, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert USERNAME in result["message"]
	assert "http_status_code" not in api_env.response
	# Negative control for the audit-failure warning below: a clean send must not
	# tell the operator the audit row is missing.
	assert "warning" not in result


@pytest.mark.parametrize(
	"raw",
	[
		"  @jaceth2009  ",
		"@jaceth2009",
		"jaceth2009  ",
		"@ jaceth2009",  # pasted out of a chat window, with the space kept
		"  @  jaceth2009  ",
	],
)
def test_the_username_that_is_validated_is_the_username_that_is_sent(monkeypatch, api_env, raw):
	# is_flash_username_candidate strips internally before matching, so a value
	# normalised to " jaceth2009" passes the shape guard and is then shipped to
	# flash with the leading space — which flash refuses as INVALID_INPUT, so the
	# operator gets an opaque 500 instead of the crisp error the guard exists to
	# produce. Whatever survives normalisation must be exactly what goes out, and
	# exactly what the audit row names.
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(raw, f"  {TITLE}  ", f"  {MESSAGE}  ")

	assert sent == [{"username": USERNAME, "title": TITLE, "message": MESSAGE}]
	assert api_env.docs[0].payload["target_username"] == USERNAME
	assert result["success"] is True


def test_writes_a_direct_audit_row_and_commits_it(monkeypatch, api_env):
	# Without this row there is no record of which customer support messaged
	# privately, or what was said.
	install_client(monkeypatch)

	admin_api.send_user_alert(f"@{USERNAME}", TITLE, MESSAGE)

	assert len(api_env.docs) == 1
	payload = api_env.docs[0].payload
	assert payload["doctype"] == "User Alerts"
	assert payload["tag"] == "DIRECT"
	assert payload["target_username"] == USERNAME
	assert payload["title"] == TITLE
	assert payload["message"] == MESSAGE
	assert payload["sent_by"] == "ops@getflash.io"
	assert payload["sent_on"] == "2026-08-19 12:00:00.000000"
	# The doctype is System Manager-only; the insert has to bypass permissions
	# for a Flash Admin send to be logged at all.
	assert api_env.docs[0].insert_calls == [{"ignore_permissions": True}]
	assert api_env.commits == [True]


def test_boundary_lengths_are_accepted(monkeypatch, api_env):
	# Negative control for the bounds tests below: at the limit the send must
	# still go through, so "rejects everything" cannot pass the suite.
	sent = install_client(monkeypatch)

	admin_api.send_user_alert("a" * 50, "t" * 140, "m" * 1000)

	assert sent == [{"username": "a" * 50, "title": "t" * 140, "message": "m" * 1000}]
	assert "http_status_code" not in api_env.response


# --- input bounds ---


@pytest.mark.parametrize(
	("username", "title", "message"),
	[
		("", TITLE, MESSAGE),
		(USERNAME, "", MESSAGE),
		(USERNAME, TITLE, ""),
		# None is the whole reason the *pre*-strip guard cannot be deleted as a
		# duplicate of its post-strip twin: str(None) is "None", a non-empty
		# 4-character string that clears emptiness, clears the bounds check, and
		# — for title and message — is never seen again. Without the pre-strip
		# guard, send_user_alert(USERNAME, None, MESSAGE) delivers a personal
		# push titled "None" to a real customer and writes the audit row to match.
		(None, TITLE, MESSAGE),
		(USERNAME, None, MESSAGE),
		(USERNAME, TITLE, None),
	],
)
def test_missing_arguments_are_rejected_before_any_send(monkeypatch, api_env, username, title, message):
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(username, title, message)

	assert result["success"] is False
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []


@pytest.mark.parametrize(
	("username", "title", "message"),
	[
		("@", TITLE, MESSAGE),  # blank once the @ is stripped
		("   ", TITLE, MESSAGE),
		("@   ", TITLE, MESSAGE),
		(USERNAME, "   ", MESSAGE),
		(USERNAME, TITLE, "   "),
		(USERNAME, "\t\n ", MESSAGE),
		("   ", "   ", "   "),
	],
)
def test_whitespace_only_payloads_never_reach_flash(monkeypatch, api_env, username, title, message):
	# Whitespace is truthy, so these clear the pre-strip guard and arrive at the
	# bounds check as empty strings — which only tests upper limits. Left
	# unchecked, a blank title delivers an unrecallable empty push to a real
	# customer and then fails the doctype's reqd insert, which the audit
	# try/except reports back as a *successful* send with no row written.
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(username, title, message)

	assert result == {"success": False, "error": "Username, title, and message are required"}
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []


@pytest.mark.parametrize(
	("username", "title", "message"),
	[
		("a" * 51, TITLE, MESSAGE),
		(USERNAME, "t" * 141, MESSAGE),
		(USERNAME, TITLE, "m" * 1001),
	],
)
def test_out_of_bounds_payloads_never_reach_flash(monkeypatch, api_env, username, title, message):
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(username, title, message)

	assert result["success"] is False
	assert "length limits" in result["error"]
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []


@pytest.mark.parametrize(
	"username",
	[
		"+18765550100",  # phone number
		"ops@getflash.io",  # email
		"7f9c1f2a-4b1e-4c9d-9d0e-2b6a1c3d4e5f",  # account uuid
		"ab",  # under the Username scalar's 3-character minimum
		"bc1qar0srrr7xfkvy5l643lydnw9re59gtzz",  # bitcoin address
		"@ ali ce",  # pasted display name — an interior space is not a username
		"jaceth 2009",
	],
)
def test_non_username_identifiers_are_rejected_locally(monkeypatch, api_env, username):
	# Screened by is_flash_username_candidate so the operator is told the value
	# is not a username, rather than burning a round trip to be told flash has
	# no such account.
	sent = install_client(monkeypatch)

	result = admin_api.send_user_alert(username, TITLE, MESSAGE)

	assert result == {"success": False, "error": "Not a Flash username"}
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []


# --- upstream failures ---


def test_upstream_errors_are_surfaced_as_400_and_not_logged_as_sent(monkeypatch, api_env):
	install_client(monkeypatch, {"errors": [{"message": "Invalid username"}], "success": False})

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert result == {"success": False, "errors": ["Invalid username"]}
	assert api_env.response["http_status_code"] == 400
	assert api_env.docs == []
	assert len(api_env.errors) == 1


@pytest.mark.parametrize("payload", [{"success": False}, {}, {"success": None}])
def test_a_falsy_success_is_a_500_with_no_audit_row(monkeypatch, api_env, payload):
	install_client(monkeypatch, payload)

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert result == {"success": False, "error": "Failed to send notification"}
	assert api_env.response["http_status_code"] == 500
	assert api_env.docs == []


def test_a_transport_failure_is_caught_by_handle_api_errors(monkeypatch, api_env):
	install_client(monkeypatch, raises=GraphQLError("boom"))

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert result["success"] is False
	assert api_env.response["http_status_code"] == 500
	assert api_env.docs == []


# --- delivered, but the audit row did not land ---


def test_a_delivered_push_with_a_failed_audit_row_is_still_reported_as_sent(monkeypatch, api_env):
	# The push cannot be recalled once flash has accepted it. Reporting the
	# audit-write failure as a failed send — which is what handle_api_errors does
	# to an unguarded insert — makes the page keep the form intact, the operator
	# clicks Send again, and the customer gets the same personal push twice with
	# no row recorded for either.
	sent = install_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert sent == [{"username": USERNAME, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert "do not resend" in result["warning"]
	assert USERNAME in result["message"]
	# Not a 4xx and not a 5xx: handle_api_errors must never see this.
	assert "http_status_code" not in api_env.response
	# The insert was genuinely attempted and genuinely failed — no commit.
	assert len(api_env.docs) == 1
	assert api_env.docs[0].insert_calls == [{"ignore_permissions": True}]
	assert api_env.commits == []


def test_a_failed_audit_row_is_logged_with_the_delivered_content(monkeypatch, api_env):
	# The response warning is the operator's signal; the log line is the only
	# remaining record of who received what, so it has to carry both.
	install_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))

	admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	logged = "\n".join(api_env.errors)
	assert "was DELIVERED" in logged
	assert USERNAME in logged
	assert TITLE in logged
	assert "Title is mandatory" in logged


def test_a_failed_audit_row_leaves_a_durable_error_log_row(monkeypatch, api_env):
	# frappe.logger() writes to sites/<site>/logs/*.log *inside the pod*, and this
	# app ships as a container on a chart whose pods roll on every deploy — so the
	# log line above, "the only remaining record of who received what", is gone at
	# the next release. An Error Log row is in the database and survives it.
	install_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))

	admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert len(api_env.error_logs) == 1
	recorded = " ".join(str(value) for value in api_env.error_logs[0].values())
	assert USERNAME in recorded
	assert TITLE in recorded
	assert MESSAGE in recorded
	assert "audit row failed" in recorded


def test_a_failing_error_log_write_still_reports_the_push_as_delivered(monkeypatch, api_env):
	# The audit insert can fail because the database is gone, in which case the
	# Error Log write fails too. Unguarded, that exception is raised *inside* the
	# except block, escapes to handle_api_errors as a 500, and reintroduces the
	# exact double-push this branch exists to prevent — the best-effort durable
	# record must never be able to cause the bug it documents.
	sent = install_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))
	api_env.fail_log_error(RuntimeError("MySQL server has gone away"))

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert sent == [{"username": USERNAME, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert "do not resend" in result["warning"]
	assert "http_status_code" not in api_env.response


# --- pre-migrate window ---


def test_a_send_is_refused_while_the_audit_column_is_missing(monkeypatch, api_env):
	# frappe builds the INSERT from meta.get_valid_columns(), so before the
	# migrate lands the target_username key is dropped silently and the DIRECT
	# row would record a private message to one customer as a broadcast to every
	# Flash user — permanently, since the row itself lost the target. A push that
	# cannot be audited must not go out at all.
	sent = install_client(monkeypatch)
	api_env.columns["target_username"] = False

	result = admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert result["success"] is False
	assert "mid-migration" in result["error"]
	assert api_env.response["http_status_code"] == 503
	assert sent == []
	assert api_env.docs == []
	assert api_env.commits == []


def test_the_column_check_runs_after_the_cheap_input_guards(monkeypatch, api_env):
	# A bad identifier should still be reported as a bad identifier mid-migrate,
	# not masked behind a retry-later 503 the operator cannot act on.
	install_client(monkeypatch)
	api_env.columns["target_username"] = False

	result = admin_api.send_user_alert("ops@getflash.io", TITLE, MESSAGE)

	assert result == {"success": False, "error": "Not a Flash username"}
	assert api_env.response["http_status_code"] == 400


# --- the broadcast sibling shares the input guards ---


ALERT_TYPE = "EMERGENCY"


def test_send_alert_broadcasts_a_well_formed_payload(monkeypatch, api_env):
	# Negative control for the rejection cases below: "refuse everything" must not
	# pass this file.
	sent = install_broadcast_client(monkeypatch)

	result = admin_api.send_alert(f"  {ALERT_TYPE}  ", f"  {TITLE}  ", f"  {MESSAGE}  ")

	assert sent == [{"alert_type": ALERT_TYPE, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert "http_status_code" not in api_env.response
	assert api_env.docs[0].payload["tag"] == ALERT_TYPE
	assert api_env.commits == [True]
	# Negative control for the audit-failure warning below: a clean broadcast must
	# not tell the operator the audit row is missing.
	assert "warning" not in result
	assert api_env.error_logs == []


@pytest.mark.parametrize(
	("alert_type", "title", "message"),
	[
		("", TITLE, MESSAGE),
		(ALERT_TYPE, "", MESSAGE),
		(ALERT_TYPE, TITLE, ""),
		# The None cases are what makes the *pre*-strip guard load-bearing rather
		# than a duplicate of its post-strip twin: str(None) is "None", which
		# clears emptiness and clears the bounds check. Delete the pre-strip guard
		# and send_alert(None, TITLE, MESSAGE) broadcasts under topic "None", while
		# send_alert(ALERT_TYPE, None, MESSAGE) pushes a notification titled "None"
		# to every Flash user.
		(None, TITLE, MESSAGE),
		(ALERT_TYPE, None, MESSAGE),
		(ALERT_TYPE, TITLE, None),
	],
)
def test_send_alert_rejects_missing_arguments(monkeypatch, api_env, alert_type, title, message):
	sent = install_broadcast_client(monkeypatch)

	result = admin_api.send_alert(alert_type, title, message)

	assert result == {"success": False, "error": "Alert type, title, and message are required"}
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []
	assert api_env.commits == []


@pytest.mark.parametrize(
	("alert_type", "title", "message"),
	[
		("   ", TITLE, MESSAGE),
		(ALERT_TYPE, "   ", MESSAGE),
		(ALERT_TYPE, TITLE, "   "),
		(ALERT_TYPE, "\t\n ", MESSAGE),
		("   ", "   ", "   "),
	],
)
def test_send_alert_rejects_whitespace_only_arguments(monkeypatch, api_env, alert_type, title, message):
	# Same defect as its single-user sibling, with a wider blast radius: a
	# whitespace-only title broadcasts a blank push to *every* Flash user and only
	# then fails the doctype's reqd insert — which the audit try/except now reports
	# as a *successful* send, leaving a broadcast to every Flash user permanently
	# unauditable. Leaving one endpoint fixed and the other broken is how this
	# regresses.
	sent = install_broadcast_client(monkeypatch)

	result = admin_api.send_alert(alert_type, title, message)

	assert result == {"success": False, "error": "Alert type, title, and message are required"}
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []
	assert api_env.commits == []


@pytest.mark.parametrize(
	("alert_type", "title", "message"),
	[
		("e" * 65, TITLE, MESSAGE),
		(ALERT_TYPE, "t" * 141, MESSAGE),
		(ALERT_TYPE, TITLE, "m" * 1001),
	],
)
def test_send_alert_rejects_out_of_bounds_arguments(monkeypatch, api_env, alert_type, title, message):
	sent = install_broadcast_client(monkeypatch)

	result = admin_api.send_alert(alert_type, title, message)

	assert result["success"] is False
	assert "length limits" in result["error"]
	assert api_env.response["http_status_code"] == 400
	assert sent == []
	assert api_env.docs == []


def test_a_delivered_broadcast_with_a_failed_audit_row_is_still_reported_as_sent(monkeypatch, api_env):
	# The half of the symmetry the single-user fix stopped short of. This PR's own
	# DDL adds target_username to `tabUser Alerts`, and the migrate Job carries no
	# helm hook, so a serving pod's INSERT can land inside the ALTER's metadata
	# lock and time out. By then the push has fanned out to every Flash user and
	# cannot be recalled — reporting it as a failed send makes the page keep the
	# form intact, the operator clicks Send again, and every Flash user gets the
	# same push twice.
	sent = install_broadcast_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))

	result = admin_api.send_alert(ALERT_TYPE, TITLE, MESSAGE)

	assert sent == [{"alert_type": ALERT_TYPE, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert TITLE in result["message"]
	assert "do not resend" in result["warning"]
	# Not a 4xx and not a 5xx: handle_api_errors must never see this.
	assert "http_status_code" not in api_env.response
	# The insert was genuinely attempted and genuinely failed — no commit.
	assert len(api_env.docs) == 1
	assert api_env.docs[0].insert_calls == [{"ignore_permissions": True}]
	assert api_env.commits == []


def test_a_failed_broadcast_audit_row_is_recorded_in_the_log_and_durably(monkeypatch, api_env):
	# Same two records as the single-user path: the pod log for whoever is
	# tailing it now, and an Error Log row for whoever asks after the next deploy
	# why a broadcast has no audit entry.
	install_broadcast_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))

	admin_api.send_alert(ALERT_TYPE, TITLE, MESSAGE)

	logged = "\n".join(api_env.errors)
	assert "was DELIVERED" in logged
	assert ALERT_TYPE in logged
	assert TITLE in logged
	assert "Title is mandatory" in logged

	assert len(api_env.error_logs) == 1
	recorded = " ".join(str(value) for value in api_env.error_logs[0].values())
	assert ALERT_TYPE in recorded
	assert TITLE in recorded
	assert MESSAGE in recorded
	assert "audit row failed" in recorded


def test_a_failing_error_log_write_still_reports_the_broadcast_as_delivered(monkeypatch, api_env):
	sent = install_broadcast_client(monkeypatch)
	api_env.fail_insert(frappe.ValidationError("Title is mandatory"))
	api_env.fail_log_error(RuntimeError("MySQL server has gone away"))

	result = admin_api.send_alert(ALERT_TYPE, TITLE, MESSAGE)

	assert sent == [{"alert_type": ALERT_TYPE, "title": TITLE, "message": MESSAGE}]
	assert result["success"] is True
	assert "do not resend" in result["warning"]
	assert "http_status_code" not in api_env.response


# --- role gate ---


def test_send_user_alert_is_refused_without_an_admin_role(monkeypatch, api_env):
	sent = install_client(monkeypatch)
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["Employee"], raising=False)

	with pytest.raises(frappe.PermissionError):
		admin_api.send_user_alert(USERNAME, TITLE, MESSAGE)

	assert sent == []


def test_get_alert_types_is_refused_without_an_admin_role(monkeypatch, api_env):
	# The Page doc carries "roles": [], and Frappe's Page.is_permitted() returns
	# True when the list is empty — so /app/alert-users opens for every logged-in
	# user. Ungated, this endpoint let an Employee or Website Manager login make
	# the panel mint an admin JWT and run Flash's notificationTopics admin query
	# on their behalf.
	fetched = install_topics_client(monkeypatch)
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["Website Manager"], raising=False)

	with pytest.raises(frappe.PermissionError):
		admin_api.get_alert_types()

	assert fetched == []


def test_get_alert_types_still_serves_an_admin(monkeypatch, api_env):
	# Negative control for the gate above: "always refuse" must not pass.
	fetched = install_topics_client(monkeypatch, ["EMERGENCY", "MARKETING"])

	result = admin_api.get_alert_types()

	assert result == {"topics": ["EMERGENCY", "MARKETING"]}
	assert fetched == [True]


# --- history read ---


def test_get_user_alerts_is_refused_without_an_admin_role(monkeypatch, api_env):
	# frappe.get_all reads with ignore_permissions, so the doctype's
	# System Manager-only read permission is not a second line of defence:
	# without this gate any authenticated Frappe user could read every DIRECT
	# row — which customer was messaged privately, and what was said.
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["Website Manager"], raising=False)

	with pytest.raises(frappe.PermissionError):
		admin_api.get_user_alerts(limit=1000)

	assert api_env.queries == []


def test_get_user_alerts_selects_the_target_username(api_env):
	result = admin_api.get_user_alerts(limit=5)

	assert result["logs"] == [{"title": "Scheduled maintenance"}]
	assert result["target_username_available"] is True
	assert api_env.queries[0]["doctype"] == "User Alerts"
	assert "target_username" in api_env.queries[0]["fields"]
	assert api_env.queries[0]["limit_page_length"] == 5


def test_get_user_alerts_survives_a_pre_migrate_table(api_env):
	# The chart's migrate Job carries no helm hook, so a new pod can serve this
	# before the column exists. Dropping the field beats 500ing the whole
	# history panel, broadcast rows included.
	api_env.columns["target_username"] = False

	result = admin_api.get_user_alerts()

	assert result["logs"] == [{"title": "Scheduled maintenance"}]
	assert "target_username" not in api_env.queries[0]["fields"]
	for expected in ("title", "message", "tag", "sent_by", "sent_on"):
		assert expected in api_env.queries[0]["fields"]


def test_get_user_alerts_reports_the_dropped_column_to_the_page(api_env):
	# Without this flag the drop is invisible: every row arrives with no target
	# and the history panel labels each one "to all users", which is a lie about
	# who received a private message.
	api_env.columns["target_username"] = False

	result = admin_api.get_user_alerts()

	assert result["target_username_available"] is False

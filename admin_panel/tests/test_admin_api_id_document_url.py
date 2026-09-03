"""Behavioral tests for the get_id_document_url endpoint (admin_api).

Pins the failure contract around GraphQLClient.get_id_document_read_url's
``or {}`` fallback: a null / readUrl-less idDocumentReadUrl payload must NOT
come back as ``{"success": True, "url": None}`` — the document viewer would
"succeed" with nothing to open. It must be a loud ``{"success": False}`` with
a 502, mirroring how send_alert's caller surfaces upstream failures.
"""

import sys
import types

import pytest

# admin_api pulls in frappe / jwt / requests (directly and via auth, common,
# graphql_client, bridge_client, ibex_client); none are importable outside a
# bench environment. Install functional stubs BEFORE importing the module
# under test: frappe needs working decorator / session / response / logger
# surfaces so the real endpoint code runs, and requests needs an exceptions
# hierarchy for common.handle_api_errors' except clauses.


def _ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


frappe = _ensure_module("frappe")
if not hasattr(frappe, "whitelist"):
	frappe.whitelist = lambda *args, **kwargs: lambda func: func
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

_requests = _ensure_module("requests")
if not hasattr(_requests, "exceptions"):
	_requests.exceptions = types.SimpleNamespace(RequestException=type("RequestException", (Exception,), {}))

_ensure_module("jwt")

from admin_panel.api import admin_api


@pytest.fixture()
def api_env(monkeypatch):
	"""Fresh frappe.response + captured logger errors + ledger events per test.

	``owner`` is what the Account Upgrade Request lookup by id_document
	returns (None = no request owns the key, so the ledger references the
	key itself).
	"""
	response = {}
	errors = []
	events = []
	owner = {"name": None}
	monkeypatch.setattr(frappe, "response", response, raising=False)
	monkeypatch.setattr(
		frappe,
		"logger",
		lambda: types.SimpleNamespace(error=errors.append, warning=lambda *a, **k: None),
		raising=False,
	)
	monkeypatch.setattr(
		frappe,
		"db",
		types.SimpleNamespace(get_value=lambda *args, **kwargs: owner["name"]),
		raising=False,
	)
	monkeypatch.setattr(admin_api, "record_event", lambda *args: events.append(args))
	return types.SimpleNamespace(response=response, errors=errors, events=events, owner=owner)


def install_client(monkeypatch, result):
	"""Replace GraphQLClient with a stub returning a canned payload."""

	class StubClient:
		def get_id_document_read_url(self, file_key):
			return result

	monkeypatch.setattr(admin_api, "GraphQLClient", StubClient)


def test_missing_read_url_fails_loudly(monkeypatch, api_env):
	# A null idDocumentReadUrl payload reaches the endpoint as {} (the
	# client's `or {}` fallback). That must be a 502 failure, not a
	# "successful" response with url=None.
	install_client(monkeypatch, {})
	result = admin_api.get_id_document_url("kyc/passport.jpg")
	assert result == {"success": False, "error": "No read URL returned"}
	assert api_env.response["http_status_code"] == 502
	assert len(api_env.errors) == 1
	assert "kyc/passport.jpg" in api_env.errors[0]
	# Nothing was served, so nothing was viewed.
	assert api_env.events == []


def test_null_read_url_field_fails_loudly(monkeypatch, api_env):
	install_client(monkeypatch, {"readUrl": None})
	result = admin_api.get_id_document_url("kyc/passport.jpg")
	assert result["success"] is False
	assert api_env.response["http_status_code"] == 502


def test_read_url_present_succeeds(monkeypatch, api_env):
	install_client(monkeypatch, {"readUrl": "https://spaces.example/signed"})
	result = admin_api.get_id_document_url("kyc/passport.jpg")
	assert result == {"success": True, "url": "https://spaces.example/signed"}
	assert "http_status_code" not in api_env.response
	# Every successful mint is an evidence view on the compliance ledger,
	# referenced by the key itself when no upgrade request owns it.
	assert api_env.events == [
		("evidence_viewed", "Account Upgrade Request", "kyc/passport.jpg", {"file_key": "kyc/passport.jpg"})
	]


def test_evidence_view_references_the_owning_upgrade_request(monkeypatch, api_env):
	install_client(monkeypatch, {"readUrl": "https://spaces.example/signed"})
	api_env.owner["name"] = "AUR-0007"
	admin_api.get_id_document_url("kyc/passport.jpg")
	assert api_env.events == [
		("evidence_viewed", "Account Upgrade Request", "AUR-0007", {"file_key": "kyc/passport.jpg"})
	]


def test_a_view_the_ledger_cannot_record_is_not_served(monkeypatch, api_env):
	"""Evidence access must be auditable; a ledger failure fails the mint."""
	install_client(monkeypatch, {"readUrl": "https://spaces.example/signed"})

	def broken(*args):
		raise RuntimeError("ledger down")

	monkeypatch.setattr(admin_api, "record_event", broken)
	result = admin_api.get_id_document_url("kyc/passport.jpg")
	assert result["success"] is False
	assert api_env.response["http_status_code"] == 500


def test_payload_errors_are_surfaced_as_400(monkeypatch, api_env):
	install_client(monkeypatch, {"errors": [{"message": "denied"}], "readUrl": None})
	result = admin_api.get_id_document_url("kyc/passport.jpg")
	assert result == {"success": False, "errors": ["denied"]}
	assert api_env.response["http_status_code"] == 400
	assert api_env.events == []


def test_missing_file_key_is_400(monkeypatch, api_env):
	install_client(monkeypatch, {"readUrl": "https://spaces.example/signed"})
	result = admin_api.get_id_document_url("")
	assert result["success"] is False
	assert api_env.response["http_status_code"] == 400

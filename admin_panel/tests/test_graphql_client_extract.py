"""Behavioral tests for GraphQLClient.execute_and_extract's typed extraction.

The method's return type is parameterized by ``result_type`` (issue #16 —
previously ``-> Any``). These pin the runtime contract behind that type:
extraction by key, strict vs lookup (allow_not_found) error semantics,
partial-response tolerance, and the isinstance guard that turns an API shape
drift into a GraphQLError instead of a mistyped value leaking into callers.
"""

import sys
import types
from pathlib import Path

import pytest

# graphql_client imports frappe / jwt / requests at module level; none are
# importable outside a bench environment. Stub whichever are missing so the
# real module under test can be imported and exercised directly.
for _name in ("frappe", "jwt", "requests"):
	if _name not in sys.modules:
		try:
			__import__(_name)
		except ImportError:
			sys.modules[_name] = types.ModuleType(_name)

from admin_panel.api import graphql_client as gql
from admin_panel.api.graphql_client import GraphQLClient, GraphQLError

ACCOUNT = {"id": "acc-1", "username": "alice", "level": "TWO"}


def make_client(response):
	"""GraphQLClient with a canned execute_query — no config, no network."""
	client = GraphQLClient.__new__(GraphQLClient)
	client.execute_query = lambda query, variables=None: response
	return client


def install_logger(monkeypatch):
	"""Capture frappe.logger().warning calls made by the partial path."""
	records = []
	monkeypatch.setattr(
		gql.frappe,
		"logger",
		lambda: types.SimpleNamespace(warning=records.append),
		raising=False,
	)
	return records


# --- strict (all-or-nothing) semantics ---


def test_extracts_payload_at_data_key():
	client = make_client({"data": {"accountUpdateLevel": ACCOUNT}})
	result = client.execute_and_extract("q", {}, "accountUpdateLevel", result_type=dict)
	assert result == ACCOUNT


def test_strict_missing_key_returns_none():
	client = make_client({"data": {"somethingElse": ACCOUNT}})
	assert client.execute_and_extract("q", {}, "accountUpdateLevel", result_type=dict) is None


def test_strict_null_data_returns_none():
	# {"data": null} with no errors array must return None like the lookup
	# path does, not blow up with AttributeError on None.get.
	client = make_client({"data": None})
	assert client.execute_and_extract("q", {}, "accountUpdateLevel", result_type=dict) is None


def test_strict_graphql_error_raises():
	client = make_client({"errors": [{"code": "FORBIDDEN", "message": "nope"}]})
	with pytest.raises(GraphQLError):
		client.execute_and_extract("q", {}, "accountUpdateLevel", result_type=dict)


def test_strict_not_found_still_raises_without_flag():
	# NOT_FOUND is only tolerated under LOOKUP semantics; mutations and
	# strict reads must keep all-or-nothing behavior.
	client = make_client({"errors": [{"code": "NOT_FOUND", "message": "gone"}]})
	with pytest.raises(GraphQLError):
		client.execute_and_extract("q", {}, "accountUpdateLevel", result_type=dict)


# --- the isinstance guard behind the parameterized return type ---


def test_shape_drift_raises_graphql_error():
	# API starts returning a list where the caller declared dict: that must
	# surface as a clear error, not a mistyped value flowing downstream.
	client = make_client({"data": {"accountDetailsByAccountId": [ACCOUNT]}})
	with pytest.raises(GraphQLError) as exc:
		client.execute_and_extract("q", {}, "accountDetailsByAccountId", result_type=dict)
	assert "accountDetailsByAccountId" in str(exc.value)
	assert "list" in str(exc.value)
	assert "dict" in str(exc.value)


def test_result_type_list_accepts_list_payload():
	client = make_client({"data": {"accounts": [ACCOUNT]}})
	result = client.execute_and_extract("q", {}, "accounts", result_type=list)
	assert result == [ACCOUNT]


def test_lookup_shape_drift_also_raises(monkeypatch):
	install_logger(monkeypatch)
	client = make_client({"data": {"accountDetailsByUserPhone": "not-a-dict"}})
	with pytest.raises(GraphQLError):
		client.execute_and_extract(
			"q", {}, "accountDetailsByUserPhone", allow_not_found=True, result_type=dict
		)


# --- lookup (allow_not_found) semantics ---


@pytest.mark.parametrize(
	"error",
	[
		{"code": "NOT_FOUND", "message": "no such account"},
		{"code": "INVALID_INPUT", "message": "bad id"},
		{"code": "UNEXPECTED_CLIENT_ERROR", "message": "InvalidAccountIdError: nope"},
	],
)
def test_lookup_not_found_shapes_return_none(error):
	client = make_client({"data": {"accountDetailsByAccountId": None}, "errors": [error]})
	result = client.execute_and_extract(
		"q", {}, "accountDetailsByAccountId", allow_not_found=True, result_type=dict
	)
	assert result is None


def test_lookup_real_error_still_raises():
	client = make_client({"errors": [{"code": "FORBIDDEN", "message": "nope"}]})
	with pytest.raises(GraphQLError):
		client.execute_and_extract(
			"q", {}, "accountDetailsByAccountId", allow_not_found=True, result_type=dict
		)


def test_lookup_partial_response_returns_data_and_logs(monkeypatch):
	# A resolved node with field-level errors (e.g. Kratos 404 on owner.email)
	# must be returned with nulls, not raised — the admin panel exists to
	# inspect broken accounts.
	records = install_logger(monkeypatch)
	client = make_client(
		{
			"data": {"accountDetailsByUserPhone": ACCOUNT},
			"errors": [{"code": "UNEXPECTED_CLIENT_ERROR", "message": "owner.email failed"}],
		}
	)
	result = client.execute_and_extract(
		"q", {}, "accountDetailsByUserPhone", allow_not_found=True, result_type=dict
	)
	assert result == ACCOUNT
	assert len(records) == 1
	assert "accountDetailsByUserPhone" in records[0]


# --- typing flows through the public helpers ---


def test_get_account_by_id_returns_account_dict():
	client = make_client({"data": {"accountDetailsByAccountId": ACCOUNT}})
	assert client.get_account_by_id("acc-1") == ACCOUNT


def test_get_notification_topics_returns_topics_list():
	client = make_client({"data": {"notificationTopics": ["Circles", "Payments"]}})
	assert client.get_notification_topics() == ["Circles", "Payments"]


def test_get_notification_topics_null_data_returns_empty_list():
	client = make_client({"data": {"notificationTopics": None}})
	assert client.get_notification_topics() == []


def test_get_notification_topics_shape_drift_raises():
	# The typed-extraction guard now covers this last helper too: a dict
	# where a list is expected must raise, not leak into the caller.
	client = make_client({"data": {"notificationTopics": {"oops": True}}})
	with pytest.raises(GraphQLError):
		client.get_notification_topics()


def test_get_notification_topics_error_raises():
	client = make_client({"errors": [{"code": "FORBIDDEN", "message": "nope"}]})
	with pytest.raises(GraphQLError):
		client.get_notification_topics()


def test_update_account_status_null_data_returns_empty_dict():
	client = make_client({"data": {"accountUpdateStatus": None}})
	assert client.update_account_status("uid-1", "ACTIVE") == {}


def test_return_type_is_parameterized_not_any():
	# The point of issue #16: no Any left in the client's typing surface.
	source = (Path(__file__).parents[1] / "api" / "graphql_client.py").read_text()
	assert "result_type: type[T]" in source
	assert "-> T | None" in source
	assert "from typing import Any" not in source
	assert "-> Any" not in source


# --- the JWT the client actually mints ---
#
# _create_jwt_token is the security boundary of the support lookup relay
# (PR #73): jwt_roles lets an endpoint mint fixed upstream roles instead of the
# session user's frappe roles, because the bridge's service user deliberately
# holds no upstream-recognized role. Source-level regex proves the characters
# exist; these prove the token carries them. If it stopped carrying them the
# upstream shield would return AuthorizationError and every lookup would 500.


def make_minting_client(monkeypatch, jwt_roles, user="ops@getflash.io", frappe_roles=("Flash Admin",)):
	"""A client wired to capture the payload handed to jwt.encode."""
	captured = {}
	role_lookups = []

	def fake_encode(payload, key, algorithm=None):
		captured["payload"] = payload
		captured["key"] = key
		captured["algorithm"] = algorithm
		return "signed-token"

	def fake_get_roles(u=None):
		role_lookups.append(u)
		return list(frappe_roles)

	monkeypatch.setattr(gql.jwt, "encode", fake_encode, raising=False)
	monkeypatch.setattr(gql.frappe, "session", types.SimpleNamespace(user=user), raising=False)
	monkeypatch.setattr(gql.frappe, "get_roles", fake_get_roles, raising=False)

	client = GraphQLClient.__new__(GraphQLClient)
	client.api_key = "test-api-key"
	client._jwt_roles = list(jwt_roles) if jwt_roles else None
	return client, captured, role_lookups


def test_fixed_jwt_roles_are_what_the_token_carries(monkeypatch):
	client, captured, role_lookups = make_minting_client(monkeypatch, ("Accounts Manager",))

	token = client._create_jwt_token()

	assert token == "signed-token"
	assert captured["payload"]["roles"] == ["Accounts Manager"]
	# The session user is still stamped for upstream audit.
	assert captured["payload"]["userId"] == "ops@getflash.io"
	assert captured["payload"]["iss"] == "frappe-admin-panel"
	assert captured["key"] == "test-api-key"
	assert captured["algorithm"] == "HS256"
	# Fixed roles replace the frappe lookup — they never merge with it, or the
	# service user's real roles would ride along upstream.
	assert role_lookups == []


def test_default_jwt_roles_fall_back_to_the_session_users_frappe_roles(monkeypatch):
	# The path all ~15 pre-existing endpoints take; jwt_roles must not disturb it.
	client, captured, role_lookups = make_minting_client(
		monkeypatch, None, user="ops@getflash.io", frappe_roles=("Flash Admin", "Accounts Manager")
	)

	client._create_jwt_token()

	assert captured["payload"]["roles"] == ["Flash Admin", "Accounts Manager"]
	assert captured["payload"]["userId"] == "ops@getflash.io"
	assert role_lookups == ["ops@getflash.io"]


def test_no_session_user_mints_no_roles(monkeypatch):
	client, captured, role_lookups = make_minting_client(monkeypatch, None, user=None)

	client._create_jwt_token()

	assert captured["payload"]["roles"] == []
	assert role_lookups == []


def test_jwt_token_expires_within_the_hour(monkeypatch):
	client, captured, _ = make_minting_client(monkeypatch, ("Accounts Manager",))
	client._create_jwt_token()
	payload = captured["payload"]
	assert payload["exp"] - payload["iat"] == 3600


def test_constructor_normalizes_jwt_roles_and_defaults_to_none(monkeypatch):
	monkeypatch.setattr(
		gql.frappe,
		"conf",
		{"flash_admin_api_url": "https://api.example/graphql", "admin_api_key": "k"},
		raising=False,
	)
	# The pooled requests.Session the constructor grabs — no network here.
	monkeypatch.setattr(gql, "_get_session", lambda: object())

	assert GraphQLClient(jwt_roles=("Accounts Manager",))._jwt_roles == ["Accounts Manager"]
	assert GraphQLClient()._jwt_roles is None
	# An empty tuple must mean "no override", not "mint an empty role list".
	assert GraphQLClient(jwt_roles=())._jwt_roles is None

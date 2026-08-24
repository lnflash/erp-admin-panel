"""Behavioral tests for the support contact lookup relay endpoint.

``get_support_contact_by_npub`` is the one endpoint in this app whose caller
sits outside the cluster (the nostr-dm-bridge on the support droplet) and whose
output is PII — phone number and email address, keyed by a public identifier.
Everything that keeps that safe is exercised for real here, with a stubbed
frappe and a fake GraphQL client, so that a flipped ``allow_not_found``, a
misnamed variable key, a deleted not-found branch, a dropped rate limit, a
missing audit line or an upstream error array leaking out of the cluster fails
in this file instead of on the droplet.

The source-level invariants behavior cannot reach — the upstream query's field
set, the Role provisioning in setup.py, the repo-wide confinement of
``jwt_roles`` — live in test_support_lookup_contract.py. The JWT the client
actually mints is pinned in test_graphql_client_extract.py.

support_lookup pulls in frappe / jwt / requests (directly and via auth, common,
graphql_client, bridge_client, ibex_client); none are importable outside a
bench environment. Install functional stubs BEFORE importing the module under
test, mirroring test_admin_api_send_user_alert.py.
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

# frappe.rate_limiter.rate_limit is applied at import time, so the stub has to
# be in place before the endpoint module is imported. It records the kwargs it
# was decorated with, which is how the rate-limit wiring is asserted below.
_rate_limiter = _ensure_module("frappe.rate_limiter")
if not hasattr(_rate_limiter, "rate_limit"):
	_rate_limiter.calls = []

	def _rate_limit(**kwargs):
		_rate_limiter.calls.append(kwargs)
		return lambda func: func

	_rate_limiter.rate_limit = _rate_limit
frappe.rate_limiter = _rate_limiter
# None only if a real frappe is importable (bench env) and owns the module.
RATE_LIMIT_CALLS = getattr(_rate_limiter, "calls", None)

_requests = _ensure_module("requests")
if not hasattr(_requests, "exceptions"):
	_requests.exceptions = types.SimpleNamespace(RequestException=type("RequestException", (Exception,), {}))

_ensure_module("jwt")

from admin_panel.api import support_lookup
from admin_panel.api.graphql_client import GraphQLError

NPUB = "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"

ACCOUNT = {
	"npub": NPUB,
	"username": "jaceth2009",
	"level": "TWO",
	"createdAt": "2026-01-04T10:00:00Z",
	"title": None,
	"owner": {
		"phone": "+18765550100",
		"language": "en",
		"email": {"address": "jaceth@example.com", "verified": True},
	},
	"merchants": [{"title": "Jace's Shop"}],
}


class FakeClient:
	"""Stands in for GraphQLClient: records how it was built and called."""

	def __init__(self, result=None, error=None):
		self.result = result
		self.error = error
		self.init_kwargs = None
		self.calls = []

	def factory(self, **kwargs):
		"""Used as the GraphQLClient replacement — constructing returns self."""
		self.init_kwargs = kwargs
		return self

	def execute_and_extract(self, query, variables, data_key, allow_not_found=False, **kwargs):
		self.calls.append(
			{
				"query": query,
				"variables": variables,
				"data_key": data_key,
				"allow_not_found": allow_not_found,
				**kwargs,
			}
		)
		if self.error is not None:
			raise self.error
		return self.result


@pytest.fixture()
def env(monkeypatch):
	"""Stub the frappe surfaces the endpoint touches and record what it does."""
	response = {}
	logs = {"info": [], "error": [], "warning": []}

	monkeypatch.setattr(support_lookup.frappe, "response", response, raising=False)
	monkeypatch.setattr(
		support_lookup.frappe,
		"logger",
		lambda: types.SimpleNamespace(
			info=logs["info"].append,
			error=logs["error"].append,
			warning=logs["warning"].append,
		),
		raising=False,
	)
	# A real service user, not "Administrator" — so require_roles' role lookup
	# actually runs instead of short-circuiting.
	monkeypatch.setattr(
		support_lookup.frappe,
		"session",
		types.SimpleNamespace(user="nostr-bridge@getflash.io"),
		raising=False,
	)
	monkeypatch.setattr(
		support_lookup.frappe, "get_roles", lambda user=None: ["Support Lookup"], raising=False
	)

	def use(client):
		monkeypatch.setattr(support_lookup, "GraphQLClient", client.factory)
		return client

	return types.SimpleNamespace(response=response, logs=logs, use=use)


# --- upstream call shape ---


def test_client_is_built_with_the_narrow_upstream_role(env):
	client = env.use(FakeClient(result=ACCOUNT))
	support_lookup.get_support_contact_by_npub(NPUB)
	assert client.init_kwargs == {"jwt_roles": ("Accounts Manager",)}
	assert client.init_kwargs["jwt_roles"] == support_lookup.UPSTREAM_JWT_ROLES


def test_query_is_issued_with_lookup_semantics_and_the_right_keys(env):
	client = env.use(FakeClient(result=ACCOUNT))
	support_lookup.get_support_contact_by_npub(NPUB)
	(call,) = client.calls
	assert call["query"] is support_lookup.SUPPORT_CONTACT_BY_NPUB_QUERY
	assert call["variables"] == {"npub": NPUB}
	assert call["data_key"] == "accountDetailsByNpub"
	# Without allow_not_found an unknown npub raises instead of 404-ing.
	assert call["allow_not_found"] is True
	assert call["result_type"] is dict


# --- response shapes ---


def test_known_npub_returns_the_slimmed_contact_card(env):
	env.use(FakeClient(result=ACCOUNT))
	result = support_lookup.get_support_contact_by_npub(NPUB)
	assert result == {
		"npub": NPUB,
		"username": "jaceth2009",
		"level": "TWO",
		"accountCreatedAt": "2026-01-04T10:00:00Z",
		"phone": "+18765550100",
		"email": "jaceth@example.com",
		"emailVerified": True,
		"language": "en",
		"merchantTitle": "Jace's Shop",
	}
	assert "http_status_code" not in env.response


def test_known_npub_never_returns_financial_fields(env):
	# Defence in depth behind the query's field set: whatever upstream sends,
	# only the contact contract keys leave the cluster.
	env.use(FakeClient(result={**ACCOUNT, "wallets": [{"balance": 1234}], "erpParty": "CUST-1"}))
	result = support_lookup.get_support_contact_by_npub(NPUB)
	assert set(result) == set(support_lookup.slim_support_contact(ACCOUNT))
	assert "wallets" not in result
	assert "erpParty" not in result


def test_unknown_npub_is_a_404_not_a_null_card(env):
	env.use(FakeClient(result=None))
	result = support_lookup.get_support_contact_by_npub(NPUB)
	assert result == {"error": "Account not found"}
	assert env.response["http_status_code"] == 404


# --- upstream failure must not ship resolver detail out of the cluster ---


def test_graphql_error_is_a_generic_502_with_detail_kept_in_the_cluster_log(env):
	detail = "GraphQL errors: [{'message': 'Kratos down at /accountDetailsByNpub/owner/email'}]"
	env.use(FakeClient(error=GraphQLError(detail)))

	result = support_lookup.get_support_contact_by_npub(NPUB)

	assert result == {"error": "lookup failed"}
	assert env.response["http_status_code"] == 502
	# The upstream error array must not be echoed to the droplet...
	assert detail not in str(result)
	assert "Kratos" not in str(result)
	# ...but it must be recoverable in the cluster.
	assert any(detail in line for line in env.logs["error"])


# --- audit trail ---


@pytest.mark.parametrize("account,found", [(ACCOUNT, True), (None, False)])
def test_every_lookup_is_logged_with_npub_and_caller(env, account, found):
	env.use(FakeClient(result=account))
	support_lookup.get_support_contact_by_npub(NPUB)
	(line,) = env.logs["info"]
	assert "support_lookup" in line
	assert NPUB in line
	assert "nostr-bridge@getflash.io" in line
	assert f"found={found}" in line


# --- rate limit ---


def test_endpoint_is_rate_limited_per_source_ip():
	# A leaked bridge key must not buy an attacker unbounded npub -> phone/email
	# enumeration. Recorded at import time by the frappe.rate_limiter stub.
	if RATE_LIMIT_CALLS is None:
		pytest.skip("real frappe.rate_limiter is installed; nothing recorded")
	assert RATE_LIMIT_CALLS, "get_support_contact_by_npub must be wrapped in rate_limit"
	kwargs = RATE_LIMIT_CALLS[-1]
	assert kwargs["ip_based"] is True
	assert kwargs["limit"] == support_lookup.SUPPORT_LOOKUP_RATE_LIMIT
	assert kwargs["seconds"] == support_lookup.SUPPORT_LOOKUP_RATE_WINDOW
	# key= would bucket per (ip, npub), handing an enumerator a fresh
	# allowance for every new npub — the opposite of the point.
	assert "key" not in kwargs


# --- role gate ---


def test_caller_without_the_service_role_is_rejected(env, monkeypatch):
	client = env.use(FakeClient(result=ACCOUNT))
	monkeypatch.setattr(
		support_lookup.frappe, "get_roles", lambda user=None: ["Website Manager"], raising=False
	)
	with pytest.raises(support_lookup.frappe.PermissionError):
		support_lookup.get_support_contact_by_npub(NPUB)
	assert client.calls == []

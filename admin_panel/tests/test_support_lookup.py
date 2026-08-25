"""Behavioral tests for the support contact lookup relay endpoint.

``get_support_contact_by_npub`` is the one endpoint in this app whose caller
sits outside the cluster (the nostr-dm-bridge on the support droplet) and whose
output is PII — phone number and email address, keyed by a public identifier.
Everything that keeps that safe is exercised for real here, with a stubbed
frappe and a fake GraphQL client, so that a flipped ``allow_not_found``, a
misnamed variable key, a deleted not-found branch, a dropped per-caller quota,
an unvalidated npub forging audit lines, a missing audit line, or an upstream
error array / internal URL leaking out of the cluster fails in this file
instead of on the droplet.

The source-level invariants behavior cannot reach — the upstream query's field
set, the Role provisioning in setup.py, the repo-wide confinement of
``jwt_roles`` — live in test_support_lookup_contract.py. The JWT the client
actually mints is pinned in test_graphql_client_extract.py.

support_lookup pulls in frappe / jwt / requests (directly and via auth, common,
graphql_client, bridge_client, ibex_client); none are importable outside a
bench environment. Install functional stubs BEFORE importing the module under
test, mirroring test_admin_api_send_user_alert.py.
"""

import inspect
import logging
import re
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
if not hasattr(frappe, "RateLimitExceededError"):
	# Real frappe subclasses ValidationError, so handle_api_errors lets it
	# through as user-facing rather than masking it as an internal error.
	frappe.RateLimitExceededError = type("RateLimitExceededError", (frappe.ValidationError,), {})
if not hasattr(frappe, "response"):
	frappe.response = {}
if not hasattr(frappe, "throw"):

	def _throw(message, exc=None):
		raise (exc or frappe.ValidationError)(message)

	frappe.throw = _throw

# frappe.rate_limiter.rate_limit is applied at import time, so the stub has to
# be in place before the endpoint module is imported. It records
# (function name, kwargs) — the name matters because the stub is installed
# globally in sys.modules, so "the last decoration recorded anywhere in the
# pytest session" would silently become some other module's the moment a
# second endpoint uses @rate_limit.
_rate_limiter = _ensure_module("frappe.rate_limiter")
if not hasattr(_rate_limiter, "rate_limit"):
	_rate_limiter.calls = []

	def _rate_limit(**kwargs):
		def decorator(func):
			_rate_limiter.calls.append((func.__name__, kwargs))
			return func

		return decorator

	_rate_limiter.rate_limit = _rate_limit
frappe.rate_limiter = _rate_limiter
# None only if a real frappe is importable (bench env) and owns the module.
RATE_LIMIT_CALLS = getattr(_rate_limiter, "calls", None)

_requests = _ensure_module("requests")
if not hasattr(_requests, "exceptions"):
	_request_exception = type("RequestException", (Exception,), {})
	_requests.exceptions = types.SimpleNamespace(
		RequestException=_request_exception,
		HTTPError=type("HTTPError", (_request_exception,), {}),
	)

_ensure_module("jwt")

from admin_panel.api import support_lookup
from admin_panel.api.graphql_client import GraphQLError

NPUB = "npub1" + "q" * 58

# The bridge key holder controls this string. Without validation it is
# interpolated straight into the audit line, so the second line here becomes a
# complete, plausible forged entry for a different account attributed to a
# different user — in the log that is supposed to answer "which accounts were
# exposed" after that very key leaks.
FORGED_NPUB = NPUB + "\nsupport_lookup npub=npub1victim by admin@getflash.io found=False"

# createdAt is upstream's Timestamp! scalar, which serializes as Unix SECONDS
# (flash src/graphql/shared/types/scalar/timestamp.ts), not an ISO string.
# The bridge reads this test as the wire contract; an ISO fixture here would
# put 1970 on every Chatwoot card.
CREATED_AT = 1767520800

ACCOUNT = {
	"npub": NPUB,
	"username": "jaceth2009",
	"level": "TWO",
	"createdAt": CREATED_AT,
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


class FakeCache:
	"""Minimal stand-in for frappe's RedisWrapper counter surface."""

	def __init__(self):
		self.store = {}
		self.expires = {}

	def make_key(self, key):
		return f"testsite||{key}"

	def incrby(self, key, amount):
		self.store[key] = self.store.get(key, 0) + amount
		return self.store[key]

	def expire(self, key, seconds):
		self.expires[key] = seconds


class RecordingLoggers:
	"""Stands in for frappe.logger(), including the level that hides records.

	Real frappe hands back a logger set to `frappe.log_level or
	default_log_level`, and off a dev server that default is ERROR — which is
	why a bare `frappe.logger().info(...)` writes nothing on the cluster. So
	the logger handed out here starts at ERROR too, and records are captured
	through a handler rather than by monkeypatching `.info`. A module that
	stops raising its own level therefore loses its audit lines HERE, in the
	log-content assertions below, instead of only in production.
	"""

	def __init__(self, sink):
		self.sink = sink
		self.made = []
		self.loggers = {}

	def __call__(self, module=None, **kwargs):
		self.made.append((module, kwargs))
		if module not in self.loggers:
			logger = logging.getLogger(f"test-support-lookup-{module}")
			logger.handlers[:] = []
			logger.addHandler(_SinkHandler(self.sink))
			logger.propagate = False
			# frappe sets the level once, when it first builds the logger.
			logger.setLevel(logging.ERROR)
			self.loggers[module] = logger
		return self.loggers[module]


class _SinkHandler(logging.Handler):
	def __init__(self, sink):
		super().__init__(level=logging.NOTSET)
		self.sink = sink

	def emit(self, record):
		# setdefault, not [...]: an unexpected level would otherwise raise out
		# of the logging call and surface as a phantom generic 500.
		self.sink.setdefault(record.levelname.lower(), []).append(record.getMessage())


@pytest.fixture()
def env(monkeypatch):
	"""Stub the frappe surfaces the endpoint touches and record what it does."""
	response = {}
	logs = {"info": [], "error": [], "warning": []}
	logger_factory = RecordingLoggers(logs)
	cache = FakeCache()

	monkeypatch.setattr(support_lookup.frappe, "response", response, raising=False)
	monkeypatch.setattr(support_lookup.frappe, "cache", cache, raising=False)
	monkeypatch.setattr(support_lookup.frappe, "logger", logger_factory, raising=False)
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

	return types.SimpleNamespace(response=response, logs=logs, cache=cache, use=use, loggers=logger_factory)


# --- input validation (must run before the log and before the upstream call) ---


@pytest.mark.parametrize(
	"bad",
	[
		pytest.param(FORGED_NPUB, id="newline-forges-an-audit-line"),
		# Regression pin: with `$` instead of `\Z` this one passes validation —
		# Python's `$` matches before a trailing newline.
		pytest.param(NPUB + "\n", id="trailing-newline"),
		pytest.param(NPUB + " ", id="trailing-space"),
		pytest.param("npub1" + "q" * 57, id="too-short"),
		pytest.param("npub1" + "q" * 59, id="too-long"),
		pytest.param("npub1" + "b" * 58, id="outside-bech32-charset"),
		pytest.param("nsec1" + "q" * 58, id="wrong-prefix"),
		pytest.param("", id="empty"),
		pytest.param(None, id="missing"),
		pytest.param([NPUB, NPUB], id="repeated-query-param-arrives-as-a-list"),
		pytest.param(12345, id="non-string"),
	],
)
def test_malformed_npub_is_a_400_that_never_reaches_the_log_or_the_upstream(env, bad):
	client = env.use(FakeClient(result=ACCOUNT))
	result = support_lookup.get_support_contact_by_npub(bad)
	assert result == {"error": "invalid npub"}
	assert env.response["http_status_code"] == 400
	# No round-trip against the cluster-internal admin API...
	assert client.calls == []
	# ...and nothing the caller controls reaches the audit log.
	assert env.logs["info"] == []


def test_a_forged_npub_cannot_write_a_second_audit_line(env):
	env.use(FakeClient(result=ACCOUNT))
	support_lookup.get_support_contact_by_npub(FORGED_NPUB)
	assert not any("npub1victim" in line for line in env.logs["info"])


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
		# Unix seconds, matching upstream's Timestamp! scalar.
		"accountCreatedAt": CREATED_AT,
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


def test_transport_failure_never_ships_the_internal_graphql_url_to_the_droplet(env):
	# execute_query calls response.raise_for_status(), so an upstream 5xx or a
	# connection failure surfaces as a requests exception, not a GraphQLError.
	# Uncaught, handle_api_errors echoes str(e) — which names the internal URL.
	url = "http://flash-admin-api.flash.svc.cluster.local:4002/admin/graphql"
	detail = f"500 Server Error: Internal Server Error for url: {url}"
	env.use(FakeClient(error=_requests.exceptions.HTTPError(detail)))

	result = support_lookup.get_support_contact_by_npub(NPUB)

	assert result == {"error": "lookup failed"}
	assert env.response["http_status_code"] == 502
	assert url not in str(result)
	assert any(url in line for line in env.logs["error"])


def test_connection_failure_is_the_same_generic_502(env):
	env.use(FakeClient(error=_requests.exceptions.RequestException("connection refused")))
	result = support_lookup.get_support_contact_by_npub(NPUB)
	assert result == {"error": "lookup failed"}
	assert env.response["http_status_code"] == 502


# --- audit trail ---


@pytest.mark.parametrize("account,found", [(ACCOUNT, True), (None, False)])
def test_every_lookup_is_logged_with_npub_and_caller(env, account, found):
	env.use(FakeClient(result=account))
	support_lookup.get_support_contact_by_npub(NPUB)
	attempt, outcome = env.logs["info"]
	for line in (attempt, outcome):
		assert "support_lookup" in line
		assert NPUB in line
		assert "nostr-bridge@getflash.io" in line
	assert "attempt" in attempt
	assert f"found={found}" in outcome


def test_the_attempt_is_logged_before_the_upstream_call(env):
	# After a key compromise the question is which npubs were PROBED, not
	# which ones resolved. A burst of enumeration against an unreachable
	# flash-api must still name every npub.
	env.use(FakeClient(error=GraphQLError("upstream down")))
	support_lookup.get_support_contact_by_npub(NPUB)
	(line,) = env.logs["info"]
	assert line == f"support_lookup attempt npub={NPUB} by nostr-bridge@getflash.io"


# --- per-caller quota ---


def test_caller_quota_is_bucketed_on_the_authenticated_user(env):
	# The asset at risk is the bridge's frappe key, and whoever holds it picks
	# their own source address — so the cap has to bind the identity, not the
	# network path.
	client = env.use(FakeClient(result=ACCOUNT))
	for _ in range(support_lookup.SUPPORT_LOOKUP_RATE_LIMIT):
		support_lookup.get_support_contact_by_npub(NPUB)

	with pytest.raises(support_lookup.frappe.RateLimitExceededError):
		support_lookup.get_support_contact_by_npub(NPUB)

	assert env.response["http_status_code"] == 429
	# The line that fires WHILE a leaked key is being used, not after: it is
	# the signal that the compromise is live, so it has to survive the level
	# too. Deleting it must fail here.
	assert any(
		"quota exceeded" in line and "nostr-bridge@getflash.io" in line for line in env.logs["warning"]
	)
	# The blocked call never reached upstream.
	assert len(client.calls) == support_lookup.SUPPORT_LOOKUP_RATE_LIMIT
	assert env.cache.store, "the quota must actually count something"
	assert all("nostr-bridge@getflash.io" in key for key in env.cache.store)
	assert env.cache.expires, "the counter key must get a TTL"
	assert all(ttl == support_lookup.SUPPORT_LOOKUP_RATE_WINDOW for ttl in env.cache.expires.values())


def test_a_different_caller_is_unaffected_by_an_exhausted_quota(env, monkeypatch):
	env.use(FakeClient(result=ACCOUNT))
	for _ in range(support_lookup.SUPPORT_LOOKUP_RATE_LIMIT):
		support_lookup.get_support_contact_by_npub(NPUB)

	monkeypatch.setattr(
		support_lookup.frappe,
		"session",
		types.SimpleNamespace(user="admin@getflash.io"),
		raising=False,
	)
	result = support_lookup.get_support_contact_by_npub(NPUB)
	assert result["npub"] == NPUB
	assert "http_status_code" not in env.response


def test_quota_rejection_is_not_bucketed_per_npub(env):
	# A fresh allowance per npub is exactly the enumeration the cap exists to
	# stop, so walking distinct npubs must not reset the counter.
	env.use(FakeClient(result=ACCOUNT))
	charset = "023456789acdefghjklmnpqrstuvwxyz"
	for i in range(support_lookup.SUPPORT_LOOKUP_RATE_LIMIT):
		# Distinct, well-formed npubs — one per allowed call.
		suffix = charset[i // len(charset)] + charset[i % len(charset)]
		support_lookup.get_support_contact_by_npub("npub1" + "q" * 56 + suffix)
	with pytest.raises(support_lookup.frappe.RateLimitExceededError):
		support_lookup.get_support_contact_by_npub(NPUB)


def test_malformed_npub_still_costs_the_caller_quota(env):
	# Otherwise garbage is free: a leaked bridge key can stream unlimited
	# invalid npubs through whitelist auth and frappe.get_roles without moving
	# a counter or writing a line anywhere.
	env.use(FakeClient(result=ACCOUNT))
	for _ in range(support_lookup.SUPPORT_LOOKUP_RATE_LIMIT):
		support_lookup.get_support_contact_by_npub("not-an-npub")

	with pytest.raises(support_lookup.frappe.RateLimitExceededError):
		support_lookup.get_support_contact_by_npub(NPUB)


def test_the_quota_window_rolls_over(env, monkeypatch):
	# The counter is keyed by window number so it expires on its own. If that
	# key ever became constant, the honest bridge would 429 forever once it hit
	# SUPPORT_LOOKUP_RATE_LIMIT lifetime lookups, and every Chatwoot card would
	# silently degrade to "Unavailable" — the bridge treats any relay failure
	# as enrich-skip.
	env.use(FakeClient(result=ACCOUNT))
	now = float(CREATED_AT)
	monkeypatch.setattr(support_lookup.time, "time", lambda: now)

	for _ in range(support_lookup.SUPPORT_LOOKUP_RATE_LIMIT):
		support_lookup.get_support_contact_by_npub(NPUB)
	with pytest.raises(support_lookup.frappe.RateLimitExceededError):
		support_lookup.get_support_contact_by_npub(NPUB)

	now += support_lookup.SUPPORT_LOOKUP_RATE_WINDOW
	assert support_lookup.get_support_contact_by_npub(NPUB)["npub"] == NPUB


# --- audit logger ---


def test_the_audit_logger_actually_emits_info(env):
	# frappe.logger() hands back a logger set to ERROR off a dev server, so a
	# bare frappe.logger().info(...) writes nothing on the cluster — where this
	# is the only record of which accounts a leaked bridge key read.
	env.use(FakeClient(result=ACCOUNT))
	support_lookup.get_support_contact_by_npub(NPUB)

	logger = support_lookup._audit_logger()
	assert logger.isEnabledFor(logging.INFO)
	assert env.logs["info"], "the audit lines have to survive the level"


def test_the_audit_logger_gets_its_own_file(env):
	# Its own module name keeps PII-bearing lines out of the shared
	# logs/frappe.log, where unrelated frappe chatter would rotate them away.
	env.use(FakeClient(result=ACCOUNT))
	support_lookup.get_support_contact_by_npub(NPUB)

	modules = {module for module, _ in env.loggers.made}
	assert modules == {"support_lookup"}
	assert all(kwargs.get("file_count") for _, kwargs in env.loggers.made)


# --- rate limit decorator (second, weaker layer) ---

ENDPOINT_SRC = inspect.getsource(support_lookup)


def _rate_limit_decorator_source(fn_name):
	m = re.search(
		r"@rate_limit\(([^)]*)\)\s*\n(?:@[^\n]*\n)*def " + re.escape(fn_name) + r"\(",
		ENDPOINT_SRC,
	)
	assert m, f"{fn_name} must be wrapped in @rate_limit"
	return m.group(1)


def _recorded_rate_limit_kwargs(fn_name, recorded=None):
	"""The kwargs THIS endpoint was decorated with, not whatever was last."""
	for name, kwargs in (RATE_LIMIT_CALLS if recorded is None else recorded) or []:
		if name == fn_name:
			return kwargs
	return None


def test_endpoint_is_rate_limited_per_source_ip():
	# A leaked bridge key must not buy an attacker unbounded npub -> phone/email
	# enumeration. The source form holds in every environment, including a
	# bench where the real frappe.rate_limiter owns the module and the stub
	# records nothing — so there is no environment in which this is vacuous.
	decorator = _rate_limit_decorator_source("get_support_contact_by_npub")
	assert "ip_based=True" in decorator
	assert "limit=SUPPORT_LOOKUP_RATE_LIMIT" in decorator
	assert "seconds=SUPPORT_LOOKUP_RATE_WINDOW" in decorator
	# key= would bucket per (ip, npub), handing an enumerator a fresh
	# allowance for every new npub — the opposite of the point.
	assert "key=" not in decorator

	kwargs = _recorded_rate_limit_kwargs("get_support_contact_by_npub")
	if kwargs is not None:
		assert kwargs["ip_based"] is True
		assert kwargs["limit"] == support_lookup.SUPPORT_LOOKUP_RATE_LIMIT
		assert kwargs["seconds"] == support_lookup.SUPPORT_LOOKUP_RATE_WINDOW
		assert "key" not in kwargs


def test_rate_limit_assertion_selects_this_endpoints_decoration():
	# Guards the guard: the stub is global, so a second module using
	# @rate_limit must not be able to satisfy the assertion above.
	recorded = [
		("some_other_endpoint", {"ip_based": False, "limit": 1, "seconds": 1}),
		("get_support_contact_by_npub", {"ip_based": True, "limit": 120, "seconds": 3600}),
		("a_later_collected_endpoint", {"ip_based": False, "limit": 5, "seconds": 5}),
	]
	assert _recorded_rate_limit_kwargs("get_support_contact_by_npub", recorded) == {
		"ip_based": True,
		"limit": 120,
		"seconds": 3600,
	}
	assert _recorded_rate_limit_kwargs("never_decorated", recorded) is None


# --- role gate ---


def test_caller_without_the_service_role_is_rejected(env, monkeypatch):
	client = env.use(FakeClient(result=ACCOUNT))
	monkeypatch.setattr(
		support_lookup.frappe, "get_roles", lambda user=None: ["Website Manager"], raising=False
	)
	with pytest.raises(support_lookup.frappe.PermissionError):
		support_lookup.get_support_contact_by_npub(NPUB)
	assert client.calls == []

"""Support contact lookup relay for the nostr-dm-bridge.

The admin GraphQL API is cluster-internal; the bridge that turns in-app
Nostr DMs into Chatwoot conversations runs on the support droplet outside
the cluster. This endpoint is the narrow, authenticated bridge between the
two: npub in, identity card out. See support_lookup_core for the shape.
"""

import logging
import re
import sys
import time

import frappe
import requests
from frappe.rate_limiter import rate_limit

from .auth import ADMIN_ROLES, require_roles
from .common import handle_api_errors
from .graphql_client import GraphQLClient, GraphQLError
from .support_lookup_core import slim_support_contact

# The bridge authenticates as a dedicated Frappe service user holding only
# "Support Lookup" (created by setup.ensure_roles, no desk access) — a leaked
# bridge key can call exactly this read and nothing else. Human admins keep
# access for debugging.
SUPPORT_LOOKUP_ROLES = ["Support Lookup", *ADMIN_ROLES]

# Roles minted into the upstream JWT for this call. The frappe-side role gate
# above is the security boundary; the service user deliberately does NOT hold
# Accounts Manager in frappe (that would open ERPNext banking doctypes to the
# bridge key). Keep this endpoint read-only-narrow or move the boundary.
UPSTREAM_JWT_ROLES = ("Accounts Manager",)

# npub is bech32: the "npub1" HRP + separator, then exactly 58 characters of
# the bech32 charset (no "1", "b", "i" or "o"). Anything else is rejected
# before it reaches the audit log or the upstream API — see
# _reject_malformed_npub for why that ordering is the point.
# \Z, not $: in Python, $ also matches just before a trailing newline, and a
# trailing "\n" is precisely the character the audit-line defense exists to
# keep out.
NPUB_RE = re.compile(r"^npub1[023456789acdefghjklmnpqrstuvwxyz]{58}\Z")

# The bridge key lives in the environment of an internet-facing support
# droplet. If it leaks, npubs scraped from public Nostr relays could be walked
# through this endpoint to build a bulk npub -> phone/email deanonymization
# list, so the call volume is capped twice.
#
# The cap that matters is _enforce_caller_quota below: it buckets on the
# authenticated frappe user, which is the thing the leaked key actually is.
# The @rate_limit decorator is a second, weaker layer — frappe derives
# request_ip from the leftmost X-Forwarded-For value (frappe/auth.py), so it
# binds only callers who cannot pick their own source address, and a proxy
# pool defeats it. It is kept for cheap shedding ahead of the role-gate DB
# lookup (frappe dispatches whitelisted functions after session auth, so
# nothing here runs pre-auth), not relied on.
#
# Deliberately NOT key="npub" on the decorator: frappe buckets on "<ip>:<key>"
# when a key is given, which hands an enumerator a fresh allowance for every
# new npub — exactly the attack. Both caps are sized above the bridge's real
# volume (one lookup per new DM thread, and it caches) but kept tight: every
# unit of headroom over honest traffic is attacker budget after a key leak.
SUPPORT_LOOKUP_RATE_LIMIT = 30
SUPPORT_LOOKUP_RATE_WINDOW = 60 * 60

# Identity fields only — never add wallets/balances here (the response
# leaves the cluster; see support_lookup_core docstring).
SUPPORT_CONTACT_BY_NPUB_QUERY = """
	query accountDetailsByNpub($npub: npub!) {
		accountDetailsByNpub(npub: $npub) {
			npub
			username
			level
			createdAt
			title
			owner {
				phone
				language
				email {
					address
					verified
				}
			}
			merchants {
				title
			}
		}
	}
"""


# Built once, at import, and attached by identity below.
#
# Two reasons it is a module-level singleton rather than a fresh handler per
# request. `Logger.addHandler` is membership-checked under logging's own lock,
# so re-attaching THIS object is idempotent and race-free; a per-request
# `logging.StreamHandler(sys.stdout)` guarded by a check-then-set flag is not —
# frappe serves under gthread gunicorn workers, and two concurrent first
# requests in a fresh worker can both see the flag unset and both attach,
# permanently doubling every audit line that worker emits. In the log that
# answers "how many lookups did the leaked key make", duplicated lines corrupt
# the count.
#
# And the formatter is load-bearing, not cosmetic: with none, logging falls
# back to "%(message)s" and the stdout copy carries no level, so the "quota
# exceeded" WARNING — the line that fires WHILE a leaked key is being abused —
# reaches the collector in a shape indistinguishable from a routine INFO
# lookup. There would be no level to alert on.
_AUDIT_STDOUT_HANDLER = logging.StreamHandler(sys.stdout)
_AUDIT_STDOUT_HANDLER.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))


def _audit_logger():
	"""The audit logger, at a level that actually emits.

	`frappe.logger()` sets the level to `frappe.log_level or
	default_log_level`, and frappe defines `default_log_level = WARNING if
	frappe._dev_server else ERROR` (frappe/utils/logger.py). `log_level` is
	initialised to None, nothing in frappe or this app ever calls
	`set_log_level`, and DEV_SERVER is unset in the frappe/erpnext image — so
	on the cluster the effective threshold is ERROR and every INFO record
	here would be discarded before reaching a handler. Hence the explicit
	setLevel: without it this "audit trail" writes nothing in the one
	environment where it matters.

	The module name also gives it its own file rather than interleaving
	PII-bearing lines into the shared `logs/frappe.log`, where unrelated
	frappe chatter would rotate them away.

	The file handlers frappe attaches are pod-local and this deployment
	mounts no PVC over `logs/`, so a restart or a node drain takes the
	history with it — exactly when you need it, since rotating the leaked
	key means redeploying. frappe only adds a stream handler when
	FRAPPE_STREAM_LOGGING is set, which this cluster does not set, so
	_AUDIT_STDOUT_HANDLER, attached below, is what actually gets these lines
	off the pod and into the log collector.
	"""
	# frappe.logger caches by "<module>-<site>" and sets the level only when
	# it first builds the logger, so this setLevel sticks for the worker.
	logger = frappe.logger("support_lookup", max_size=1_000_000, file_count=20)
	logger.setLevel(logging.INFO)
	# This runs per request and handlers stack silently, so idempotence
	# matters. addHandler is a locked membership check, so re-attaching the
	# same object is a no-op no matter how many workers race here.
	logger.addHandler(_AUDIT_STDOUT_HANDLER)
	return logger


def _cache():
	"""frappe.cache is a function on v14 and a bound RedisWrapper on v15."""
	cache = getattr(frappe, "cache", None)
	return cache() if callable(cache) else cache


def _enforce_caller_quota():
	"""Cap lookups per authenticated caller, not per source address.

	The asset at risk is the bridge's frappe key. Whoever holds it picks
	their own source IP (a proxy pool turns an IP-bucketed cap into no cap
	at all), and frappe reads request_ip from the client-supplied
	X-Forwarded-For header, so an IP bucket is only as trustworthy as an
	ingress config living in another repo. The session user is the identity
	the key actually authenticates as, so that is what gets metered.

	Fixed window, keyed by window number so the counter rolls over on its
	own even if a process dies before the TTL is set.
	"""
	cache = _cache()
	if cache is None:  # pragma: no cover - no cache backend configured
		return
	window = int(time.time() // SUPPORT_LOOKUP_RATE_WINDOW)
	key = cache.make_key(f"rl:support_lookup:{window}:{frappe.session.user}")
	count = cache.incrby(key, 1)
	cache.expire(key, SUPPORT_LOOKUP_RATE_WINDOW)
	if count > SUPPORT_LOOKUP_RATE_LIMIT:
		_audit_logger().warning(
			f"support_lookup quota exceeded by {frappe.session.user} ({count} in window {window})"
		)
		frappe.response["http_status_code"] = 429
		frappe.throw("Support lookup quota exceeded", frappe.RateLimitExceededError)


def _reject_malformed_npub(npub):
	"""True if the caller gets a 400 instead of a lookup.

	Two reasons this runs before the audit line and the upstream call. That
	line interpolates the npub raw, so an unvalidated value containing a newline
	lets the caller forge a complete, plausible log entry for a different
	account attributed to a different user — in the one log that answers
	"which accounts were exposed" after a bridge-key compromise, writable by
	the party you would be investigating. And every garbage string would
	otherwise burn a round-trip against the cluster-internal admin API.
	"""
	# isinstance, not just the regex: a repeated query param arrives as a list
	# and would make .match() raise, which handle_api_errors turns into a 500.
	if isinstance(npub, str) and NPUB_RE.match(npub):
		return False
	frappe.response["http_status_code"] = 400
	return True


@frappe.whitelist()
@rate_limit(limit=SUPPORT_LOOKUP_RATE_LIMIT, seconds=SUPPORT_LOOKUP_RATE_WINDOW, ip_based=True)
@require_roles(SUPPORT_LOOKUP_ROLES)
@handle_api_errors
def get_support_contact_by_npub(npub):
	"""Resolve a Nostr npub to the identity fields a Chatwoot contact card needs."""
	# Quota first: otherwise malformed input is free, and a leaked bridge key
	# can stream unlimited garbage npubs through whitelist auth and
	# frappe.get_roles without moving a counter or writing a line. The helper
	# never touches `npub`, so nothing caller-controlled is interpolated
	# before validation and the forged-audit-line guarantee still holds.
	_enforce_caller_quota()
	if _reject_malformed_npub(npub):
		return {"error": "invalid npub"}

	# Audit trail: this read turns a public identifier into phone + email and
	# its caller sits outside the cluster. After a bridge-key compromise this
	# log is the only way to answer "which accounts were exposed" — so the
	# attempt is recorded BEFORE the upstream call. A burst of enumeration
	# during an upstream outage must still name every npub that was probed.
	_audit_logger().info(f"support_lookup attempt npub={npub} by {frappe.session.user}")

	client = GraphQLClient(jwt_roles=UPSTREAM_JWT_ROLES)
	try:
		account = client.execute_and_extract(
			SUPPORT_CONTACT_BY_NPUB_QUERY,
			{"npub": npub},
			"accountDetailsByNpub",
			allow_not_found=True,
			result_type=dict,
		)
	except (GraphQLError, requests.exceptions.RequestException) as e:
		# handle_api_errors would echo str(e) into a body that leaves the
		# cluster for the droplet: the whole upstream error array for a
		# GraphQLError, and for a transport failure the internal GraphQL URL
		# itself ("500 Server Error ... for url: <flash_admin_api_url>").
		# execute_query calls raise_for_status(), so both are live paths.
		# Keep the detail in the cluster log.
		_audit_logger().error(f"support_lookup upstream error for npub={npub}: {e}")
		frappe.response["http_status_code"] = 502
		return {"error": "lookup failed"}

	_audit_logger().info(f"support_lookup npub={npub} by {frappe.session.user} found={account is not None}")

	if account is None:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return slim_support_contact(account)

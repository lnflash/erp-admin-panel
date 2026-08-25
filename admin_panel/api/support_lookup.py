"""Support contact lookup relay for the nostr-dm-bridge.

The admin GraphQL API is cluster-internal; the bridge that turns in-app
Nostr DMs into Chatwoot conversations runs on the support droplet outside
the cluster. This endpoint is the narrow, authenticated bridge between the
two: npub in, identity card out. See support_lookup_core for the shape.
"""

import re
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
NPUB_RE = re.compile(r"^npub1[023456789acdefghjklmnpqrstuvwxyz]{58}$")

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
# pool defeats it. It is kept for cheap pre-auth shedding, not relied on.
#
# Deliberately NOT key="npub" on the decorator: frappe buckets on "<ip>:<key>"
# when a key is given, which hands an enumerator a fresh allowance for every
# new npub — exactly the attack. Both caps are sized well above the bridge's
# real volume (one lookup per new DM thread, and it caches).
SUPPORT_LOOKUP_RATE_LIMIT = 120
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
		frappe.logger().warning(
			f"support_lookup quota exceeded by {frappe.session.user} ({count} in window {window})"
		)
		frappe.response["http_status_code"] = 429
		frappe.throw("Support lookup quota exceeded", frappe.RateLimitExceededError)


def _reject_malformed_npub(npub):
	"""True if the caller gets a 400 instead of a lookup.

	Two reasons this runs before anything else. The audit line below
	interpolates the npub raw, so an unvalidated value containing a newline
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
	if _reject_malformed_npub(npub):
		return {"error": "invalid npub"}
	_enforce_caller_quota()

	# Audit trail: this read turns a public identifier into phone + email and
	# its caller sits outside the cluster. After a bridge-key compromise this
	# log is the only way to answer "which accounts were exposed" — so the
	# attempt is recorded BEFORE the upstream call. A burst of enumeration
	# during an upstream outage must still name every npub that was probed.
	frappe.logger().info(f"support_lookup attempt npub={npub} by {frappe.session.user}")

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
		frappe.logger().error(f"support_lookup upstream error for npub={npub}: {e}")
		frappe.response["http_status_code"] = 502
		return {"error": "lookup failed"}

	frappe.logger().info(f"support_lookup npub={npub} by {frappe.session.user} found={account is not None}")

	if account is None:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return slim_support_contact(account)

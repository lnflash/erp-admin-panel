"""Support contact lookup relay for the nostr-dm-bridge.

The admin GraphQL API is cluster-internal; the bridge that turns in-app
Nostr DMs into Chatwoot conversations runs on the support droplet outside
the cluster. This endpoint is the narrow, authenticated bridge between the
two: npub in, identity card out. See support_lookup_core for the shape.
"""

import frappe
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

# The bridge key lives in the environment of an internet-facing support
# droplet. If it leaks, npubs scraped from public Nostr relays could be walked
# through this endpoint to build a bulk npub -> phone/email deanonymization
# list, so cap the call volume per source IP.
#
# Deliberately NOT key="npub": frappe's rate limiter buckets on "<ip>:<key>"
# when a key is given, which hands an enumerator a fresh allowance for every
# new npub — exactly the attack. Bucketing on IP alone caps total lookups from
# any one caller. Sized well above the bridge's real volume (one lookup per
# new DM thread, and it caches).
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


@frappe.whitelist()
@rate_limit(limit=SUPPORT_LOOKUP_RATE_LIMIT, seconds=SUPPORT_LOOKUP_RATE_WINDOW, ip_based=True)
@require_roles(SUPPORT_LOOKUP_ROLES)
@handle_api_errors
def get_support_contact_by_npub(npub):
	"""Resolve a Nostr npub to the identity fields a Chatwoot contact card needs."""
	client = GraphQLClient(jwt_roles=UPSTREAM_JWT_ROLES)
	try:
		account = client.execute_and_extract(
			SUPPORT_CONTACT_BY_NPUB_QUERY,
			{"npub": npub},
			"accountDetailsByNpub",
			allow_not_found=True,
			result_type=dict,
		)
	except GraphQLError as e:
		# handle_api_errors would echo str(e) — the whole upstream error array,
		# resolver paths and messages included — into a body that leaves the
		# cluster for the droplet. Keep the detail in the cluster log.
		frappe.logger().error(f"support_lookup upstream error for npub={npub}: {e}")
		frappe.response["http_status_code"] = 502
		return {"error": "lookup failed"}

	# Audit trail: this read turns a public identifier into phone + email and
	# its caller sits outside the cluster. After a bridge-key compromise this
	# log is the only way to answer "which accounts were exposed".
	frappe.logger().info(f"support_lookup npub={npub} by {frappe.session.user} found={account is not None}")

	if account is None:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return slim_support_contact(account)

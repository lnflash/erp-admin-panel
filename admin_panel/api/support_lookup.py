"""Support contact lookup relay for the nostr-dm-bridge.

The admin GraphQL API is cluster-internal; the bridge that turns in-app
Nostr DMs into Chatwoot conversations runs on the support droplet outside
the cluster. This endpoint is the narrow, authenticated bridge between the
two: npub in, identity card out. See support_lookup_core for the shape.
"""

import frappe

from .auth import ADMIN_ROLES, require_roles
from .common import handle_api_errors
from .graphql_client import GraphQLClient
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
@require_roles(SUPPORT_LOOKUP_ROLES)
@handle_api_errors
def get_support_contact_by_npub(npub):
	"""Resolve a Nostr npub to the identity fields a Chatwoot contact card needs."""
	client = GraphQLClient(jwt_roles=UPSTREAM_JWT_ROLES)
	account = client.execute_and_extract(
		SUPPORT_CONTACT_BY_NPUB_QUERY,
		{"npub": npub},
		"accountDetailsByNpub",
		allow_not_found=True,
		result_type=dict,
	)

	if account is None:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return slim_support_contact(account)

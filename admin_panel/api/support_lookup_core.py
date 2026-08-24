"""Pure shaping for the support contact lookup relay.

The nostr-dm-bridge (flash-support-infra, pulse-server) calls
``get_support_contact_by_npub`` to enrich the Chatwoot contact card it
creates for an in-app Nostr DM. Whatever this module returns leaves the
cluster and lands on the support droplet, so the shape is deliberately
narrow: identity fields only, never wallets or balances.

No frappe import — testable under plain pytest, matching *_core style.
"""

# The exact keys the bridge consumes — a contract with
# services/nostr-dm-bridge/bridge.mjs in flash-support-infra.
SUPPORT_CONTACT_KEYS = (
	"npub",
	"username",
	"level",
	"accountCreatedAt",
	"phone",
	"email",
	"emailVerified",
	"language",
	"merchantTitle",
)


def slim_support_contact(account):
	"""Shape an AuditedAccount payload into the support contact contract.

	Tolerates missing blocks: lookup semantics allow partial responses
	(e.g. owner.email failing on a dangling Kratos identity), so every
	field degrades to None instead of raising.
	"""
	owner = account.get("owner") or {}
	email = owner.get("email") or {}
	merchant_title = next(
		(m["title"] for m in (account.get("merchants") or []) if m and m.get("title")),
		None,
	)
	return {
		"npub": account.get("npub"),
		"username": account.get("username"),
		"level": account.get("level"),
		"accountCreatedAt": account.get("createdAt"),
		"phone": owner.get("phone"),
		"email": email.get("address"),
		"emailVerified": bool(email.get("verified")) if email.get("address") else None,
		"language": owner.get("language"),
		"merchantTitle": merchant_title or account.get("title"),
	}

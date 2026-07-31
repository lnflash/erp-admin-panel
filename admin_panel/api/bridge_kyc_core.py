"""Pure join/summary logic for the bridge-kyc page.

No frappe or IO imports — everything here takes plain dicts (Bridge customers
from bridge_client, linked accounts from mongo_reader) so it can be unit-tested
directly, mirroring census_core.

Bridge customer statuses (observed in prod + Bridge docs): not_started,
incomplete, awaiting_questionnaire, awaiting_ubo, under_review, active,
rejected, paused, offboarded. An account whose linked customer id no longer
exists at Bridge gets the synthetic status "missing_at_bridge".
"""

MISSING_AT_BRIDGE = "missing_at_bridge"

# Display buckets for tiles/filters. Unknown statuses land in "attention" on
# purpose — a status we have never seen should be surfaced, not hidden.
BUCKETS = {
	"active": "approved",
	"incomplete": "in_progress",
	"awaiting_questionnaire": "in_progress",
	"awaiting_ubo": "in_progress",
	"under_review": "in_progress",
	"not_started": "not_started",
	"rejected": "attention",
	"paused": "attention",
	"offboarded": "attention",
	MISSING_AT_BRIDGE: "attention",
}


def bucket_for(status):
	return BUCKETS.get(status, "attention")


def _display_name(customer):
	first = customer.get("first_name") or ""
	last = customer.get("last_name") or ""
	return f"{first} {last}".strip() or None


def _rejection_reasons(customer):
	"""Rejection reasons come as dicts ({reason, developer_reason, ...}); keep strings."""
	out = []
	for r in customer.get("rejection_reasons") or []:
		if isinstance(r, str):
			out.append(r)
		elif isinstance(r, dict):
			reason = r.get("reason") or r.get("developer_reason")
			if reason:
				out.append(str(reason))
	return list(dict.fromkeys(out))


def _flatten_item(item):
	"""One entry of a `missing` group: a plain string, or a nested object for an
	associated person ({object_type, all_of: [...]})."""
	if isinstance(item, str):
		return [item]
	if isinstance(item, dict):
		label = item.get("object_type") or "associated_person"
		inner = item.get("all_of") or item.get("any_of") or item.get("items") or []
		return [f"{label}: {sub}" for sub in inner if isinstance(sub, str)]
	return []


def flatten_missing(customer):
	"""Union of missing requirements + issues across all endorsements.

	`requirements.missing` is either a group dict ({"all_of": [...]}) or a plain
	list; entries are strings or nested associated-person objects. Returns
	(missing, issues) as order-preserving deduped string lists.
	"""
	missing, issues = [], []
	for endorsement in customer.get("endorsements") or []:
		requirements = endorsement.get("requirements") or {}
		raw = requirements.get("missing")
		groups = []
		if isinstance(raw, dict):
			for val in raw.values():
				if isinstance(val, list):
					groups.extend(val)
		elif isinstance(raw, list):
			groups = raw
		for item in groups:
			missing.extend(_flatten_item(item))
		for issue in requirements.get("issues") or []:
			if isinstance(issue, str):
				issues.append(issue)
	return list(dict.fromkeys(missing)), list(dict.fromkeys(issues))


def _endorsement_summaries(customer):
	out = []
	for endorsement in customer.get("endorsements") or []:
		requirements = endorsement.get("requirements") or {}
		single = {"endorsements": [endorsement]}
		missing, issues = flatten_missing(single)
		out.append(
			{
				"name": endorsement.get("name"),
				"status": endorsement.get("status"),
				"complete_count": len(requirements.get("complete") or []),
				"pending": [p for p in requirements.get("pending") or [] if isinstance(p, str)],
				"missing": missing,
				"issues": issues,
				"additional_requirements": endorsement.get("additional_requirements") or [],
			}
		)
	return out


def build_row(customer, accounts=None):
	"""One overview table row: Bridge truth + the linked Flash account(s).

	More than one account linked to the same customer is a data smell (it has
	happened — duplicate test-account links), so all usernames are carried and
	the UI can flag the sharing instead of silently showing just one.
	"""
	accounts = accounts or []
	first = accounts[0] if accounts else None
	missing, issues = flatten_missing(customer)
	return {
		"customer_id": customer.get("id"),
		"name": _display_name(customer),
		"email": customer.get("email"),
		"type": customer.get("type"),
		"status": customer.get("status") or "unknown",
		"bucket": bucket_for(customer.get("status") or "unknown"),
		"created_at": customer.get("created_at"),
		"updated_at": customer.get("updated_at"),
		"linked": bool(first),
		"username": first.get("username") if first else None,
		"usernames": [a.get("username") or "(no username)" for a in accounts],
		"account_level": first.get("level") if first else None,
		"stored_kyc_status": first.get("bridge_kyc_status") if first else None,
		"requirements_due": [r for r in customer.get("requirements_due") or [] if isinstance(r, str)],
		"missing_count": len(missing),
		"issues_count": len(issues),
		"rejection_reasons": _rejection_reasons(customer),
	}


def build_overview(customers, accounts):
	"""Join Bridge customers to Flash accounts by bridgeCustomerId.

	Customers with no Flash account show as unlinked; accounts whose linked
	customer id is absent from Bridge get a synthetic missing_at_bridge row
	(that is the "modal came back" failure mode — surface it loudly).
	"""
	accounts_by_customer = {}
	for account in accounts:
		accounts_by_customer.setdefault(account["bridge_customer_id"], []).append(account)
	rows = []
	seen = set()
	for customer in customers:
		customer_id = customer.get("id")
		seen.add(customer_id)
		rows.append(build_row(customer, accounts_by_customer.get(customer_id)))

	for account in accounts:
		if account["bridge_customer_id"] in seen:
			continue
		rows.append(
			{
				"customer_id": account["bridge_customer_id"],
				"name": None,
				"email": None,
				"type": None,
				"status": MISSING_AT_BRIDGE,
				"bucket": "attention",
				"created_at": None,
				"updated_at": None,
				"linked": True,
				"username": account.get("username"),
				"usernames": [account.get("username") or "(no username)"],
				"account_level": account.get("level"),
				"stored_kyc_status": account.get("bridge_kyc_status"),
				"requirements_due": [],
				"missing_count": 0,
				"issues_count": 0,
				"rejection_reasons": [],
			}
		)

	rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)

	by_status = {}
	buckets = {"approved": 0, "in_progress": 0, "not_started": 0, "attention": 0}
	linked = 0
	for row in rows:
		by_status[row["status"]] = by_status.get(row["status"], 0) + 1
		buckets[row["bucket"]] = buckets.get(row["bucket"], 0) + 1
		if row["linked"]:
			linked += 1

	return {
		"rows": rows,
		"summary": {
			"total": len(rows),
			"linked": linked,
			"unlinked": len(rows) - linked,
			"by_status": by_status,
			"buckets": buckets,
		},
	}


def build_detail(customer):
	"""Full per-customer drill-down for the detail drawer."""
	row = build_row(customer)
	missing, issues = flatten_missing(customer)
	row.update(
		{
			"missing": missing,
			"issues": issues,
			"endorsements": _endorsement_summaries(customer),
		}
	)
	return row

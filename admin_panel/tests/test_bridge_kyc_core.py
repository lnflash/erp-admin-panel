"""Unit tests for the pure bridge-kyc join/summary logic.

Fixture shapes mirror real prod Bridge responses observed 2026-07-31
(a business customer stuck at awaiting_ubo with an associated-person
requirements object, plus an active individual).
"""

from admin_panel.api.bridge_kyc_core import (
	MISSING_AT_BRIDGE,
	bucket_for,
	build_detail,
	build_overview,
	build_row,
	flatten_missing,
)

BUSINESS_AWAITING_UBO = {
	"id": "27c15fb2-65f4-4f86-ac6d-09e4f487a4df",
	"status": "awaiting_ubo",
	"type": "business",
	"first_name": "Hot Steppa LLC",
	"last_name": None,
	"email": "info@example.com",
	"requirements_due": ["external_account"],
	"rejection_reasons": [],
	"created_at": "2026-07-22T23:42:11.393Z",
	"updated_at": "2026-07-23T00:21:01.704Z",
	"endorsements": [
		{
			"name": "base",
			"status": "incomplete",
			"requirements": {
				"complete": ["terms_of_service_v1", "business_name"],
				"pending": [],
				"missing": {
					"all_of": [
						{
							"object_type": "associated_person",
							"object_id": "e5da8553",
							"all_of": ["tax_identification_number", "government_id_document"],
						},
						"proof_of_nature_of_business_document",
						"kyb_review",
					]
				},
				"issues": ["aiprise_nature_of_business_needs_manual_review"],
			},
		},
		{
			"name": "sepa",
			"status": "incomplete",
			"requirements": {
				"complete": ["terms_of_service_v2"],
				"pending": [],
				# Same items as base — flatten must dedupe across endorsements.
				"missing": {"all_of": ["proof_of_nature_of_business_document", "kyb_review"]},
				"issues": ["aiprise_nature_of_business_needs_manual_review"],
			},
		},
	],
}

ACTIVE_INDIVIDUAL = {
	"id": "2da4a213-0000-0000-0000-000000000000",
	"status": "active",
	"type": "individual",
	"first_name": "Jane",
	"last_name": "Doe",
	"email": "jane@example.com",
	"requirements_due": [],
	"rejection_reasons": [],
	"created_at": "2026-07-01T00:00:00.000Z",
	"updated_at": "2026-07-30T00:00:00.000Z",
	"endorsements": [],
}

REJECTED_INDIVIDUAL = {
	"id": "9e9e9e9e-0000-0000-0000-000000000000",
	"status": "rejected",
	"type": "individual",
	"first_name": "Rick",
	"last_name": None,
	"email": "rick@example.com",
	"requirements_due": [],
	"rejection_reasons": [{"reason": "Document expired", "developer_reason": "id_expired"}],
	"created_at": "2026-07-10T00:00:00.000Z",
	"updated_at": "2026-07-11T00:00:00.000Z",
	"endorsements": [],
}

LINKED_ACCOUNTS = [
	{
		"bridge_customer_id": "27c15fb2-65f4-4f86-ac6d-09e4f487a4df",
		"bridge_kyc_status": "awaiting_ubo",
		"username": "hotsteppa",
		"level": 3,
		"status": "active",
		"created_at": "2024-09-10T16:44:33Z",
	},
	{
		# Orphan: linked customer id that Bridge no longer returns.
		"bridge_customer_id": "dead-beef",
		"bridge_kyc_status": "approved",
		"username": "ghost",
		"level": 2,
		"status": "active",
		"created_at": "2024-01-01T00:00:00Z",
	},
]


def test_flatten_missing_flattens_and_dedupes_across_endorsements():
	missing, issues = flatten_missing(BUSINESS_AWAITING_UBO)
	assert missing == [
		"associated_person: tax_identification_number",
		"associated_person: government_id_document",
		"proof_of_nature_of_business_document",
		"kyb_review",
	]
	# The same issue string appears in both endorsements — must come out once.
	assert issues == ["aiprise_nature_of_business_needs_manual_review"]


def test_flatten_missing_handles_absent_endorsements():
	assert flatten_missing({"endorsements": None}) == ([], [])
	assert flatten_missing({}) == ([], [])


def test_bucket_mapping_and_unknown_status_surfaces_as_attention():
	assert bucket_for("active") == "approved"
	assert bucket_for("awaiting_ubo") == "in_progress"
	assert bucket_for("not_started") == "not_started"
	assert bucket_for("rejected") == "attention"
	assert bucket_for(MISSING_AT_BRIDGE) == "attention"
	# A status we have never seen must be surfaced, never silently hidden.
	assert bucket_for("some_new_bridge_status") == "attention"


def test_build_row_joins_account_and_counts_missing():
	row = build_row(BUSINESS_AWAITING_UBO, [LINKED_ACCOUNTS[0]])
	assert row["name"] == "Hot Steppa LLC"
	assert row["linked"] is True
	assert row["username"] == "hotsteppa"
	assert row["usernames"] == ["hotsteppa"]
	assert row["account_level"] == 3
	assert row["status"] == "awaiting_ubo"
	assert row["bucket"] == "in_progress"
	assert row["missing_count"] == 4
	assert row["issues_count"] == 1
	assert row["requirements_due"] == ["external_account"]


def test_build_row_unlinked_and_rejection_reasons_become_strings():
	row = build_row(REJECTED_INDIVIDUAL)
	assert row["linked"] is False
	assert row["username"] is None
	assert row["rejection_reasons"] == ["Document expired"]


def test_build_overview_joins_orphans_and_tallies():
	customers = [BUSINESS_AWAITING_UBO, ACTIVE_INDIVIDUAL, REJECTED_INDIVIDUAL]
	overview = build_overview(customers, LINKED_ACCOUNTS)
	rows = overview["rows"]
	summary = overview["summary"]

	assert summary["total"] == 4  # 3 Bridge customers + 1 orphaned link
	assert summary["linked"] == 2  # hotsteppa + ghost
	assert summary["unlinked"] == 2  # jane + rick have no Flash account
	assert summary["by_status"] == {
		"awaiting_ubo": 1,
		"active": 1,
		"rejected": 1,
		MISSING_AT_BRIDGE: 1,
	}
	assert summary["buckets"] == {
		"approved": 1,
		"in_progress": 1,
		"not_started": 0,
		"attention": 2,
	}

	orphan = next(r for r in rows if r["status"] == MISSING_AT_BRIDGE)
	assert orphan["username"] == "ghost"
	assert orphan["bucket"] == "attention"
	assert orphan["customer_id"] == "dead-beef"

	# Newest activity first; the orphan (no timestamp) sorts last.
	assert rows[0]["customer_id"] == ACTIVE_INDIVIDUAL["id"]
	assert rows[-1]["customer_id"] == "dead-beef"


def test_shared_customer_link_carries_every_username():
	"""Multiple Flash accounts linked to ONE Bridge customer is a real data
	smell (seen in prod: three test accounts on one customer) — every username
	must surface, never just the first."""
	shared = [
		{
			"bridge_customer_id": ACTIVE_INDIVIDUAL["id"],
			"bridge_kyc_status": "approved",
			"username": "real_user",
			"level": 2,
			"status": "active",
			"created_at": None,
		},
		{
			"bridge_customer_id": ACTIVE_INDIVIDUAL["id"],
			"bridge_kyc_status": "approved",
			"username": "test_dupe",
			"level": 1,
			"status": "active",
			"created_at": None,
		},
	]
	overview = build_overview([ACTIVE_INDIVIDUAL], shared)
	assert overview["summary"]["total"] == 1  # one customer row, not two
	row = overview["rows"][0]
	assert row["username"] == "real_user"
	assert row["usernames"] == ["real_user", "test_dupe"]


def test_linked_account_without_username_gets_placeholder():
	"""Accounts can lack a username; the usernames list feeds tooltips and the
	detail drawer, so None must never leak through as 'null' / blank."""
	acct = {
		"bridge_customer_id": ACTIVE_INDIVIDUAL["id"],
		"bridge_kyc_status": "approved",
		"username": None,
		"level": 1,
		"status": "active",
		"created_at": None,
	}
	row = build_row(ACTIVE_INDIVIDUAL, [acct])
	assert row["usernames"] == ["(no username)"]


def test_build_detail_summarizes_each_endorsement():
	detail = build_detail(BUSINESS_AWAITING_UBO)
	assert detail["missing"][0] == "associated_person: tax_identification_number"
	assert detail["issues"] == ["aiprise_nature_of_business_needs_manual_review"]
	names = [e["name"] for e in detail["endorsements"]]
	assert names == ["base", "sepa"]
	base = detail["endorsements"][0]
	assert base["status"] == "incomplete"
	assert base["complete_count"] == 2
	assert "kyb_review" in base["missing"]
	assert base["issues"] == ["aiprise_nature_of_business_needs_manual_review"]

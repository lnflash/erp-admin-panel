"""after_migrate seeders for Decision Reason and Identity Document Type."""

import ast
from pathlib import Path

from idv_stubs import frappe

from admin_panel.admin_panel import setup
from admin_panel.api import compliance_audit as ledger

SETUP_PY = Path(__file__).resolve().parents[1] / "admin_panel" / "setup.py"

EXPECTED_REASONS = {
	"APPROVE_VERIFIED",
	"APPROVE_BRIDGE_KYC",
	"REJECT_NAME_MISMATCH",
	"REJECT_EXPIRED_DOCUMENT",
	"REJECT_DUPLICATE_DOCUMENT",
	"REJECT_SUSPECTED_FORGERY",
	"REJECT_SANCTIONS_HIT",
	"REJECT_UNSUPPORTED_DOCUMENT",
	"REJECT_OTHER",
	"RESUBMIT_BLURRY",
	"RESUBMIT_GLARE",
	"RESUBMIT_CROPPED",
	"RESUBMIT_WRONG_DOCUMENT",
	"RESUBMIT_SELFIE_MISSING",
}

COUNTRIES = ("Jamaica", "Cayman Islands", "Trinidad and Tobago", "Barbados", "Bahamas", "El Salvador")


def by_code(rows):
	return {r["code"]: r for r in rows}


# ── Decision Reason ─────────────────────────────────────────────────────


def test_decision_reason_seed_is_idempotent(fake):
	fake.autoname["Decision Reason"] = lambda doc: doc.code

	setup.seed_decision_reasons()
	first = [dict(r) for r in fake.rows("Decision Reason")]
	setup.seed_decision_reasons()

	assert len(first) == 14
	assert fake.rows("Decision Reason") == first, "second run must insert nothing"
	assert set(by_code(first)) == EXPECTED_REASONS


def test_every_seeded_reason_is_complete(fake):
	fake.autoname["Decision Reason"] = lambda doc: doc.code
	setup.seed_decision_reasons()

	for code, row in by_code(fake.rows("Decision Reason")).items():
		assert row["name"] == code
		assert row["outcome"] == code.split("_", 1)[0].lower()
		assert row["label"].strip()
		assert row["user_facing_message"].strip(), f"{code} has no user-facing text"
		assert row["active"] == 1
	# Every resubmit message tells the user what to do next.
	for code, row in by_code(fake.rows("Decision Reason")).items():
		if code.startswith("RESUBMIT_"):
			assert "again" in row["user_facing_message"] or "submit" in row["user_facing_message"].lower()


def test_decision_reason_seed_reasserts_outcome_but_keeps_operator_text(fake):
	fake.autoname["Decision Reason"] = lambda doc: doc.code
	setup.seed_decision_reasons()
	row = by_code(fake.rows("Decision Reason"))["REJECT_OTHER"]
	row["outcome"] = "approve"
	row["label"] = "Operator label"
	row["user_facing_message"] = "Operator text"
	row["active"] = 0

	setup.seed_decision_reasons()

	row = by_code(fake.rows("Decision Reason"))["REJECT_OTHER"]
	assert row["outcome"] == "reject"
	assert row["label"] == "Operator label"
	assert row["user_facing_message"] == "Operator text"
	assert row["active"] == 0
	assert len(fake.rows("Decision Reason")) == 14


# ── Identity Document Type ──────────────────────────────────────────────


def test_document_type_seed_is_idempotent_and_skips_missing_countries(fake):
	fake.autoname["Identity Document Type"] = lambda doc: doc.code
	fake.seed("Country", *[{"name": c} for c in COUNTRIES if c != "El Salvador"])

	setup.seed_identity_document_types()
	rows = fake.rows("Identity Document Type")
	codes = set(by_code(rows))

	assert len(setup.IDENTITY_DOCUMENT_TYPES) == 17
	assert len(rows) == 15
	assert "SV_PASSPORT" not in codes and "SV_DUI" not in codes
	assert sum("El Salvador" in w for w in fake.warnings) == 2

	setup.seed_identity_document_types()
	assert len(fake.rows("Identity Document Type")) == 15, "second run must insert nothing"

	# The country arrives later: the next migrate picks the rows up.
	fake.seed("Country", {"name": "El Salvador"})
	setup.seed_identity_document_types()
	assert len(fake.rows("Identity Document Type")) == 17


def test_document_type_seed_never_raises_on_an_empty_country_table(fake):
	fake.autoname["Identity Document Type"] = lambda doc: doc.code
	setup.seed_identity_document_types()
	assert fake.rows("Identity Document Type") == []
	assert len(fake.warnings) == 17


def test_document_type_seed_matches_the_registry_spec(fake):
	fake.autoname["Identity Document Type"] = lambda doc: doc.code
	fake.seed("Country", *[{"name": c} for c in COUNTRIES])
	setup.seed_identity_document_types()
	rows = by_code(fake.rows("Identity Document Type"))

	passports = {code: row for code, row in rows.items() if row["document_name"] == "Passport"}
	assert {row["country"] for row in passports.values()} == set(COUNTRIES)
	for row in passports.values():
		assert row["has_mrz"] == 1 and row["enabled"] == 1 and row["base_confidence"] == 0.9

	jm_dl = rows["JM_DRIVERS_LICENCE"]
	assert jm_dl["country"] == "Jamaica"
	assert (jm_dl["sides"], jm_dl["enabled"], jm_dl["base_confidence"], jm_dl["sample_verified"]) == (
		"2",
		1,
		0.6,
		0,
	)
	assert (rows["JM_VOTER_ID"]["enabled"], rows["JM_VOTER_ID"]["base_confidence"]) == (1, 0.4)
	assert rows["JM_NIDS"]["enabled"] == 0
	assert rows["KY_DRIVERS_LICENCE"]["enabled"] == 0
	assert rows["TT_NATIONAL_ID"]["enabled"] == 0 and rows["TT_DRIVERS_PERMIT"]["enabled"] == 0
	assert rows["BB_NATIONAL_ID"]["enabled"] == 0 and rows["BB_DRIVERS_LICENCE"]["enabled"] == 0
	assert rows["BS_DRIVERS_LICENCE"]["enabled"] == 0 and rows["BS_VOTERS_CARD"]["enabled"] == 0
	assert (rows["SV_DUI"]["enabled"], rows["SV_DUI"]["base_confidence"]) == (1, 0.6)
	for row in rows.values():
		assert row["sides"] in ("1", "2")
		assert 0 <= row["base_confidence"] <= 1
		assert row["sample_verified"] == 0 and row["vendor_extraction"] == 0


def test_document_type_seed_leaves_operator_edits_alone(fake):
	fake.autoname["Identity Document Type"] = lambda doc: doc.code
	fake.seed("Country", *[{"name": c} for c in COUNTRIES])
	setup.seed_identity_document_types()
	by_code(fake.rows("Identity Document Type"))["JM_NIDS"]["enabled"] = 1

	setup.seed_identity_document_types()

	assert by_code(fake.rows("Identity Document Type"))["JM_NIDS"]["enabled"] == 1


# ── wiring ──────────────────────────────────────────────────────────────


def test_after_migrate_runs_both_seeders():
	tree = ast.parse(SETUP_PY.read_text())
	fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "after_migrate")
	calls = [
		node.value.func.id
		for node in fn.body
		if isinstance(node, ast.Expr)
		and isinstance(node.value, ast.Call)
		and isinstance(node.value.func, ast.Name)
	]
	assert "seed_decision_reasons" in calls
	assert "seed_identity_document_types" in calls
	assert "seed_chain_genesis" in calls
	# Countries must exist before document types link to them; both come
	# after the roles the doctypes' permissions reference.
	assert calls.index("ensure_roles") < calls.index("seed_decision_reasons")


# ── Compliance Audit Event chain genesis ─────────────────────────────────
#
# _head_hash() locks the newest ledger row with SELECT ... FOR UPDATE so two
# concurrent writers serialise instead of forking the chain. On a table that
# is genuinely empty that lock has nothing to grab, so the first two
# concurrent writers to a freshly migrated site can both chain onto
# prev_hash=GENESIS. seed_chain_genesis() closes that window by writing one
# real event before any request can reach record_event.


def test_chain_genesis_seed_writes_one_event_on_an_empty_ledger(fake):
	ledger.seed_chain_genesis()

	rows = fake.rows(ledger.DOCTYPE)
	assert len(rows) == 1
	assert rows[0]["event_type"] == "ledger_initialized"
	assert rows[0]["prev_hash"] == "GENESIS"
	assert ledger.verify_chain() == {"ok": True, "checked": 1, "first_bad": None}
	assert ledger.latest_anchor()["count"] == 1


def test_chain_genesis_seed_is_idempotent(fake):
	ledger.seed_chain_genesis()
	first = [dict(r) for r in fake.rows(ledger.DOCTYPE)]

	ledger.seed_chain_genesis()

	assert fake.rows(ledger.DOCTYPE) == first, "second run must insert nothing"


def test_chain_genesis_seed_is_a_noop_once_the_ledger_has_real_history(fake):
	"""A migrate on a site that already has audit events must not touch the
	chain — inserting anything here would no longer be the first row and
	would need a real prev_hash, not the GENESIS sentinel."""
	ledger.record_event("evidence_viewed", "Account Upgrade Request", "AUR-1", {})

	ledger.seed_chain_genesis()

	rows = fake.rows(ledger.DOCTYPE)
	assert len(rows) == 1
	assert rows[0]["event_type"] == "evidence_viewed"

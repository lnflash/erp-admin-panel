"""Contract tests for the ID-verification Phase 0 doctypes and wiring.

Text/JSON-level: every new doctype JSON parses and is shaped the way
``bench migrate``'s sync_all needs; Account Upgrade Request gained its review
stamps; the workspace, dashboard registry, back button and hooks all know the
new destinations; the new endpoints carry the whitelist/role/error stack.
"""

import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
DOCTYPE_DIR = ADMIN_PANEL / "admin_panel" / "doctype"
ADMIN_API = (ADMIN_PANEL / "api" / "admin_api.py").read_text()
HOOKS_PY = (ADMIN_PANEL / "hooks.py").read_text()
WORKSPACE = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())

import sys

if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api import idv_core, nav_core

NEW_DOCTYPES = {
	"ID Verification": "id_verification",
	"Verification Evidence": "verification_evidence",
	"Verification Check": "verification_check",
	"Decision Reason": "decision_reason",
	"Compliance Audit Event": "compliance_audit_event",
	"Identity Document Type": "identity_document_type",
	"ID Verification Settings": "id_verification_settings",
}

LAYOUT_TYPES = ("Section Break", "Column Break", "Tab Break")

# The value on origin/main before this change; bench migrate skips file-syncing
# a doctype whose JSON "modified" is not newer than the DB row's.
AUR_MODIFIED_ON_MAIN = "2026-02-24 07:25:19.018064"


def load(folder):
	return json.loads((DOCTYPE_DIR / folder / f"{folder}.json").read_text())


def fields(folder):
	return {f["fieldname"]: f for f in load(folder)["fields"]}


def options(field):
	return field["options"].split("\n")


def perms_by_role(doctype):
	return {p["role"]: p for p in doctype["permissions"]}


# ── every new doctype ───────────────────────────────────────────────────


@pytest.mark.parametrize("name,folder", sorted(NEW_DOCTYPES.items()))
def test_doctype_json_is_well_formed(name, folder):
	doctype = load(folder)

	assert doctype["doctype"] == "DocType"
	assert doctype["name"] == name
	assert doctype["custom"] == 0
	assert doctype["module"] == "Admin Panel"

	fieldnames = [f["fieldname"] for f in doctype["fields"]]
	assert len(set(fieldnames)) == len(fieldnames), "duplicate fieldname"
	order_message = "field_order must list every field, in order, and nothing else"
	assert fieldnames == doctype["field_order"], order_message
	assert doctype["modified"] >= doctype["creation"]
	assert doctype["modified"] >= "2026-09-01"

	for field in doctype["fields"]:
		if field["fieldtype"] in ("Link", "Table", "Select"):
			assert field.get("options"), f"{name}.{field['fieldname']} needs options"

	assert (DOCTYPE_DIR / folder / "__init__.py").exists()
	controller = (DOCTYPE_DIR / folder / f"{folder}.py").read_text()
	# Frappe derives the controller class from the doctype name with spaces
	# removed; a different class name raises ImportError at load time.
	assert f"class {name.replace(' ', '')}(Document)" in controller


@pytest.mark.parametrize("folder", ["verification_evidence", "verification_check"])
def test_child_tables_are_child_tables(folder):
	doctype = load(folder)
	assert doctype["istable"] == 1
	assert doctype["permissions"] == [], "child tables inherit the parent's permissions"
	assert "autoname" not in doctype


@pytest.mark.parametrize(
	"folder", sorted(set(NEW_DOCTYPES.values()) - {"verification_evidence", "verification_check"})
)
def test_non_child_doctypes_have_no_istable(folder):
	assert not load(folder).get("istable")


# ── ID Verification ─────────────────────────────────────────────────────


def test_id_verification_schema():
	doctype = load("id_verification")
	f = fields("id_verification")

	assert doctype["autoname"] == "format:IDV-{#####}"
	assert doctype["naming_rule"] == "Expression"

	assert f["upgrade_request"]["fieldtype"] == "Link"
	assert f["upgrade_request"]["options"] == "Account Upgrade Request"
	assert f["upgrade_request"]["reqd"] == 1 and f["upgrade_request"]["unique"] == 1

	assert f["username"]["fieldtype"] == "Data" and f["username"]["read_only"] == 1
	assert f["username"]["fetch_from"] == "upgrade_request.username"
	assert f["requested_level"]["fieldtype"] == "Select" and f["requested_level"]["read_only"] == 1
	assert options(f["requested_level"]) == ["ZERO", "ONE", "TWO", "THREE"]
	assert f["requested_level"]["fetch_from"] == "upgrade_request.requested_level"

	assert f["status"]["fieldtype"] == "Select"
	assert options(f["status"]) == list(idv_core.ALLOWED_STATUSES)
	assert options(f["status"]) == [
		"Checks pending",
		"Ready for review",
		"Checks unavailable",
		"Approved",
		"Rejected",
		"Resubmit requested",
	]
	assert f["status"]["default"] == "Checks pending"
	assert f["status"]["in_list_view"] == 1

	assert options(f["identity_source"]) == ["capture", "bridge_kyc"]
	assert f["identity_source"]["default"] == "capture"
	assert f["overall_score"]["fieldtype"] == "Float"
	assert f["report_json"]["fieldtype"] == "Long Text"
	assert f["report_sha256"]["fieldtype"] == "Data"
	assert f["evidence"]["fieldtype"] == "Table" and f["evidence"]["options"] == "Verification Evidence"
	assert f["checks"]["fieldtype"] == "Table" and f["checks"]["options"] == "Verification Check"
	assert f["bridge_customer_id"]["fieldtype"] == "Data"
	assert f["bridge_snapshot_json"]["fieldtype"] == "Long Text"
	assert f["reviewed_by"] == {**f["reviewed_by"], "fieldtype": "Link", "options": "User", "read_only": 1}
	assert f["reviewed_at"]["fieldtype"] == "Datetime" and f["reviewed_at"]["read_only"] == 1
	assert (
		f["decision_reason"]["fieldtype"] == "Link" and f["decision_reason"]["options"] == "Decision Reason"
	)
	assert f["reviewer_note"]["fieldtype"] == "Small Text"
	assert options(f["vendor"]) == ["none", "sumsub", "veriff"] and f["vendor"]["default"] == "none"
	assert f["vendor_applicant_id"]["fieldtype"] == "Data"
	assert f["vendor_verdict"]["fieldtype"] == "Data"


def test_id_verification_permissions():
	perms = perms_by_role(load("id_verification"))
	assert set(perms) == {"System Manager", "Flash Admin"}
	assert all(perms["System Manager"].get(p) == 1 for p in ("create", "read", "write", "delete"))
	flash_admin = perms["Flash Admin"]
	assert all(flash_admin.get(p) == 1 for p in ("create", "read", "write", "report", "export"))
	assert not flash_admin.get("delete")


def test_id_verification_controller_enforces_status_and_reviewer_stamp():
	controller = (DOCTYPE_DIR / "id_verification" / "id_verification.py").read_text()
	assert "if self.status not in ALLOWED_STATUSES:" in controller
	assert "if self.status in DECIDED_STATUSES and not (self.reviewed_by and self.reviewed_at):" in controller
	assert idv_core.DECIDED_STATUSES == ("Approved", "Rejected")


# ── child tables ────────────────────────────────────────────────────────


def test_verification_evidence_schema():
	f = fields("verification_evidence")
	assert f["evidence_type"]["fieldtype"] == "Select" and f["evidence_type"]["reqd"] == 1
	assert options(f["evidence_type"]) == [
		"id_front",
		"id_back",
		"selfie",
		"liveness_frame",
		"business_registration",
		"trn",
		"proof_of_address",
		"bridge_kyc",
	]
	assert (
		f["document_type"]["fieldtype"] == "Link"
		and f["document_type"]["options"] == "Identity Document Type"
	)
	assert f["issuing_country"]["fieldtype"] == "Link" and f["issuing_country"]["options"] == "Country"
	for name in ("file_key", "sha256", "content_type"):
		assert f[name]["fieldtype"] == "Data"
	for name in ("captured_at", "deleted_at"):
		assert f[name]["fieldtype"] == "Datetime"


def test_verification_check_schema():
	f = fields("verification_check")
	assert f["check"]["fieldtype"] == "Data" and f["check"]["reqd"] == 1
	assert f["result"]["fieldtype"] == "Select" and f["result"]["reqd"] == 1
	assert options(f["result"]) == ["pass", "fail", "unknown"]
	assert f["confidence"]["fieldtype"] == "Float"
	assert f["detail"]["fieldtype"] == "Small Text"
	assert f["extracted_value"]["fieldtype"] == "Data"
	assert f["declared_value"]["fieldtype"] == "Data"


# ── Decision Reason ─────────────────────────────────────────────────────


def test_decision_reason_schema():
	doctype = load("decision_reason")
	f = fields("decision_reason")
	assert doctype["autoname"] == "field:code"
	assert f["code"]["fieldtype"] == "Data" and f["code"]["unique"] == 1 and f["code"]["reqd"] == 1
	assert f["outcome"]["fieldtype"] == "Select" and f["outcome"]["reqd"] == 1
	assert options(f["outcome"]) == ["approve", "reject", "resubmit"]
	assert f["label"]["fieldtype"] == "Data" and f["label"]["reqd"] == 1
	assert f["user_facing_message"]["fieldtype"] == "Small Text"
	assert f["active"]["fieldtype"] == "Check" and f["active"]["default"] == "1"
	assert idv_core.DEFAULT_APPROVE_REASON == "APPROVE_VERIFIED"
	assert idv_core.DEFAULT_REJECT_REASON == "REJECT_OTHER"


# ── Compliance Audit Event ──────────────────────────────────────────────


def test_compliance_audit_event_schema():
	f = fields("compliance_audit_event")
	assert f["event_type"]["fieldtype"] == "Data" and f["event_type"]["reqd"] == 1
	assert f["actor"]["fieldtype"] == "Data" and f["actor"]["reqd"] == 1
	assert f["reference_doctype"]["fieldtype"] == "Data"
	assert f["reference_name"]["fieldtype"] == "Data"
	assert f["payload_json"]["fieldtype"] == "Long Text"
	for name in ("payload_sha256", "prev_hash", "hash"):
		assert f[name]["fieldtype"] == "Data"
	assert f["hash"]["unique"] == 1
	assert f["created_at"]["fieldtype"] == "Datetime" and f["created_at"]["reqd"] == 1
	assert load("compliance_audit_event")["track_changes"] == 0


def test_compliance_audit_event_is_read_only_for_every_role():
	doctype = load("compliance_audit_event")
	perms = perms_by_role(doctype)
	assert set(perms) == {"System Manager", "Accounts Manager", "Flash Admin"}
	for role, perm in perms.items():
		assert perm.get("read") == 1, f"{role} must be able to read the ledger"
		for verb in ("write", "delete", "cancel", "amend", "create", "submit"):
			assert not perm.get(verb), f"{role} must not hold {verb} on the ledger"
	assert not doctype.get("is_submittable")


def test_compliance_audit_event_controller_is_append_only():
	controller = (DOCTYPE_DIR / "compliance_audit_event" / "compliance_audit_event.py").read_text()
	assert "def before_save(self):" in controller and "if not self.is_new():" in controller
	assert "def on_trash(self):" in controller
	assert controller.count("frappe.throw(APPEND_ONLY_MESSAGE)") == 2


# ── Identity Document Type ──────────────────────────────────────────────


def test_identity_document_type_schema():
	doctype = load("identity_document_type")
	f = fields("identity_document_type")
	assert doctype["autoname"] == "field:code"
	assert f["code"]["fieldtype"] == "Data" and f["code"]["unique"] == 1 and f["code"]["reqd"] == 1
	assert (
		f["country"]["fieldtype"] == "Link"
		and f["country"]["options"] == "Country"
		and f["country"]["reqd"] == 1
	)
	assert f["document_name"]["fieldtype"] == "Data" and f["document_name"]["reqd"] == 1
	assert f["has_mrz"]["fieldtype"] == "Check"
	assert (
		f["sides"]["fieldtype"] == "Select"
		and options(f["sides"]) == ["1", "2"]
		and f["sides"]["default"] == "1"
	)
	assert f["template_keywords"]["fieldtype"] == "Small Text"
	assert f["base_confidence"]["fieldtype"] == "Float" and f["base_confidence"]["default"] == "0.5"
	for name in ("enabled", "sample_verified", "vendor_extraction"):
		assert f[name]["fieldtype"] == "Check"


# ── ID Verification Settings ────────────────────────────────────────────


def test_id_verification_settings_is_a_single_with_defaults():
	doctype = load("id_verification_settings")
	f = fields("id_verification_settings")
	assert doctype["issingle"] == 1
	assert f["auto_approve_enabled"]["fieldtype"] == "Check" and f["auto_approve_enabled"]["default"] == "0"
	assert f["auto_approve_levels"]["fieldtype"] == "Data" and f["auto_approve_levels"]["default"] == "TWO"
	assert (
		f["auto_approve_min_score"]["fieldtype"] == "Float"
		and f["auto_approve_min_score"]["default"] == "0.9"
	)
	assert f["auto_approve_sampling_percent"]["fieldtype"] == "Int"
	assert f["auto_approve_sampling_percent"]["default"] == "10"
	assert f["bridge_kyc_satisfies_identity"]["fieldtype"] == "Check"
	assert f["bridge_kyc_satisfies_identity"]["default"] == "1"
	assert f["retention_years"]["fieldtype"] == "Int" and f["retention_years"]["default"] == "7"
	assert f["idv_service_url"]["fieldtype"] == "Data"

	perms = perms_by_role(doctype)
	assert set(perms) == {"System Manager", "Flash Admin"}
	for perm in perms.values():
		assert perm.get("read") == 1 and perm.get("write") == 1


# ── Account Upgrade Request ─────────────────────────────────────────────


def test_account_upgrade_request_gained_the_review_stamps():
	doctype = load("account_upgrade_request")
	f = fields("account_upgrade_request")

	assert f["reviewed_by"]["fieldtype"] == "Link" and f["reviewed_by"]["options"] == "User"
	assert f["reviewed_by"]["read_only"] == 1
	assert f["reviewed_at"]["fieldtype"] == "Datetime" and f["reviewed_at"]["read_only"] == 1
	assert (
		f["decision_reason"]["fieldtype"] == "Link" and f["decision_reason"]["options"] == "Decision Reason"
	)

	order = doctype["field_order"]
	at = order.index("support_note")
	assert order[at + 1 : at + 4] == ["reviewed_by", "reviewed_at", "decision_reason"]
	assert [x["fieldname"] for x in doctype["fields"]] == order

	assert doctype["modified"] > AUR_MODIFIED_ON_MAIN, (
		"account_upgrade_request.json changed without bumping 'modified' — "
		"bench migrate will skip file-syncing it on existing sites"
	)


# ── workspace / dashboard / back button / hooks ─────────────────────────

COMPLIANCE_LINKS = (
	"ID Verification",
	"Identity Document Type",
	"ID Verification Settings",
	"Compliance Audit Event",
)


def compliance_card_links():
	links = WORKSPACE["links"]
	start = next(
		i for i, row in enumerate(links) if row["type"] == "Card Break" and row["label"] == "Compliance"
	)
	card = []
	for row in links[start + 1 :]:
		if row["type"] == "Card Break":
			break
		card.append(row)
	return links[start], card


def test_workspace_lists_the_new_doctypes_under_compliance():
	card_break, card = compliance_card_links()
	labels = [row["label"] for row in card]

	for label in COMPLIANCE_LINKS:
		assert label in labels, f"{label} missing from the Compliance card"
		row = card[labels.index(label)]
		assert row["link_type"] == "DocType" and row["link_to"] == label
		assert row["type"] == "Link" and row["hidden"] == 0
		assert row["parent"] == "Admin Panel" and row["parentfield"] == "links"
		assert row["description"]
	# Existing entries keep their place ahead of the new ones.
	assert labels[:3] == ["Bridge KYC", "Allowed Country", "System Watchlist"]
	assert card_break["link_count"] == len(card) == 7


def test_workspace_link_rows_share_one_shape():
	_, card = compliance_card_links()
	reference = set(next(row for row in card if row["label"] == "Allowed Country"))
	for row in card:
		assert set(row) == reference, f"{row['label']} has a different key set from the Allowed Country entry"


def test_dashboard_registry_lists_the_new_doctypes_under_compliance():
	compliance = next(g for g in nav_core.NAV_GROUPS if g["title"] == "Compliance")
	doctypes = [link["doctype"] for link in compliance["links"] if link["kind"] == "doctype"]
	assert doctypes[-4:] == list(COMPLIANCE_LINKS)
	for link in compliance["links"]:
		if link.get("doctype") in COMPLIANCE_LINKS:
			assert len(link["badge"]) == 2 and link["desc"]
	# Sidebar descriptions and tile descriptions must not drift apart.
	_, card = compliance_card_links()
	by_label = {row["label"]: row["description"] for row in card}
	for link in compliance["links"]:
		if link.get("doctype") in COMPLIANCE_LINKS:
			assert by_label[link["doctype"]] == link["desc"]


def test_doctypes_without_a_tile_are_explicitly_unlisted():
	for route in ("decision-reason", "verification-evidence", "verification-check"):
		assert nav_core.UNLISTED.get(route)


def test_hooks_enable_the_daily_anchor_only():
	tree = ast.parse(HOOKS_PY)
	assign = next(
		n
		for n in ast.walk(tree)
		if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "scheduler_events" for t in n.targets)
	)
	events = ast.literal_eval(assign.value)
	assert events == {"daily": ["admin_panel.api.compliance_audit.post_daily_anchor"]}
	assert "scheduler worker" in HOOKS_PY


def test_scheduler_target_exists_and_is_not_an_endpoint():
	source = (ADMIN_PANEL / "api" / "compliance_audit.py").read_text()
	assert "\ndef post_daily_anchor():" in source
	assert "@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef post_daily_anchor(" not in source


# ── endpoints ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
	"signature",
	[
		"approve_upgrade_request(request_id, reason_code=None)",
		"reject_upgrade_request(request_id, reason=None, reason_code=None)",
		"request_resubmission(request_id, reason_code, note=None)",
		"get_id_verification(request_id)",
		"get_idv_settings()",
		"get_id_document_url(file_key)",
	],
)
def test_decision_endpoints_are_whitelisted_and_admin_gated(signature):
	stack = f"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef {signature}:"
	assert stack in ADMIN_API, f"{signature} is missing the whitelist/require_admin/handle_api_errors stack"


def test_approve_and_reject_still_write_the_legacy_comment_audit():
	assert ADMIN_API.count('audit_log(\n\t\t"approve_upgrade",') == 1
	assert '"reject_upgrade", "Account Upgrade Request", request_id' in ADMIN_API


def test_approve_keeps_erp_and_level_update_logic():
	approve = ADMIN_API[
		ADMIN_API.index("def approve_upgrade_request(") : ADMIN_API.index("def reject_upgrade_request(")
	]
	assert "erp_errors, erp_party = _create_erp_records(req)" in approve
	assert 'if req.requested_level in ("TWO", "THREE"):' in approve
	assert "client.update_account_level(" in approve
	# Reason validation happens before the flash lookup, never after.
	assert approve.index('_decision_reason(reason_code, "approve")') < approve.index(
		"client.get_account_by_phone"
	)


def test_get_id_document_url_ledgers_every_successful_mint():
	block = ADMIN_API[
		ADMIN_API.index("def get_id_document_url(") : ADMIN_API.index("def _upgrade_request_for_file_key(")
	]
	assert 'return {"success": False, "error": "No read URL returned"}' in block
	assert '"evidence_viewed"' in block
	assert block.index('"evidence_viewed"') > block.index("No read URL returned")
	assert block.index('"evidence_viewed"') < block.index('return {"success": True, "url": url}')


# ── docs ────────────────────────────────────────────────────────────────


def test_phase0_plan_and_readme_are_written():
	plan = REPO_ROOT / "docs" / "plans" / "2026-09-01-id-verification-phase0.md"
	assert plan.exists()
	text = plan.read_text()
	for needle in ("Compliance Audit Event", "verify_chain", "GENESIS", "request_resubmission", "flash-idv"):
		assert needle in text
	readme = (REPO_ROOT / "README.md").read_text()
	assert "ID Verification" in readme and "Compliance Audit Event" in readme

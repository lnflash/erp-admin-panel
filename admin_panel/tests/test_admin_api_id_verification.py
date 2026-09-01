"""Behavioral tests for the reviewer-decision endpoints (admin_api).

approve / reject / request_resubmission must stamp the decision on the
Account Upgrade Request, mirror it onto the request's ID Verification and
write the matching ledger event — with the reason code validated BEFORE any
call to flash, so a bad code can never leave flash upgraded and the local
request un-decided.
"""

import types

import pytest
from idv_stubs import frappe

from admin_panel.api import admin_api

REQUEST = "AUR-0001"

REASONS = (
	("APPROVE_VERIFIED", "approve", "Identity verified", "You are verified."),
	("APPROVE_BRIDGE_KYC", "approve", "Verified via Bridge KYC", "Verified via KYC."),
	("REJECT_OTHER", "reject", "Other", "We could not approve your upgrade."),
	("REJECT_NAME_MISMATCH", "reject", "Name does not match", "Fix your name and try again."),
	("RESUBMIT_BLURRY", "resubmit", "Photo too blurry", "Retake the photo in good light."),
)


@pytest.fixture()
def env(fake, monkeypatch):
	fake.seed(
		"Decision Reason",
		*[
			{"name": code, "code": code, "outcome": outcome, "label": label, "user_facing_message": msg}
			for code, outcome, label, msg in REASONS
		],
	)
	fake.seed(
		"Account Upgrade Request",
		{
			"name": REQUEST,
			"status": "Pending",
			"username": "alice",
			"requested_level": "TWO",
			"phone_number": "+18765550100",
			"id_document": "kyc/alice.jpg",
			"support_note": None,
		},
	)
	counter = {"n": 0}

	def idv_name(doc):
		counter["n"] += 1
		return f"IDV-{counter['n']:05d}"

	fake.autoname["ID Verification"] = idv_name

	graphql = types.SimpleNamespace(lookups=[], level_updates=[], account={"id": "uid-1"}, result={})

	class StubClient:
		def get_account_by_phone(self, phone):
			graphql.lookups.append(phone)
			return graphql.account

		def update_account_level(self, uid, level, erp_party=None):
			graphql.level_updates.append((uid, level, erp_party))
			return graphql.result

	events = []
	audits = []
	erp = []
	monkeypatch.setattr(admin_api, "GraphQLClient", StubClient)
	monkeypatch.setattr(
		admin_api, "_create_erp_records", lambda req: (erp.append(req.name), ([], "CUST-1"))[1]
	)
	monkeypatch.setattr(admin_api, "record_event", lambda *args: events.append(args))
	monkeypatch.setattr(admin_api, "audit_log", lambda *args: audits.append(args))
	return types.SimpleNamespace(fake=fake, graphql=graphql, events=events, audits=audits, erp=erp)


def request_row(env):
	return next(r for r in env.fake.rows("Account Upgrade Request") if r["name"] == REQUEST)


def idv_rows(env):
	return env.fake.rows("ID Verification")


# ── approve ─────────────────────────────────────────────────────────────


def test_approve_stamps_decision_mirrors_idv_and_records_event(env):
	result = admin_api.approve_upgrade_request(REQUEST)

	assert result["success"] is True
	assert env.graphql.lookups == ["+18765550100"]
	assert env.graphql.level_updates == [("uid-1", "TWO", "CUST-1")]
	assert env.erp == [REQUEST]

	req = request_row(env)
	assert req["status"] == "Approved"
	assert req["reviewed_by"] == "reviewer@getflash.io"
	assert req["reviewed_at"] and req["reviewed_at"].startswith("2026-09-01 12:00:00")
	assert req["decision_reason"] == "APPROVE_VERIFIED"

	assert len(idv_rows(env)) == 1
	idv = idv_rows(env)[0]
	assert idv["upgrade_request"] == REQUEST
	assert idv["username"] == "alice" and idv["requested_level"] == "TWO"
	assert idv["status"] == "Approved"
	assert idv["reviewed_by"] == "reviewer@getflash.io"
	assert idv["reviewed_at"] == req["reviewed_at"]
	assert idv["decision_reason"] == "APPROVE_VERIFIED"

	assert env.events == [
		(
			"upgrade_approved",
			"Account Upgrade Request",
			REQUEST,
			{
				"username": "alice",
				"requested_level": "TWO",
				"decision_reason": "APPROVE_VERIFIED",
				"id_verification": idv["name"],
				"evidence_sha256": [],
			},
		)
	]
	# The legacy Comment audit stays alongside the ledger.
	assert [a[0] for a in env.audits] == ["approve_upgrade"]
	assert env.fake.commits >= 1


def test_approve_accepts_an_explicit_approve_reason(env):
	assert admin_api.approve_upgrade_request(REQUEST, reason_code="APPROVE_BRIDGE_KYC")["success"] is True
	assert request_row(env)["decision_reason"] == "APPROVE_BRIDGE_KYC"
	assert idv_rows(env)[0]["decision_reason"] == "APPROVE_BRIDGE_KYC"
	assert env.events[0][3]["decision_reason"] == "APPROVE_BRIDGE_KYC"


def test_approve_rejects_a_non_approve_reason_before_touching_flash(env):
	result = admin_api.approve_upgrade_request(REQUEST, reason_code="REJECT_OTHER")

	assert result["success"] is False
	assert "reject reason, not approve" in result["error"]
	assert env.fake.response["http_status_code"] == 400
	assert env.graphql.lookups == [] and env.graphql.level_updates == []
	assert request_row(env)["status"] == "Pending"
	assert env.events == [] and idv_rows(env) == []


def test_approve_rejects_an_unknown_reason_code(env):
	result = admin_api.approve_upgrade_request(REQUEST, reason_code="NOPE")

	assert result == {"success": False, "error": "Unknown decision reason 'NOPE'"}
	assert env.fake.response["http_status_code"] == 400
	assert env.graphql.level_updates == []


def test_approve_refuses_a_request_that_is_not_pending(env):
	request_row(env)["status"] = "Rejected"

	result = admin_api.approve_upgrade_request(REQUEST)

	assert result == {"success": False, "error": "Request has already been rejected"}
	assert env.events == [] and env.graphql.lookups == []


def test_approve_does_not_stamp_when_flash_refuses(env):
	env.graphql.result = {"errors": [{"message": "level locked"}]}

	result = admin_api.approve_upgrade_request(REQUEST)

	assert result == {"success": False, "errors": ["level locked"]}
	req = request_row(env)
	assert req["status"] == "Pending" and req.get("reviewed_by") is None
	assert env.events == [] and idv_rows(env) == []


def test_approve_reuses_an_existing_id_verification_and_ledgers_its_evidence(env):
	env.fake.seed(
		"ID Verification",
		{
			"name": "IDV-00042",
			"upgrade_request": REQUEST,
			"status": "Ready for review",
			"evidence": [
				types.SimpleNamespace(evidence_type="id_front", sha256="aaa"),
				types.SimpleNamespace(evidence_type="selfie", sha256="bbb"),
				types.SimpleNamespace(evidence_type="id_back", sha256=None),
			],
		},
	)

	admin_api.approve_upgrade_request(REQUEST)

	assert [r["name"] for r in idv_rows(env)] == ["IDV-00042"]
	assert idv_rows(env)[0]["status"] == "Approved"
	assert env.events[0][3]["id_verification"] == "IDV-00042"
	assert env.events[0][3]["evidence_sha256"] == ["aaa", "bbb"]


# ── reject ──────────────────────────────────────────────────────────────


def test_reject_stamps_decision_mirrors_idv_and_records_event(env):
	result = admin_api.reject_upgrade_request(REQUEST, reason="ID photo is of someone else")

	assert result == {"success": True, "message": "Request rejected."}
	assert env.graphql.lookups == [] and env.graphql.level_updates == []

	req = request_row(env)
	assert req["status"] == "Rejected"
	assert req["support_note"] == "ID photo is of someone else"
	assert req["reviewed_by"] == "reviewer@getflash.io"
	assert req["reviewed_at"]
	assert req["decision_reason"] == "REJECT_OTHER"

	idv = idv_rows(env)[0]
	assert idv["status"] == "Rejected"
	assert idv["reviewed_by"] == "reviewer@getflash.io"
	assert idv["reviewed_at"] == req["reviewed_at"]
	assert idv["decision_reason"] == "REJECT_OTHER"
	assert idv["reviewer_note"] == "ID photo is of someone else"

	assert env.events == [
		(
			"upgrade_rejected",
			"Account Upgrade Request",
			REQUEST,
			{
				"username": "alice",
				"requested_level": "TWO",
				"decision_reason": "REJECT_OTHER",
				"id_verification": idv["name"],
				"evidence_sha256": [],
				"reason": "ID photo is of someone else",
			},
		)
	]
	assert [a[0] for a in env.audits] == ["reject_upgrade"]


def test_reject_without_a_reason_records_the_placeholder(env):
	admin_api.reject_upgrade_request(REQUEST)

	assert request_row(env)["support_note"] == "No reason provided"
	assert env.events[0][3]["reason"] == "No reason provided"


def test_reject_accepts_an_explicit_reject_reason(env):
	admin_api.reject_upgrade_request(REQUEST, reason="name", reason_code="REJECT_NAME_MISMATCH")

	assert request_row(env)["decision_reason"] == "REJECT_NAME_MISMATCH"
	assert idv_rows(env)[0]["decision_reason"] == "REJECT_NAME_MISMATCH"


def test_reject_refuses_a_non_reject_reason(env):
	result = admin_api.reject_upgrade_request(REQUEST, reason_code="APPROVE_VERIFIED")

	assert result["success"] is False and "approve reason, not reject" in result["error"]
	assert env.fake.response["http_status_code"] == 400
	assert request_row(env)["status"] == "Pending"
	assert env.events == []


def test_reject_refuses_a_request_that_is_not_pending(env):
	request_row(env)["status"] = "Approved"

	assert admin_api.reject_upgrade_request(REQUEST) == {
		"success": False,
		"error": "Request has already been approved",
	}
	assert env.events == []


# ── request_resubmission ────────────────────────────────────────────────


def test_request_resubmission_leaves_the_request_pending_and_flags_the_idv(env):
	result = admin_api.request_resubmission(REQUEST, "RESUBMIT_BLURRY", note="front of ID unreadable")

	assert result == {
		"success": True,
		"message": "Resubmission requested.",
		"user_facing_message": "Retake the photo in good light.",
	}

	req = request_row(env)
	assert req["status"] == "Pending"
	assert req.get("reviewed_by") is None and req.get("decision_reason") is None
	assert req["support_note"] == (
		"Resubmission requested (RESUBMIT_BLURRY): Retake the photo in good light. — front of ID unreadable"
	)

	idv = idv_rows(env)[0]
	assert idv["status"] == "Resubmit requested"
	assert idv["decision_reason"] == "RESUBMIT_BLURRY"
	assert idv["reviewer_note"] == "front of ID unreadable"
	assert idv.get("reviewed_by") is None, "a resubmission ask is not a decision"

	assert env.events == [
		(
			"resubmission_requested",
			"Account Upgrade Request",
			REQUEST,
			{
				"username": "alice",
				"requested_level": "TWO",
				"decision_reason": "RESUBMIT_BLURRY",
				"note": "front of ID unreadable",
				"id_verification": idv["name"],
			},
		)
	]
	assert [a[0] for a in env.audits] == ["request_resubmission"]


def test_request_resubmission_without_a_note(env):
	admin_api.request_resubmission(REQUEST, "RESUBMIT_BLURRY")
	assert request_row(env)["support_note"] == (
		"Resubmission requested (RESUBMIT_BLURRY): Retake the photo in good light."
	)
	assert idv_rows(env)[0].get("reviewer_note") is None


def test_request_resubmission_rejects_a_non_resubmit_reason(env):
	result = admin_api.request_resubmission(REQUEST, "REJECT_OTHER")

	assert result["success"] is False and "reject reason, not resubmit" in result["error"]
	assert env.fake.response["http_status_code"] == 400
	assert idv_rows(env) == [] and env.events == []
	assert request_row(env)["support_note"] is None


def test_request_resubmission_rejects_an_unknown_reason(env):
	result = admin_api.request_resubmission(REQUEST, "NOPE")
	assert result == {"success": False, "error": "Unknown decision reason 'NOPE'"}
	assert env.fake.response["http_status_code"] == 400


def test_request_resubmission_requires_a_reason_code(env):
	result = admin_api.request_resubmission(REQUEST, "")
	assert result == {"success": False, "error": "reason_code is required"}
	assert env.fake.response["http_status_code"] == 400


def test_request_resubmission_refuses_a_request_that_is_not_pending(env):
	request_row(env)["status"] = "Approved"

	result = admin_api.request_resubmission(REQUEST, "RESUBMIT_BLURRY")

	assert result == {"success": False, "error": "Request has already been approved"}
	assert env.fake.response["http_status_code"] == 400
	assert env.events == []


# ── reads + helper ──────────────────────────────────────────────────────


def test_get_id_verification_is_none_until_one_exists(env):
	assert admin_api.get_id_verification(REQUEST) is None

	admin_api.request_resubmission(REQUEST, "RESUBMIT_BLURRY")
	found = admin_api.get_id_verification(REQUEST)

	assert found["upgrade_request"] == REQUEST
	assert found["status"] == "Resubmit requested"


def test_get_idv_settings_returns_exactly_the_tunable_fields(env):
	from admin_panel.api.idv_core import SETTINGS_FIELDS

	env.fake.singles["ID Verification Settings"] = {
		"doctype": "ID Verification Settings",
		"name": "ID Verification Settings",
		"auto_approve_enabled": 1,
		"auto_approve_levels": "TWO,THREE",
		"auto_approve_min_score": 0.95,
		"auto_approve_sampling_percent": 5,
		"bridge_kyc_satisfies_identity": 0,
		"retention_years": 7,
		"idv_service_url": "http://idv:8080",
		"modified_by": "not-a-setting",
	}

	settings = admin_api.get_idv_settings()

	assert set(settings) == {name for name, _ in SETTINGS_FIELDS}
	assert settings["auto_approve_levels"] == "TWO,THREE"
	assert settings["idv_service_url"] == "http://idv:8080"


def test_get_or_create_id_verification_is_idempotent(env):
	req = frappe.get_doc("Account Upgrade Request", REQUEST)

	first = admin_api.get_or_create_id_verification(req)
	second = admin_api.get_or_create_id_verification(req)

	assert first.name == second.name
	assert len(idv_rows(env)) == 1
	assert idv_rows(env)[0]["username"] == "alice"


def test_helper_is_not_an_endpoint():
	from pathlib import Path

	source = (Path(__file__).resolve().parents[1] / "api" / "admin_api.py").read_text()
	before = source[: source.index("\ndef get_or_create_id_verification(")]
	assert not before.rstrip().endswith("@handle_api_errors")
	assert (
		"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef get_or_create_id_verification("
		not in source
	)

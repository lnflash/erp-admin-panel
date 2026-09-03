"""Behavioral tests for the append-only, hash-chained compliance ledger.

Runs against ``idv_stubs.FakeFrappe`` — an in-memory frappe with real
ordering semantics — so the chain is exercised over rows that were actually
appended, read back in created order, tampered with, and re-verified.
"""

import types

import pytest
from idv_stubs import Thrown, frappe

from admin_panel.admin_panel.doctype.compliance_audit_event.compliance_audit_event import (
	ComplianceAuditEvent,
)
from admin_panel.api import compliance_audit as ledger

DOCTYPE = ledger.DOCTYPE
REF = "Account Upgrade Request"


def record_three(fake):
	return [ledger.record_event(f"event_{i}", REF, f"AUR-{i}", {"i": i, "who": "alice"}) for i in range(3)]


# ── canonical form ──────────────────────────────────────────────────────


def test_canonical_json_is_key_order_independent():
	a = ledger.canonical_json({"b": 1, "a": {"y": 2, "x": [1, 2]}})
	b = ledger.canonical_json({"a": {"x": [1, 2], "y": 2}, "b": 1})

	assert a == b == '{"a":{"x":[1,2],"y":2},"b":1}'
	assert ledger.sha256_hex(a) == ledger.sha256_hex(b)


def test_canonical_json_keeps_unicode_and_treats_none_as_empty():
	assert ledger.canonical_json({"name": "José"}) == '{"name":"José"}'
	assert ledger.canonical_json(None) == "{}"


def test_created_at_hashes_identically_as_datetime_and_as_string():
	"""Frappe hands created_at back as a datetime; the writer had a datetime
	too, but any string form of the same instant must hash the same."""
	from datetime import datetime

	instant = datetime(2026, 9, 1, 12, 0, 0, 123456)
	args = ("GENESIS", "e", "u", REF, "AUR-1", "abc")

	assert ledger.compute_hash(*args, instant) == ledger.compute_hash(*args, "2026-09-01 12:00:00.123456")
	assert ledger.compute_hash(*args, instant) == ledger.compute_hash(*args, "2026-09-01T12:00:00.123456")


def test_none_reference_fields_hash_like_empty_strings():
	"""Written as None, read back as NULL → None: must verify either way."""
	assert ledger.compute_hash(
		"GENESIS", "e", "u", None, None, "p", "2026-09-01 12:00:00"
	) == ledger.compute_hash("GENESIS", "e", "u", "", "", "p", "2026-09-01 12:00:00")


# ── writing ─────────────────────────────────────────────────────────────


def test_first_row_chains_onto_genesis(fake):
	row_hash = ledger.record_event("evidence_viewed", REF, "AUR-1", {"file_key": "kyc/a.jpg"})

	rows = fake.rows(DOCTYPE)
	assert len(rows) == 1
	row = rows[0]
	assert row["prev_hash"] == "GENESIS"
	assert row["hash"] == row_hash
	assert row["event_type"] == "evidence_viewed"
	assert row["actor"] == "reviewer@getflash.io"
	assert row["reference_doctype"] == REF
	assert row["reference_name"] == "AUR-1"
	assert row["payload_json"] == '{"file_key":"kyc/a.jpg"}'
	assert row["payload_sha256"] == ledger.sha256_hex('{"file_key":"kyc/a.jpg"}')
	assert row["created_at"] == fake.clock
	assert row["hash"] == ledger.compute_hash(
		"GENESIS",
		"evidence_viewed",
		"reviewer@getflash.io",
		REF,
		"AUR-1",
		row["payload_sha256"],
		row["created_at"],
	)


def test_each_row_chains_onto_the_previous_hash(fake):
	hashes = record_three(fake)

	rows = fake.rows(DOCTYPE)
	assert [r["prev_hash"] for r in rows] == ["GENESIS", hashes[0], hashes[1]]
	assert [r["hash"] for r in rows] == hashes
	assert len(set(hashes)) == 3


def test_reference_name_is_stored_as_a_string(fake):
	ledger.record_event("e", REF, 42, {})
	assert fake.rows(DOCTYPE)[0]["reference_name"] == "42"


def test_record_event_requires_an_event_type(fake):
	with pytest.raises(ValueError):
		ledger.record_event("", REF, "AUR-1", {})
	assert fake.rows(DOCTYPE) == []


def test_record_event_inserts_with_ignore_permissions(fake):
	"""Nobody holds create on the ledger doctype (the JSON contract test pins
	that), so the only way a row can land is ignore_permissions=True — the
	fake raises PermissionError otherwise."""
	ledger.record_event("e", REF, "AUR-1", {})
	assert len(fake.rows(DOCTYPE)) == 1


def test_head_is_read_for_update(fake, monkeypatch):
	calls = []
	real = fake.get_value

	def spy(doctype, *args, **kwargs):
		calls.append((doctype, args, kwargs))
		return real(doctype, *args, **kwargs)

	monkeypatch.setattr(frappe.db, "get_value", spy)
	ledger.record_event("e", REF, "AUR-1", {})

	head_reads = [c for c in calls if c[0] == DOCTYPE]
	assert len(head_reads) == 1
	assert head_reads[0][2]["for_update"] is True
	assert head_reads[0][2]["order_by"] == ledger.HEAD_ORDER


def test_head_read_falls_back_when_for_update_is_unsupported(fake, monkeypatch):
	real = fake.get_value

	def old_frappe(doctype, *args, **kwargs):
		if "for_update" in kwargs:
			raise TypeError("unexpected keyword argument 'for_update'")
		return real(doctype, *args, **kwargs)

	monkeypatch.setattr(frappe.db, "get_value", old_frappe)
	hashes = record_three(fake)

	assert [r["prev_hash"] for r in fake.rows(DOCTYPE)] == ["GENESIS", hashes[0], hashes[1]]
	assert ledger.verify_chain()["ok"] is True


# ── verifying ───────────────────────────────────────────────────────────


def test_three_events_verify(fake):
	record_three(fake)
	assert ledger.verify_chain() == {"ok": True, "checked": 3, "first_bad": None}


def test_empty_ledger_verifies(fake):
	assert ledger.verify_chain() == {"ok": True, "checked": 0, "first_bad": None}


def test_tampered_middle_payload_is_the_first_bad_row(fake):
	record_three(fake)
	rows = fake.rows(DOCTYPE)
	rows[1]["payload_json"] = '{"i":99,"who":"alice"}'

	assert ledger.verify_chain() == {"ok": False, "checked": 1, "first_bad": rows[1]["name"]}


def test_reformatted_but_unchanged_payload_still_verifies(fake):
	"""A tool that pretty-prints the stored JSON is not a tamper."""
	record_three(fake)
	rows = fake.rows(DOCTYPE)
	rows[1]["payload_json"] = '{ "who": "alice", "i": 1 }'

	assert ledger.verify_chain()["ok"] is True


def test_consistently_rewritten_row_breaks_the_next_link(fake):
	"""An attacker who rewrites payload, payload_sha256 AND hash of one row
	so that row verifies in isolation still breaks the row after it."""
	record_three(fake)
	rows = fake.rows(DOCTYPE)
	row = rows[1]
	row["payload_json"] = '{"i":99,"who":"alice"}'
	row["payload_sha256"] = ledger.sha256_hex(row["payload_json"])
	row["hash"] = ledger.compute_hash(
		row["prev_hash"],
		row["event_type"],
		row["actor"],
		row["reference_doctype"],
		row["reference_name"],
		row["payload_sha256"],
		row["created_at"],
	)

	assert ledger.verify_chain() == {"ok": False, "checked": 2, "first_bad": rows[2]["name"]}


def test_deleted_row_breaks_the_chain(fake):
	record_three(fake)
	rows = fake.rows(DOCTYPE)
	removed = rows.pop(1)

	result = ledger.verify_chain()
	assert result["ok"] is False
	assert result["checked"] == 1
	assert result["first_bad"] == rows[1]["name"] != removed["name"]


def test_tampered_actor_is_detected(fake):
	record_three(fake)
	fake.rows(DOCTYPE)[0]["actor"] = "someone-else"
	assert ledger.verify_chain()["first_bad"] == fake.rows(DOCTYPE)[0]["name"]


def test_unparsable_payload_is_bad(fake):
	record_three(fake)
	fake.rows(DOCTYPE)[2]["payload_json"] = "not json"
	assert ledger.verify_chain() == {"ok": False, "checked": 2, "first_bad": fake.rows(DOCTYPE)[2]["name"]}


def test_verify_chain_honours_limit(fake):
	record_three(fake)
	fake.rows(DOCTYPE)[2]["payload_json"] = "{}"

	assert ledger.verify_chain(limit=2) == {"ok": True, "checked": 2, "first_bad": None}
	assert ledger.verify_chain()["ok"] is False


# ── anchor ──────────────────────────────────────────────────────────────


def test_latest_anchor_on_empty_ledger(fake):
	assert ledger.latest_anchor() == {"hash": "GENESIS", "created_at": None, "count": 0}


def test_latest_anchor_is_the_newest_row(fake):
	hashes = record_three(fake)
	anchor = ledger.latest_anchor()

	assert anchor["hash"] == hashes[-1]
	assert anchor["count"] == 3
	assert anchor["created_at"] == ledger.created_at_iso(fake.rows(DOCTYPE)[-1]["created_at"])


def test_post_daily_anchor_is_a_noop_without_a_webhook(fake, monkeypatch):
	def never(*args, **kwargs):
		raise AssertionError("must not post")

	monkeypatch.setattr(ledger.requests, "post", never, raising=False)
	record_three(fake)

	assert ledger.post_daily_anchor() is None


def test_post_daily_anchor_posts_count_hash_and_created_at(fake, monkeypatch):
	posts = []

	class Response:
		def __init__(self):
			self.checked = False

		def raise_for_status(self):
			self.checked = True

	response = Response()

	def post(url, json=None, timeout=None, **kwargs):
		posts.append((url, json, timeout))
		return response

	monkeypatch.setattr(ledger.requests, "post", post, raising=False)
	fake.conf["ops_discord_webhook_url"] = "https://discord.example/api/webhooks/1/x"
	hashes = record_three(fake)

	anchor = ledger.post_daily_anchor()

	assert anchor["hash"] == hashes[-1] and anchor["count"] == 3
	assert len(posts) == 1
	url, body, timeout = posts[0]
	assert url == "https://discord.example/api/webhooks/1/x"
	assert timeout
	assert hashes[-1] in body["content"] and "count=3" in body["content"]
	fields = {f["name"]: f["value"] for f in body["embeds"][0]["fields"]}
	assert fields == {"count": "3", "hash": hashes[-1], "created_at": anchor["created_at"]}
	assert response.checked, "an HTTP error from the webhook must surface, not vanish"


# ── controller: append-only ─────────────────────────────────────────────


def test_controller_refuses_to_update_an_existing_row(fake):
	doc = ComplianceAuditEvent()
	doc.is_new = lambda: False
	with pytest.raises(Thrown, match="append-only"):
		doc.before_save()


def test_controller_allows_the_initial_insert(fake):
	doc = ComplianceAuditEvent()
	doc.is_new = lambda: True
	doc.before_save()  # no throw


def test_controller_refuses_deletes(fake):
	doc = ComplianceAuditEvent()
	with pytest.raises(Thrown, match="append-only"):
		doc.on_trash()


# ── endpoints ───────────────────────────────────────────────────────────


def test_endpoints_are_whitelisted_and_admin_gated():
	from pathlib import Path

	source = (Path(__file__).resolve().parents[1] / "api" / "compliance_audit.py").read_text()
	for fn in ("verify_audit_chain", "get_audit_anchor"):
		stack = f"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef {fn}("
		assert stack in source, f"{fn} is missing the whitelist/require_admin/handle_api_errors stack"
	# record_event is called from other endpoints, never exposed as one.
	assert "\ndef record_event(" in source
	assert "@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef record_event(" not in source


def test_verify_audit_chain_endpoint(fake):
	record_three(fake)
	assert ledger.verify_audit_chain() == {"ok": True, "checked": 3, "first_bad": None}
	assert ledger.verify_audit_chain(limit="2")["checked"] == 2


def test_get_audit_anchor_endpoint(fake):
	hashes = record_three(fake)
	assert ledger.get_audit_anchor()["hash"] == hashes[-1]


def test_endpoint_permission_gate_rejects_non_admins(fake, monkeypatch):
	monkeypatch.setattr(frappe, "session", types.SimpleNamespace(user="nobody@getflash.io"))
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["Guest"])
	with pytest.raises(Thrown):
		ledger.get_audit_anchor()

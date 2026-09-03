"""get_upgrade_pulse counts decisions by reviewed_at, not by modified."""

from datetime import datetime

from idv_stubs import frappe, frappe_utils

from admin_panel.api import pulse

SINCE = datetime(2026, 8, 25)


def seed_requests(fake):
	fake.seed(
		"Account Upgrade Request",
		# Stamped and decided this week: counted.
		{
			"name": "A",
			"status": "Approved",
			"reviewed_at": datetime(2026, 8, 30),
			"modified": datetime(2026, 8, 30),
		},
		# Decided a month ago, RE-SAVED this week (phone sync): must NOT count —
		# this is exactly the over-count reviewed_at fixes.
		{
			"name": "B",
			"status": "Rejected",
			"reviewed_at": datetime(2026, 8, 1),
			"modified": datetime(2026, 8, 31),
		},
		# Legacy row (decided before reviewed_at existed), modified this week: counted.
		{"name": "C", "status": "Approved", "reviewed_at": None, "modified": datetime(2026, 8, 28)},
		# Legacy row, old: not counted.
		{"name": "D", "status": "Approved", "reviewed_at": None, "modified": datetime(2026, 8, 1)},
		# Still pending: never counted.
		{
			"name": "E",
			"status": "Pending",
			"reviewed_at": None,
			"modified": datetime(2026, 8, 31),
			"creation": 1,
		},
	)


def test_processed_since_prefers_reviewed_at_and_falls_back_for_legacy_rows(fake):
	seed_requests(fake)
	assert pulse._processed_since(SINCE) == 2


def test_get_upgrade_pulse_reports_the_reviewed_at_based_count(fake, monkeypatch):
	seed_requests(fake)
	monkeypatch.setattr(frappe_utils, "add_days", lambda dt, days: SINCE, raising=False)

	result = pulse.get_upgrade_pulse()

	assert result["processed_week"] == 2
	assert result["pending"] == 1
	assert result["oldest_who"] == "E"


def test_pulse_no_longer_counts_by_modified_alone():
	from pathlib import Path

	source = (Path(__file__).resolve().parents[1] / "api" / "pulse.py").read_text()
	assert '"reviewed_at": [">=", since]' in source
	assert '"reviewed_at": ["is", "not set"], "modified": [">=", since]' in source
	assert "records no processed-at timestamp" not in source

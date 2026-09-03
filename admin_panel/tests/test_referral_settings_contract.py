"""Contract tests for the Referral Settings single (referral-reward kill switch).

The `rewards_enabled` field name, its Check fieldtype, and its default of "1"
are a contract shared with the flash payout gate — flash pays a referral
reward only on an affirmative readable 1, so a rename or default flip here
would silently defer every payout. The seeding patch is part of the contract
too: doctype JSON defaults only apply on a UI save, so a migrate alone would
leave the switch NULL (read as 0) without it. Runs under plain ``pytest``
with no Frappe runtime, matching the existing contract-test style.
"""

import importlib
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
REFERRAL_SETTINGS_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "referral_settings"


def load_doctype():
	return json.loads((REFERRAL_SETTINGS_DIR / "referral_settings.json").read_text())


def test_doctype_is_a_single():
	doctype = load_doctype()
	assert doctype["issingle"] == 1


def test_rewards_enabled_is_a_check_defaulting_on_and_placed_in_the_layout():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	assert "rewards_enabled" in fields, "rewards_enabled missing from Referral Settings"
	assert fields["rewards_enabled"]["fieldtype"] == "Check"
	assert fields["rewards_enabled"]["default"] == "1"
	# The switch must also be placed in the layout, or the operator cannot
	# see or flip it from the settings page.
	assert "rewards_enabled" in doctype["field_order"]


def test_permissions_include_system_manager_and_accounts_manager_read():
	doctype = load_doctype()
	perms = {p["role"]: p for p in doctype["permissions"]}

	assert perms["System Manager"]["read"] == 1
	assert perms["Accounts Manager"]["read"] == 1


def test_track_changes_is_on():
	# Flipping the kill switch is an operational action; the audit trail of
	# who flipped it and when must survive.
	doctype = load_doctype()
	assert doctype["track_changes"] == 1


def test_seeding_patch_is_registered_post_model_sync():
	patches = (ADMIN_PANEL / "patches.txt").read_text()
	post = patches.split("[post_model_sync]", 1)[1]

	assert "admin_panel.patches.set_referral_rewards_default" in post


def test_seeding_patch_only_touches_null():
	patch_src = (ADMIN_PANEL / "patches" / "set_referral_rewards_default.py").read_text()

	# The patch must never overwrite an operator-set value — including a
	# deliberate 0 meaning "rewards off".
	assert "is None" in patch_src
	assert "get_singles_dict" in patch_src


# ---------------------------------------------------------------------------
# Behavioral tests for the seeding patch. The patch imports frappe at module
# level, so a stub is installed in sys.modules before the import — the same
# no-Frappe-runtime approach as the other contract tests in this suite.
# ---------------------------------------------------------------------------


def _ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


_frappe = _ensure_module("frappe")


class SinglesStore:
	"""Stand-in for frappe.db backed by a dict of raw tabSingles rows.

	Values live as strings, exactly as tabSingles stores them: an
	operator-set 0 is the string "0"; a never-saved field is simply absent.
	"""

	def __init__(self, rows=None):
		self.rows = dict(rows or {})
		self.writes = []

	def get_singles_dict(self, doctype):
		assert doctype == "Referral Settings"
		return dict(self.rows)

	def get_single_value(self, doctype, fieldname):
		# Faithful to Frappe v15: get_single_value casts the fetched value by
		# fieldtype before returning it, and the Check cast collapses a
		# missing value (NULL) to 0. This is exactly why the patch must not
		# use this API for its NULL guard — `0 is None` is never True.
		assert doctype == "Referral Settings"
		value = self.rows.get(fieldname)
		return int(value) if value is not None else 0

	def set_single_value(self, doctype, fieldname, value):
		assert doctype == "Referral Settings"
		self.rows[fieldname] = str(value)
		self.writes.append((fieldname, value))


def _run_patch(monkeypatch, db):
	monkeypatch.setattr(_frappe, "db", db, raising=False)
	patch = importlib.import_module("admin_panel.patches.set_referral_rewards_default")
	patch.execute()
	return db


def test_patch_seeds_rewards_on_for_a_fresh_migrate(monkeypatch):
	"""A freshly migrated site has no tabSingles row — the switch must read ON."""
	db = _run_patch(monkeypatch, SinglesStore())

	assert db.writes == [("rewards_enabled", 1)]

	# Re-running the patch against the now-seeded store writes nothing.
	db.writes.clear()
	importlib.import_module("admin_panel.patches.set_referral_rewards_default").execute()
	assert db.writes == []


def test_patch_never_overwrites_an_operator_zero(monkeypatch):
	"""A deliberate operator 0 (rewards off) must survive re-runs of the patch."""
	operator_rows = {"rewards_enabled": "0"}
	db = _run_patch(monkeypatch, SinglesStore(operator_rows))

	assert db.writes == []
	assert db.rows == operator_rows

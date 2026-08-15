"""Contract tests for the per-level daily top-up limits on Fygaro Settings.

The l1/l2/l3_daily_limit field names and their semantics (gross USD per
rolling 24h, keyed by account level) are a contract shared with the flash
webhook's credit gate — flash fails closed (every payment drops to manual
review) if any of the three is missing, which is why the seeding patch below
is part of the contract too. Runs under plain ``pytest`` with no Frappe
runtime, matching the existing contract-test style.
"""

import importlib
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
FYGARO_SETTINGS_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "fygaro_settings"

EXPECTED_DEFAULTS = {
	"l1_daily_limit": "125.00",
	"l2_daily_limit": "1000.00",
	"l3_daily_limit": "2500.00",
}


def load_doctype():
	return json.loads((FYGARO_SETTINGS_DIR / "fygaro_settings.json").read_text())


def test_doctype_defines_all_three_daily_limits_as_currency_with_defaults():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	for fieldname, default in EXPECTED_DEFAULTS.items():
		assert fieldname in fields, f"{fieldname} missing from Fygaro Settings"
		assert fields[fieldname]["fieldtype"] == "Currency"
		assert fields[fieldname]["default"] == default
		# Each limit must also be placed in the layout, or the operator cannot
		# see or tune it from the settings page.
		assert fieldname in doctype["field_order"]


def test_validate_rejects_negative_daily_limits():
	controller = (FYGARO_SETTINGS_DIR / "fygaro_settings.py").read_text()
	normalized = " ".join(controller.split())

	assert '("l1_daily_limit", "l2_daily_limit", "l3_daily_limit")' in normalized
	assert "cannot be negative" in controller


def test_seeding_patch_is_registered_post_model_sync():
	patches = (ADMIN_PANEL / "patches.txt").read_text()
	post = patches.split("[post_model_sync]", 1)[1]

	assert "admin_panel.patches.set_fygaro_daily_limit_defaults" in post


def test_seeding_patch_defaults_match_the_doctype_and_only_touch_null():
	patch_src = (ADMIN_PANEL / "patches" / "set_fygaro_daily_limit_defaults.py").read_text()

	for fieldname, default in EXPECTED_DEFAULTS.items():
		assert (
			f'"{fieldname}": {default}' in patch_src
		), f"patch default for {fieldname} drifted from the doctype default"
	# The patch must never overwrite an operator-set value — including a
	# deliberate 0 meaning "no card top-ups for this level".
	assert "is None" in patch_src


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
		assert doctype == "Fygaro Settings"
		return dict(self.rows)

	def get_single_value(self, doctype, fieldname):
		# Faithful to Frappe v15: get_single_value casts the fetched value by
		# fieldtype before returning it, and the Currency cast collapses a
		# missing value (NULL) to 0.0. This is exactly why the patch must not
		# use this API for its NULL guard — `0.0 is None` is never True.
		assert doctype == "Fygaro Settings"
		value = self.rows.get(fieldname)
		return float(value) if value is not None else 0.0

	def set_single_value(self, doctype, fieldname, value):
		assert doctype == "Fygaro Settings"
		self.rows[fieldname] = str(value)
		self.writes.append((fieldname, value))


def _run_patch(monkeypatch, db):
	monkeypatch.setattr(_frappe, "db", db, raising=False)
	patch = importlib.import_module("admin_panel.patches.set_fygaro_daily_limit_defaults")
	patch.execute()
	return db


def test_patch_seeds_all_three_defaults_on_a_fresh_migrate(monkeypatch):
	"""A freshly migrated site has no tabSingles rows — all three must be seeded."""
	db = _run_patch(monkeypatch, SinglesStore())

	assert db.writes == [
		("l1_daily_limit", 125.00),
		("l2_daily_limit", 1000.00),
		("l3_daily_limit", 2500.00),
	]

	# Re-running the patch against the now-seeded store writes nothing.
	db.writes.clear()
	importlib.import_module("admin_panel.patches.set_fygaro_daily_limit_defaults").execute()
	assert db.writes == []


def test_patch_never_overwrites_operator_values_including_zero(monkeypatch):
	"""Operator-set values — including a deliberate 0 — must survive re-runs."""
	operator_rows = {
		"l1_daily_limit": "0",  # deliberate "no card top-ups for L1"
		"l2_daily_limit": "500.00",
		"l3_daily_limit": "9999.99",
	}
	db = _run_patch(monkeypatch, SinglesStore(operator_rows))

	assert db.writes == []
	assert db.rows == operator_rows

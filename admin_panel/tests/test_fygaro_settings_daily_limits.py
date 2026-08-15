"""Contract tests for the per-level daily top-up limits on Fygaro Settings.

The l1/l2/l3_daily_limit field names and their semantics (gross USD per
rolling 24h, keyed by account level) are a contract shared with the flash
webhook's credit gate — flash fails closed (every payment drops to manual
review) if any of the three is missing, which is why the seeding patch below
is part of the contract too. Runs under plain ``pytest`` with no Frappe
runtime, matching the existing contract-test style.
"""

import json
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
		assert f'"{fieldname}": {default.rstrip("0").rstrip(".") + ".00"}' in patch_src or (
			f'"{fieldname}": {default}' in patch_src
		), f"patch default for {fieldname} drifted from the doctype default"
	# The patch must never overwrite an operator-set value — including a
	# deliberate 0 meaning "no card top-ups for this level".
	assert "is None" in patch_src

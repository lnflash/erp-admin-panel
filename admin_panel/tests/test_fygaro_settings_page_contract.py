"""Contract tests for the Fygaro Settings doctype and the fee-breakdown wiring.

These run under plain `pytest` with no Frappe runtime — they assert on the
committed doctype JSON, the admin API query, and the Transfer Requests page JS.
The field names here are a contract shared with the flash backend; keep them in
sync if either side renames a field.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
FYGARO_SETTINGS_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "fygaro_settings"
BRIDGE_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "bridge_transfer_request"
PAGE_DIR = ADMIN_PANEL / "admin_panel" / "page" / "transfer_requests"


def read_text(path):
	return path.read_text()


def fygaro_settings_doc():
	return json.loads((FYGARO_SETTINGS_DIR / "fygaro_settings.json").read_text())


def fields_by_name(doc):
	return {field["fieldname"]: field for field in doc["fields"]}


def test_fygaro_settings_is_single_doctype_in_admin_panel_module():
	doc = fygaro_settings_doc()

	assert doc["name"] == "Fygaro Settings"
	assert doc["issingle"] == 1
	assert doc["module"] == "Admin Panel"
	# A fresh `bench migrate` must resync this doctype, so the modified stamp
	# has to be at least as recent as the change that introduced it.
	assert doc["modified"] >= "2026-08-10"


def test_fygaro_settings_has_expected_fields_and_defaults():
	fields = fields_by_name(fygaro_settings_doc())

	expected = {
		"processor": ("Data", "PayPal"),
		"processor_fee_percent": ("Float", "2.99"),
		"processor_fee_fixed": ("Currency", "0.49"),
		"flash_margin_percent": ("Float", "2.0"),
		"flash_margin_fixed": ("Currency", "0.00"),
		"auto_credit_limit": ("Currency", "500.00"),
		"minimum_topup": ("Currency", "10.00"),
		"auto_credit_enabled": ("Check", "0"),
	}

	for fieldname, (fieldtype, default) in expected.items():
		assert fieldname in fields, f"missing field {fieldname}"
		assert fields[fieldname]["fieldtype"] == fieldtype
		assert fields[fieldname]["default"] == default


def test_fygaro_settings_auto_credit_is_off_by_default():
	fields = fields_by_name(fygaro_settings_doc())

	assert fields["auto_credit_enabled"]["fieldtype"] == "Check"
	assert fields["auto_credit_enabled"]["default"] == "0"


def test_fygaro_settings_groups_fields_with_section_breaks():
	fields = fygaro_settings_doc()["fields"]
	section_labels = [f.get("label") for f in fields if f["fieldtype"] == "Section Break"]

	assert "Processor Fees" in section_labels
	assert "Flash Fee" in section_labels
	assert "Auto-Credit Controls" in section_labels


def test_bridge_transfer_request_exposes_fee_breakdown_fields():
	fields = fields_by_name(json.loads((BRIDGE_DIR / "bridge_transfer_request.json").read_text()))

	assert fields["processor_fee"]["fieldtype"] == "Currency"
	assert fields["flash_fee"]["fieldtype"] == "Currency"
	# Gross paid and net credited already exist and are reused by the backend.
	assert "initial_amount" in fields
	assert "final_amount" in fields


def test_get_bridge_transfer_requests_returns_fee_breakdown_fields():
	api_py = read_text(ADMIN_PANEL / "api" / "admin_api.py")

	assert "def get_bridge_transfer_requests" in api_py
	assert '"processor_fee"' in api_py
	assert '"flash_fee"' in api_py


def test_transfer_requests_drawer_renders_fee_breakdown():
	js = read_text(PAGE_DIR / "transfer_requests.js")

	assert "renderFeesSection(req)" in js
	assert "${this.renderFeesSection(req)}" in js
	# Fee rows are read-only labels rendered through the escaped detail item.
	for label in ("Gross", "Processor Fee", "Flash Fee", "Net Credited"):
		assert f'"{label}"' in js
	assert "req.processor_fee" in js
	assert "req.flash_fee" in js

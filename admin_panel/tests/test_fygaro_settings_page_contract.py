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


def extract_js_function(js, name):
	"""Return the source of a `name(...) { ... }` method by brace-matching.

	Lets a test assert on the *body* of one method rather than greping the
	whole file — so a gate check can't be satisfied by an unrelated match
	elsewhere in the source.
	"""
	# Find the method *definition*, skipping `this.name(...)` call sites
	# (which are preceded by a dot).
	search = 0
	while True:
		start = js.index(f"{name}(", search)
		if start == 0 or js[start - 1] != ".":
			break
		search = start + 1
	brace = js.index("{", start)
	depth = 0
	for i in range(brace, len(js)):
		if js[i] == "{":
			depth += 1
		elif js[i] == "}":
			depth -= 1
			if depth == 0:
				return js[start : i + 1]
	raise AssertionError(f"unbalanced braces extracting {name}")


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

	# Data (not Currency) so an uncomputed fee stays NULL instead of defaulting
	# to 0.0. Currency can't tell "not computed" from a genuine 0.00; the panel
	# needs that distinction to render "Pending" for a Fygaro row created before
	# the backend writes fees, rather than a "USD 0.00" that fails to reconcile
	# against Gross/Net. These match the other amount fields, all Data-typed.
	assert fields["processor_fee"]["fieldtype"] == "Data"
	assert fields["flash_fee"]["fieldtype"] == "Data"
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


def test_fees_section_gates_on_provider_not_fee_presence():
	"""The whole section must hide for Bridge rows.

	Only Fygaro (card) top-ups carry a fee breakdown; Bridge transfers never
	do. The gate keys on the row being a Fygaro top-up, not on whether the fee
	fields happen to hold a value — a Fygaro row with not-yet-computed fees
	still shows the section (with a "Pending" fee, see the test below), and a
	Bridge row never does. This asserts on the extracted method body so an
	unrelated provider check elsewhere in the file can't satisfy it.
	"""
	body = extract_js_function(read_text(PAGE_DIR / "transfer_requests.js"), "renderFeesSection")

	# Early-returns empty for anything that isn't a Fygaro card top-up.
	assert 'req.provider !== "Fygaro"' in body
	assert 'return ""' in body
	# And does NOT hide the whole section on fee presence (the regressed
	# behavior that keyed the section off a per-fee value check).
	assert "hasValue" not in body


def test_fees_section_marks_uncomputed_fygaro_fees_as_pending():
	"""A Fygaro row can exist before the backend computes its fees.

	processor_fee/flash_fee are Data-typed, so an uncomputed fee is NULL/empty
	(not 0.00). The panel must surface that as "Pending" rather than format it
	as "USD 0.00": a zero fee makes Gross minus fees fail to reconcile against
	Net, showing the operator a breakdown that visibly doesn't add up.
	"""
	js = read_text(PAGE_DIR / "transfer_requests.js")
	fees_body = extract_js_function(js, "renderFeesSection")
	fee_display_body = extract_js_function(js, "feeDisplay")

	# Fee rows route through feeDisplay, not raw formatAmount, so an uncomputed
	# fee can be labeled instead of formatted as a currency amount.
	assert "this.feeDisplay(req.processor_fee" in fees_body
	assert "this.feeDisplay(req.flash_fee" in fees_body
	# Gross and Net stay as formatted amounts (they are set at row creation).
	assert "this.formatAmount(req.initial_amount" in fees_body
	assert "this.formatAmount(req.final_amount" in fees_body
	# feeDisplay distinguishes an uncomputed (NULL/empty) fee from a real 0.00
	# and labels the uncomputed case "Pending".
	assert '"Pending"' in fee_display_body
	assert "formatAmount" in fee_display_body


def test_fygaro_settings_controller_validates_policy_invariants():
	"""The financial-policy single must guard its own invariants on save.

	No Frappe runtime here, so this asserts the controller *has* a validate()
	that enforces the key guards: non-negative fees/margins, percent bounds,
	a positive minimum, and an auto-credit limit at or above that minimum.
	With auto-credit enabled these directly bound what gets credited without
	review, so an empty `pass` controller is a defect.
	"""
	controller = read_text(FYGARO_SETTINGS_DIR / "fygaro_settings.py")

	assert "def validate(self)" in controller
	# Non-negative guard on every fee/margin field.
	for fieldname in (
		"processor_fee_percent",
		"processor_fee_fixed",
		"flash_margin_percent",
		"flash_margin_fixed",
	):
		assert fieldname in controller, f"validate must reference {fieldname}"
	assert "< 0" in controller
	# Percent fields are bounded above at 100.
	assert "> 100" in controller
	# Positive minimum and limit-at-or-above-minimum ordering.
	assert "minimum_topup" in controller
	assert "auto_credit_limit" in controller
	assert "frappe.throw" in controller

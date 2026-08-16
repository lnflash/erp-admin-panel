"""Contract + validation tests for the Fee Discount doctype.

The field names (username / discount_percent / applies_to_topup /
applies_to_cashout / active) are a contract shared with the flash backend's
cached fee-discount reader — flash silently fails open to a 0% discount for
rows it cannot validate, so a drifted field name would not error anywhere; it
would just quietly stop discounting. Runs under plain ``pytest`` with no
Frappe runtime, matching the existing contract-test style.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
FEE_DISCOUNT_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "fee_discount"

# The exact fieldnames the flash reader selects — keep in sync with
# src/services/frappe/fee-discounts.ts in the flash repo.
FLASH_CONTRACT_FIELDS = (
	"username",
	"discount_percent",
	"applies_to_topup",
	"applies_to_cashout",
	"active",
)


def load_doctype():
	return json.loads((FEE_DISCOUNT_DIR / "fee_discount.json").read_text())


def test_doctype_defines_every_flash_contract_field():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	for fieldname in FLASH_CONTRACT_FIELDS:
		assert fieldname in fields, f"{fieldname} missing from Fee Discount"
		# Every contract field must be placed in the layout, or the operator
		# cannot see or tune it from the list/form.
		assert fieldname in doctype["field_order"]


def test_username_is_required_unique_and_the_document_name():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	assert fields["username"]["reqd"] == 1
	assert fields["username"]["unique"] == 1
	# autoname by username makes the row name the username itself — one row
	# per user, enforced by the primary key rather than just the unique index.
	assert doctype["autoname"] == "field:username"


def test_flow_checkboxes_and_active_default_on():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	for fieldname in ("applies_to_topup", "applies_to_cashout", "active"):
		assert fields[fieldname]["fieldtype"] == "Check"
		assert fields[fieldname]["default"] == "1"


# ---------------------------------------------------------------------------
# Behavioral tests for the controller's validate(). The controller imports
# frappe at module level, so a stub is installed in sys.modules before the
# import — the same no-Frappe-runtime approach as the other contract tests.
# ---------------------------------------------------------------------------


def _ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


class _ValidationError(Exception):
	pass


_frappe = _ensure_module("frappe")
_frappe.throw = lambda msg, *a, **k: (_ for _ in ()).throw(_ValidationError(msg))
_frappe_utils = _ensure_module("frappe.utils")


def _flt(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


_frappe_utils.flt = _flt
_frappe.utils = _frappe_utils

_frappe_model = _ensure_module("frappe.model")
_frappe_document = _ensure_module("frappe.model.document")
if not hasattr(_frappe_document, "Document"):

	class _Document:  # stand-in for frappe.model.document.Document
		pass

	_frappe_document.Document = _Document
_frappe_model.document = _frappe_document


def _make_doc(**attrs):
	sys.path.insert(0, str(FEE_DISCOUNT_DIR))
	try:
		module = importlib.import_module("fee_discount")
	finally:
		sys.path.pop(0)
	doc = module.FeeDiscount.__new__(module.FeeDiscount)
	defaults = {
		"username": "alice",
		"discount_percent": 50,
		"applies_to_topup": 1,
		"applies_to_cashout": 1,
		"active": 1,
	}
	defaults.update(attrs)
	for key, value in defaults.items():
		setattr(doc, key, value)
	return doc


def test_validate_accepts_a_full_waiver_and_strips_the_username():
	doc = _make_doc(username="  bob  ", discount_percent=100)
	doc.validate()
	assert doc.username == "bob"


@pytest.mark.parametrize("percent", [-1, 100.01, 250])
def test_validate_rejects_out_of_range_percentages(percent):
	with pytest.raises(_ValidationError):
		_make_doc(discount_percent=percent).validate()


def test_validate_rejects_blank_username():
	with pytest.raises(_ValidationError):
		_make_doc(username="   ").validate()


def test_validate_rejects_a_discount_that_applies_to_nothing():
	with pytest.raises(_ValidationError):
		_make_doc(applies_to_topup=0, applies_to_cashout=0).validate()

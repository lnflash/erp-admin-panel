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


def test_username_is_set_only_once():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	# With autoname field:username, Frappe's _sync_autoname_field silently
	# reverts any direct edit of the field back to the document name on save —
	# an operator "fixing" a typo would see the save succeed and the value
	# snap back. set_only_once turns that silent revert into a loud
	# CannotChangeConstantError; renaming still works via the Rename dialog,
	# which updates both the name and the field.
	assert fields["username"]["set_only_once"] == 1


def test_flow_checkboxes_and_active_default_on():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	for fieldname in ("applies_to_topup", "applies_to_cashout", "active"):
		assert fields[fieldname]["fieldtype"] == "Check"
		assert fields[fieldname]["default"] == "1"


# ---------------------------------------------------------------------------
# Behavioral tests for the controller. The controller imports frappe at module
# level, so import-time gaps are filled in sys.modules below — hasattr-guarded
# only, never clobbering a real frappe where one is installed (bench, dev
# venv). Everything the tests rely on at call time (throw / flt / msgprint /
# log_error) is patched per-test via monkeypatch so it is auto-restored.
# ---------------------------------------------------------------------------


def _ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


class _ValidationError(Exception):
	pass


def _throw(msg, *args, **kwargs):
	raise _ValidationError(msg)


def _flt(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


# Import-time needs only: `import frappe` and
# `from frappe.model.document import Document`.
_frappe = _ensure_module("frappe")
_frappe_utils = _ensure_module("frappe.utils")
if not hasattr(_frappe, "utils"):
	_frappe.utils = _frappe_utils

_frappe_model = _ensure_module("frappe.model")
_frappe_document = _ensure_module("frappe.model.document")
if not hasattr(_frappe_document, "Document"):

	class _Document:  # stand-in for frappe.model.document.Document
		pass

	_frappe_document.Document = _Document
if not hasattr(_frappe_model, "document"):
	_frappe_model.document = _frappe_document


@pytest.fixture(autouse=True)
def frappe_runtime(monkeypatch):
	"""Patch the call-time frappe surfaces per test, auto-restored after."""
	messages = []
	monkeypatch.setattr(_frappe, "throw", _throw, raising=False)
	monkeypatch.setattr(_frappe_utils, "flt", _flt, raising=False)
	monkeypatch.setattr(_frappe, "msgprint", lambda msg=None, *a, **k: messages.append(msg), raising=False)
	monkeypatch.setattr(_frappe, "log_error", lambda *a, **k: None, raising=False)
	monkeypatch.setattr(_frappe, "get_traceback", lambda *a, **k: "", raising=False)
	return types.SimpleNamespace(messages=messages)


@pytest.fixture()
def flash(monkeypatch):
	"""Stub the lazy GraphQLClient import with a scriptable account lookup."""
	state = types.SimpleNamespace(account=None, error=None, lookups=[])

	class _StubGraphQLClient:
		def get_account_by_username(self, username):
			state.lookups.append(username)
			if state.error is not None:
				raise state.error
			return state.account

	stub = types.ModuleType("admin_panel.api.graphql_client")
	stub.GraphQLClient = _StubGraphQLClient
	monkeypatch.setitem(sys.modules, "admin_panel.api.graphql_client", stub)
	return state


def _make_doc(**attrs):
	module = importlib.import_module("admin_panel.admin_panel.doctype.fee_discount.fee_discount")
	doc = module.FeeDiscount.__new__(module.FeeDiscount)
	# Document-base surfaces validate() consults; a fresh unsaved doc by
	# default — override via attrs (e.g. is_new=lambda: False) for saved rows.
	doc.is_new = lambda: True
	doc.has_value_changed = lambda fieldname: True
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


# ---------------------------------------------------------------------------
# Username resolution against flash. The flash reader keys its Map on the
# exact stored string (trim only, case-sensitive) and fails open to 0% for
# unknown usernames — so an unverified typo would save cleanly and silently
# never discount.
# ---------------------------------------------------------------------------


def test_before_insert_rejects_a_username_flash_does_not_know(flash):
	flash.account = None  # flash: no such account
	doc = _make_doc(username="jhonb")
	with pytest.raises(_ValidationError):
		doc.before_insert()
	assert flash.lookups == ["jhonb"]


def test_before_insert_canonicalizes_username_case_from_flash(flash):
	flash.account = {"username": "johnb"}
	doc = _make_doc(username="  JohnB  ")
	doc.before_insert()
	# before_insert runs before set_new_name, so the canonical spelling is
	# what the document gets named — and what the flash reader matches on.
	assert doc.username == "johnb"
	assert flash.lookups == ["JohnB"]


def test_flash_outage_warns_but_never_blocks_the_save(flash, frappe_runtime):
	flash.error = RuntimeError("flash is down")
	doc = _make_doc(username="alice")
	doc.before_insert()  # must not raise — an outage must not brick the panel
	assert doc.username == "alice"
	assert frappe_runtime.messages, "operator must see a could-not-verify warning"


def test_validate_reresolves_when_username_changes_on_a_saved_row(flash):
	flash.account = {"username": "carol"}
	doc = _make_doc(
		username="Carol",
		is_new=lambda: False,
		has_value_changed=lambda fieldname: fieldname == "username",
	)
	doc.validate()
	assert doc.username == "carol"
	assert flash.lookups == ["Carol"]


def test_validate_skips_the_flash_lookup_when_username_is_unchanged(flash):
	doc = _make_doc(is_new=lambda: False, has_value_changed=lambda fieldname: False)
	doc.validate()
	assert flash.lookups == []

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

	# The reader addresses the resource as "Fee Discount"; renaming the doctype
	# (or editing "name" here) is exactly as silent as a fieldname drift,
	# because the reader fails open to 0%.
	assert doctype["name"] == "Fee Discount"

	for fieldname in FLASH_CONTRACT_FIELDS:
		assert fieldname in fields, f"{fieldname} missing from Fee Discount"
		# Every contract field must be placed in the layout, or the operator
		# cannot see or tune it from the list/form.
		assert fieldname in doctype["field_order"]

	# flash multiplies this value; a Float→Data drift would ship a string
	# across the contract and, again, fail open rather than error.
	assert fields["discount_percent"]["fieldtype"] == "Float"


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
	# BEFORE validate_set_only_once compares, so the constant-field error can
	# never fire for an autoname field. set_only_once's real effect is making
	# the field read-only in Desk; the controller's validate() supplies the
	# loud rejection for scripted edits, and the Rename dialog (which updates
	# both the name and the field) is the one working change path.
	assert fields["username"]["set_only_once"] == 1


def test_doctype_allows_rename():
	doctype = load_doctype()

	# The entire username-change workflow (set_only_once + the field
	# description + before_rename verification) funnels through the Rename
	# dialog, which only renders when meta.allow_rename is set. Doctype sync
	# imports run under frappe.flags.in_import, where _set_defaults is
	# skipped and an absent Check field serializes as 0 — so omitting the key
	# here would sync as allow_rename=0 on a fresh site and make the username
	# completely immutable (delete-and-recreate the row to fix a typo).
	assert doctype["allow_rename"] == 1


def test_flow_checkboxes_and_active_default_on():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	for fieldname in ("applies_to_topup", "applies_to_cashout", "active"):
		assert fields[fieldname]["fieldtype"] == "Check"
		assert fields[fieldname]["default"] == "1"


def test_verification_state_is_persisted_on_the_row_not_just_toasted():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	# A msgprint is invisible to REST callers (it arrives in _server_messages)
	# and gone once dismissed. A misconfigured admin_api_key fails *every*
	# check from then on, so the unverified state has to survive on the row
	# and be visible/filterable in the list view to be sweepable at all.
	assert fields["verified"]["fieldtype"] == "Check"
	assert fields["verified"]["default"] == "0"
	assert fields["verified"]["read_only"] == 1
	assert fields["verified"]["in_list_view"] == 1
	assert fields["verified"]["in_standard_filter"] == 1
	assert "verified" in doctype["field_order"]

	# ...and the description has to name the path that actually clears it. The
	# original "filter on this to re-check them" pointed at nothing: there was
	# no re-check anywhere, so the flag was permanent once set. The successor
	# ("re-save each row") pointed at something Desk refuses to do — save.js
	# skips the server call entirely on an untouched doc and answers "No
	# changes in document" — so the instruction must name the dirtying step
	# too, or the operator concludes the re-check is broken.
	description = fields["verified"]["description"]
	assert "change a field" in description
	assert "save" in description

	# The username is mutable on the flash side; the uuid is not. Without it a
	# row that went stale (user renamed themselves) is undetectable — the
	# reader just fails open to 0% forever.
	assert fields["account_uuid"]["fieldtype"] == "Data"
	assert fields["account_uuid"]["read_only"] == 1
	assert "account_uuid" in doctype["field_order"]


def test_admin_api_and_the_controller_share_one_username_shape_guard():
	# The regex was duplicated-by-omission before: admin_api screened lookup
	# candidates, the Fee Discount controller did not. Keep them on one
	# implementation so a future tightening lands on both — and so smart search
	# and the controller can never disagree about the same operator input.
	api_py = (ADMIN_PANEL / "api" / "admin_api.py").read_text()
	controller_py = (FEE_DISCOUNT_DIR / "fee_discount.py").read_text()

	assert "from .flash_identifiers import is_flash_username_candidate" in api_py
	assert "def _is_flash_username_candidate" in api_py
	assert "return is_flash_username_candidate(value)" in api_py
	assert "from admin_panel.api.flash_identifiers import is_flash_username_candidate" in controller_py

	# search_account_smart kept a third, hand-rolled copy of the old regex long
	# after the helper existed. Nothing but flash_identifiers may spell it out.
	assert "elif is_flash_username_candidate(query):" in api_py
	for source in (api_py, controller_py):
		assert 'r"^[a-zA-Z0-9_-]' not in source


@pytest.mark.parametrize(
	"value",
	["johnb", "abc", "ABC123", "john_b", "2fast", "josé_p", "Ω_mega", "a" * 50],
)
def test_shape_guard_accepts_flash_usernames(value):
	# flash's Username scalar is /^(?!^(1|3|bc1|lnbc1))[\p{L}0-9_]{3,50}$/iu
	# (src/domain/accounts/index.ts) — Unicode letters included, which is why
	# "josé_p" is a username flash accepts and the guard must not refuse.
	from admin_panel.api.flash_identifiers import is_flash_username_candidate

	assert is_flash_username_candidate(value) is True


@pytest.mark.parametrize(
	"value",
	[
		"jabari@getflash.io",
		"+18765550100",
		"ab",
		"john doe",
		"john.doe",
		"",
		None,
		# flash has no hyphen in the scalar — this was accepted before.
		"jo-hn_b",
		# The lookahead: a username may not read as a bitcoin address or a
		# BOLT11 invoice. All four prefixes were accepted before.
		"3dollars",
		"1abcdef",
		"bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
		"lnbc1pvjluezpp5qqqsyqcyq5rkwnn",
		# flash caps at 50 characters; an over-long paste was accepted before.
		"a" * 51,
		# An account uuid is not a username — it belongs on the by-id path.
		"b0f4d1e2-1111-4444-8888-aaaaaaaaaaaa",
	],
)
def test_shape_guard_rejects_what_flash_would_reject(value):
	from admin_panel.api.flash_identifiers import is_flash_username_candidate

	assert is_flash_username_candidate(value) is False


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


class _Flags(dict):
	"""Stand-in for frappe.flags (a frappe._dict): attribute + item access."""

	__getattr__ = dict.get

	def __setattr__(self, key, value):
		self[key] = value


@pytest.fixture(autouse=True)
def frappe_runtime(monkeypatch):
	"""Patch the call-time frappe surfaces per test, auto-restored after."""
	messages = []
	flags = _Flags()
	monkeypatch.setattr(_frappe, "throw", _throw, raising=False)
	monkeypatch.setattr(_frappe_utils, "flt", _flt, raising=False)
	monkeypatch.setattr(_frappe, "msgprint", lambda msg=None, *a, **k: messages.append(msg), raising=False)
	monkeypatch.setattr(_frappe, "log_error", lambda *a, **k: None, raising=False)
	monkeypatch.setattr(_frappe, "get_traceback", lambda *a, **k: "", raising=False)
	monkeypatch.setattr(_frappe, "flags", flags, raising=False)
	return types.SimpleNamespace(messages=messages, flags=flags)


@pytest.fixture()
def flash(monkeypatch):
	"""Stub the lazy GraphQLClient import with a scriptable account lookup.

	``init_error`` models the misconfiguration case specifically: the real
	GraphQLClient.__init__ raises ValueError when flash_admin_api_url or
	admin_api_key is missing from site_config.json, so the failure happens
	before any lookup is attempted.
	"""
	state = types.SimpleNamespace(account=None, error=None, init_error=None, lookups=[])

	class _StubGraphQLClient:
		def __init__(self):
			if state.init_error is not None:
				raise state.init_error

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
	# after_rename persists through db_set (rename_doc never saves the doc);
	# record the calls so the test can assert what reached the row.
	doc.db_set_calls = []
	doc.db_set = lambda fieldname, value=None, **kwargs: doc.db_set_calls.append(fieldname)
	defaults = {
		"doctype": "Fee Discount",
		"username": "alice",
		"discount_percent": 50,
		"applies_to_topup": 1,
		"applies_to_cashout": 1,
		"active": 1,
		"verified": 0,
		"account_uuid": None,
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
# Username resolution against flash. The flash reader matches
# case-insensitively but fails open to 0% for unknown usernames — so an
# unverified typo would save cleanly and silently never discount.
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


def test_before_insert_records_the_immutable_account_uuid(flash):
	# The row is keyed on a mutable identifier: a user who renames themselves
	# on flash a month from now leaves this row pointing at nothing, and the
	# reader fails open to 0% silently. The uuid is what makes that stale row
	# findable in one query.
	flash.account = {"username": "johnb", "uuid": "b0f4d1e2-1111-4444-8888-aaaaaaaaaaaa"}
	doc = _make_doc(username="johnb")
	doc.before_insert()
	assert doc.verified == 1
	assert doc.account_uuid == "b0f4d1e2-1111-4444-8888-aaaaaaaaaaaa"


def test_flash_outage_warns_but_never_blocks_the_save(flash, frappe_runtime):
	flash.error = RuntimeError("flash is down")
	doc = _make_doc(username="alice")
	doc.before_insert()  # must not raise — an outage must not brick the panel
	assert doc.username == "alice"
	assert frappe_runtime.messages, "operator must see a could-not-verify warning"


def test_unverified_state_is_persisted_on_the_row_not_only_toasted(flash):
	# A toast is invisible to REST callers and gone once dismissed. The row
	# itself has to carry the fact that the check never ran.
	flash.error = RuntimeError("flash is down")
	doc = _make_doc(username="alice", verified=1, account_uuid="stale-uuid")
	doc.before_insert()
	assert doc.verified == 0
	assert doc.account_uuid is None


def test_a_misconfigured_client_leaves_every_row_flagged_unverified(flash):
	# GraphQLClient.__init__ raises ValueError when flash_admin_api_url or
	# admin_api_key is missing/rotated — permanent, not transient, so every
	# create from then on skips verification. That must be discoverable in the
	# list view rather than only in a toast the operator already dismissed.
	flash.init_error = ValueError("flash_admin_api_url is not configured in site_config.json")
	first = _make_doc(username="alice")
	second = _make_doc(username="bobby")
	first.before_insert()
	second.before_insert()
	assert (first.verified, second.verified) == (0, 0)
	assert flash.lookups == [], "the client never got far enough to look anything up"


@pytest.mark.parametrize(
	"value",
	[
		"jabari@getflash.io",
		"+18765550100",
		"ab",
		"john doe",
		"jo-hn_b",
		"3dollars",
		"b0f4d1e2-1111-4444-8888-aaaaaaaaaaaa",
	],
)
def test_before_insert_rejects_identifiers_that_are_not_usernames(flash, value):
	# Not a fail-open fix: flash answers a non-Username argument with
	# INVALID_INPUT, which GraphQLClient already reads as "no such account", so
	# these would be rejected either way. The guard is what makes the error say
	# "that is not a username" — and what stops the round trip being spent.
	doc = _make_doc(username=value)
	with pytest.raises(_ValidationError):
		doc.before_insert()
	assert flash.lookups == [], "a malformed identifier must not reach flash at all"


def test_before_insert_accepts_a_unicode_username_that_flash_accepts(flash):
	# flash's Username scalar is Unicode ([\p{L}0-9_]{3,50}), so this is a real
	# account. An ASCII-only shape guard refused it before flash was ever asked,
	# which made the discount impossible to create OR rename — the only two
	# entry points the doctype has both run through the same guard.
	flash.account = {"username": "josé_p", "uuid": "d2d2d2d2-3333-4444-8888-cccccccccccc"}
	doc = _make_doc(username="josé_p")
	doc.before_insert()
	assert flash.lookups == ["josé_p"]
	assert (doc.username, doc.verified) == ("josé_p", 1)


def test_validate_rejects_in_place_username_edits_on_a_saved_row(flash):
	# An in-place edit can never take effect: _sync_autoname_field reverts the
	# field to the document name before the save completes, so accepting it
	# here would let a scripted edit "succeed" while the discount silently
	# stays with the old user. The Rename dialog is the one working path.
	flash.account = {"username": "carol"}
	doc = _make_doc(
		username="carol",
		is_new=lambda: False,
		has_value_changed=lambda fieldname: fieldname == "username",
	)
	with pytest.raises(_ValidationError):
		doc.validate()
	assert flash.lookups == []


def test_validate_accepts_a_saved_row_whose_username_is_unchanged(flash):
	# Guards the other side of the throw above: editing the notes or the
	# percentage on an existing row must not trip the in-place-edit rejection.
	# An already-verified row also must not spend a flash lookup on every save.
	doc = _make_doc(
		username="carol",
		discount_percent=25,
		verified=1,
		is_new=lambda: False,
		has_value_changed=lambda fieldname: False,
	)
	doc.validate()
	assert doc.username == "carol"
	assert flash.lookups == []


def _saved_unverified_doc(**attrs):
	attrs.setdefault("username", "carol")
	attrs.setdefault("verified", 0)
	attrs.setdefault("is_new", lambda: False)
	attrs.setdefault("has_value_changed", lambda fieldname: False)
	return _make_doc(**attrs)


def test_saving_an_unverified_row_re_checks_it_against_flash(flash):
	# verified=0 is the durable signal that the check never ran (rotated
	# admin_api_key, flash down). It needs a clearing path or it degrades into
	# noise: before_insert only fires on create, Frappe refuses a
	# rename-to-itself, and no scheduler event is enabled — so re-saving the
	# row has to be the re-check the field description promises.
	flash.account = {"username": "carol", "uuid": "e3e3e3e3-4444-4444-8888-dddddddddddd"}
	doc = _saved_unverified_doc(account_uuid=None)
	doc.validate()
	assert flash.lookups == ["carol"]
	assert doc.verified == 1
	assert doc.account_uuid == "e3e3e3e3-4444-4444-8888-dddddddddddd"


def test_re_checking_while_flash_is_still_down_leaves_the_row_saveable(flash, frappe_runtime):
	# The re-check must not turn a flash outage into "you cannot edit this row
	# at all" — the outage rule is the same as on create: warn, save, stay 0.
	flash.error = RuntimeError("flash is down")
	doc = _saved_unverified_doc(discount_percent=25)
	doc.validate()
	assert doc.verified == 0
	assert frappe_runtime.messages, "operator must see a could-not-verify warning"


def test_the_re_check_never_rewrites_the_username_of_a_saved_row(flash):
	# _sync_autoname_field reverts the field to the document name on save, so
	# adopting flash's canonical spelling here would be a no-op at best and a
	# misleading in-memory diff at worst. Only the verification state moves.
	flash.account = {"username": "carol", "uuid": "e3e3e3e3-4444-4444-8888-dddddddddddd"}
	doc = _saved_unverified_doc(username="Carol")
	doc.validate()
	assert doc.username == "Carol"
	assert doc.verified == 1


def test_the_re_check_warns_but_saves_a_row_flash_does_not_know(flash, frappe_runtime):
	# The row saved unverified during an outage; now flash is up and says the
	# username does not exist. The re-check must NOT throw: it would reject a
	# save over a field the operator never touched and make the row impossible
	# to suspend — unchecking Active would hit this very check. The row is
	# already harmless (flash fails open to 0% for an unknown username), so
	# warn, leave verified=0, and let the save through.
	flash.account = None
	doc = _saved_unverified_doc(username="jhonb")
	doc.validate()
	assert doc.verified == 0
	assert doc.account_uuid is None
	assert flash.lookups == ["jhonb"]
	assert frappe_runtime.messages, "operator must see a still-not-verified warning"


def test_an_unverified_row_can_still_be_suspended_while_flash_denies_it(flash):
	# The documented escape hatch: "Uncheck to suspend the discount without
	# deleting the row" must work on exactly the rows that need suspending.
	flash.account = None
	doc = _saved_unverified_doc(username="jhonb", active=0)
	doc.validate()
	assert doc.active == 0


def test_a_row_that_fails_the_local_checks_never_costs_a_flash_lookup(flash):
	doc = _saved_unverified_doc(discount_percent=250)
	with pytest.raises(_ValidationError):
		doc.validate()
	assert flash.lookups == []


# ---------------------------------------------------------------------------
# Rename-dialog path. set_only_once (and the field description) funnel every
# username change into rename_doc, which writes both the document name and the
# username column raw — before_insert/validate never run. before_rename is the
# only verification point on that path: rename_doc honors a returned
# {"new": ...} override, so the rename lands on flash's canonical spelling.
# ---------------------------------------------------------------------------


def test_before_rename_rejects_a_username_flash_does_not_know(flash):
	flash.account = None  # flash: no such account
	doc = _make_doc(username="johnb")
	with pytest.raises(_ValidationError):
		doc.before_rename("johnb", "jhonb2")
	assert flash.lookups == ["jhonb2"]


def test_before_rename_returns_flash_canonical_spelling(flash):
	flash.account = {"username": "johnb2"}
	doc = _make_doc(username="johnb")
	out = doc.before_rename("johnb", "  JohnB2  ")
	assert out == {"new": "johnb2"}
	assert flash.lookups == ["JohnB2"]


def test_before_rename_rejects_a_blank_new_name(flash):
	doc = _make_doc(username="johnb")
	with pytest.raises(_ValidationError):
		doc.before_rename("johnb", "   ")
	assert flash.lookups == []


def test_before_rename_flash_outage_warns_but_allows_the_rename(flash, frappe_runtime):
	flash.error = RuntimeError("flash is down")
	doc = _make_doc(username="johnb")
	out = doc.before_rename("johnb", "johnb2")  # must not raise — an outage must not brick renames
	assert out == {"new": "johnb2"}
	assert frappe_runtime.messages, "operator must see a could-not-verify warning"


@pytest.mark.parametrize(
	"value",
	[
		"jabari@getflash.io",
		"+18765550100",
		"ab",
		"john doe",
		"jo-hn_b",
		"3dollars",
		"b0f4d1e2-1111-4444-8888-aaaaaaaaaaaa",
	],
)
def test_before_rename_rejects_identifiers_that_are_not_usernames(flash, value):
	doc = _make_doc(username="johnb")
	with pytest.raises(_ValidationError):
		doc.before_rename("johnb", value)
	assert flash.lookups == []


def test_before_rename_accepts_a_unicode_username_that_flash_accepts(flash):
	# The other half of the ASCII-only-guard regression: with the rename path
	# blocked too, an existing row could never be moved to this user either.
	flash.account = {"username": "josé_p"}
	doc = _make_doc(username="johnb")
	assert doc.before_rename("johnb", "josé_p") == {"new": "josé_p"}
	assert flash.lookups == ["josé_p"]


# ---------------------------------------------------------------------------
# after_rename persistence. rename_doc discards whatever before_rename set on
# the document (it never saves that object, and after_rename runs on a freshly
# fetched one), so the verification state has to be written explicitly — and
# only after the rename actually landed, since validate_rename can still
# reject the new name in between.
# ---------------------------------------------------------------------------


def test_after_rename_persists_the_new_owners_verification_state(flash):
	flash.account = {"username": "johnb2", "uuid": "c1c1c1c1-2222-4444-8888-bbbbbbbbbbbb"}
	doc = _make_doc(username="johnb", verified=1, account_uuid="uuid-of-the-previous-owner")
	doc.before_rename("johnb", "johnb2")
	doc.after_rename("johnb", "johnb2")
	assert doc.db_set_calls == [{"verified": 1, "account_uuid": "c1c1c1c1-2222-4444-8888-bbbbbbbbbbbb"}]


def test_after_rename_clears_the_previous_owners_uuid_when_flash_was_unreachable(flash):
	# A rename can move the discount to a different person; keeping the old
	# occupant's uuid/verified flag would be worse than carrying none.
	flash.error = RuntimeError("flash is down")
	doc = _make_doc(username="johnb", verified=1, account_uuid="uuid-of-the-previous-owner")
	doc.before_rename("johnb", "johnb2")
	doc.after_rename("johnb", "johnb2")
	assert doc.db_set_calls == [{"verified": 0, "account_uuid": None}]


def test_after_rename_without_a_matching_before_rename_leaves_the_row_alone(flash):
	# rename_doc(validate=False) skips before_rename entirely; a resolution
	# left over from some earlier call must not be stamped onto this row.
	doc = _make_doc(username="johnb")
	doc.after_rename("johnb", "johnb2")
	assert doc.db_set_calls == []


def test_after_rename_ignores_a_resolution_left_by_a_different_rename(flash):
	# The other half of the guard: frappe.model.rename_doc.bulk_rename loops
	# rename_doc in one process, and a resolution left behind by a rename that
	# validate_rename then rejected is never popped. Matching on the resolved
	# username is what stops one row's verification state being stamped onto
	# the next row in the batch.
	flash.account = {"username": "johnb2", "uuid": "c1c1c1c1-2222-4444-8888-bbbbbbbbbbbb"}
	doc = _make_doc(username="johnb")
	doc.before_rename("johnb", "johnb2")
	doc.after_rename("carol", "carol2")
	assert doc.db_set_calls == []


def test_before_rename_does_not_write_before_the_rename_is_validated(flash):
	# validate_rename runs AFTER before_rename and can still throw (target
	# name already exists). Writing the resolution from before_rename would
	# stamp the row for a rename that never happened.
	flash.account = {"username": "johnb2", "uuid": "c1c1c1c1-2222-4444-8888-bbbbbbbbbbbb"}
	doc = _make_doc(username="johnb", verified=0, account_uuid=None)
	doc.before_rename("johnb", "johnb2")
	assert doc.db_set_calls == []
	assert doc.verified == 0
	assert doc.account_uuid is None

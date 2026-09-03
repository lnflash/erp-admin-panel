"""ID Verification Settings: bounds validation + every change is ledgered."""

import pytest
from idv_stubs import Thrown, frappe

from admin_panel.admin_panel.doctype.id_verification_settings import id_verification_settings as module
from admin_panel.api import idv_core

GOOD = {
	"auto_approve_enabled": 0,
	"auto_approve_levels": "TWO",
	"auto_approve_min_score": 0.9,
	"auto_approve_sampling_percent": 10,
	"bridge_kyc_satisfies_identity": 1,
	"retention_years": 7,
	"idv_service_url": None,
}


def make(values, before=None):
	doc = module.IDVerificationSettings()
	for key, value in values.items():
		setattr(doc, key, value)
	doc.get = lambda key, default=None: getattr(doc, key, default)
	doc.get_doc_before_save = lambda: before
	return doc


@pytest.fixture()
def events(monkeypatch):
	recorded = []
	monkeypatch.setattr(module, "record_event", lambda *args: recorded.append(args))
	return recorded


# ── validate ────────────────────────────────────────────────────────────


def test_good_values_pass(fake):
	make(GOOD).validate()


@pytest.mark.parametrize(
	"field,value,message",
	[
		("retention_years", 0, "Retention"),
		("retention_years", -3, "Retention"),
		("auto_approve_sampling_percent", 101, "Sampling"),
		("auto_approve_sampling_percent", -1, "Sampling"),
		("auto_approve_min_score", 1.5, "Minimum Score"),
		("auto_approve_min_score", -0.1, "Minimum Score"),
	],
)
def test_out_of_range_values_throw(fake, field, value, message):
	with pytest.raises(Thrown, match=message):
		make({**GOOD, field: value}).validate()


def test_boundaries_are_inclusive(fake):
	make(
		{**GOOD, "retention_years": 1, "auto_approve_sampling_percent": 0, "auto_approve_min_score": 0}
	).validate()
	make({**GOOD, "auto_approve_sampling_percent": 100, "auto_approve_min_score": 1}).validate()


def test_form_strings_are_coerced_before_the_bounds_check(fake):
	make(
		{
			**GOOD,
			"retention_years": "7",
			"auto_approve_min_score": "0.9",
			"auto_approve_sampling_percent": "10",
		}
	).validate()
	with pytest.raises(Thrown):
		make({**GOOD, "retention_years": "0"}).validate()


# ── on_update ───────────────────────────────────────────────────────────


def test_on_update_records_the_diff(fake, events):
	before = dict(GOOD)
	doc = make({**GOOD, "auto_approve_enabled": 1, "auto_approve_min_score": 0.95}, before=before)

	doc.on_update()

	assert events == [
		(
			"idv_settings_changed",
			"ID Verification Settings",
			"ID Verification Settings",
			{
				"changed": {
					"auto_approve_enabled": {"from": 0, "to": 1},
					"auto_approve_min_score": {"from": 0.9, "to": 0.95},
				}
			},
		)
	]


def test_on_update_skips_when_nothing_changed(fake, events):
	make(GOOD, before=dict(GOOD)).on_update()
	assert events == []


def test_on_update_ignores_representation_only_differences(fake, events):
	"""The form posts "0.9" / "10" / "1"; the stored row has 0.9 / 10 / 1."""
	doc = make(
		{
			**GOOD,
			"auto_approve_min_score": "0.9",
			"auto_approve_sampling_percent": "10",
			"bridge_kyc_satisfies_identity": "1",
		},
		before=dict(GOOD),
	)
	doc.on_update()
	assert events == []


def test_first_save_diffs_against_nothing(fake, events):
	make({**GOOD, "idv_service_url": "http://idv:8080"}, before=None).on_update()

	assert len(events) == 1
	changed = events[0][3]["changed"]
	assert changed["idv_service_url"] == {"from": None, "to": "http://idv:8080"}
	assert changed["retention_years"] == {"from": 0, "to": 7}
	# A value that is empty both before and after is not a change.
	assert "auto_approve_enabled" not in changed


def test_untracked_fields_are_not_ledgered(fake, events):
	before = {**GOOD, "modified": "yesterday"}
	make({**GOOD, "modified": "today"}, before=before).on_update()
	assert events == []


# ── pure helpers ────────────────────────────────────────────────────────


def test_coerce_mirrors_tab_singles_round_trip():
	assert idv_core.coerce("Check", "1") == 1
	assert idv_core.coerce("Check", None) == 0
	assert idv_core.coerce("Int", "7") == 7
	assert idv_core.coerce("Int", "garbage") == 0
	assert idv_core.coerce("Float", "0.9") == 0.9
	assert idv_core.coerce("Float", "") == 0.0
	assert idv_core.coerce("Data", "") is None
	assert idv_core.coerce("Data", "TWO") == "TWO"


def test_settings_fields_match_the_doctype_json():
	import json
	from pathlib import Path

	doctype = json.loads(
		(
			Path(__file__).resolve().parents[1]
			/ "admin_panel"
			/ "doctype"
			/ "id_verification_settings"
			/ "id_verification_settings.json"
		).read_text()
	)
	value_fields = {
		f["fieldname"]: f["fieldtype"]
		for f in doctype["fields"]
		if f["fieldtype"] not in ("Section Break", "Column Break")
	}
	assert value_fields == dict(idv_core.SETTINGS_FIELDS)

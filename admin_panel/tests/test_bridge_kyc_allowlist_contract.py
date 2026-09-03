"""Contract tests for the Bridge KYC country allowlist on Allowed Country.

The Flash api's ``bridgeInitiateKyc`` reads
``GET /api/resource/Allowed Country?filters=[["flash_allowed","=",1]]&fields=["alpha2_code","country_name"]``
every 60s and denies KYC to any user whose phone country is not in the result.
A drifted field name would not error anywhere — flash would just deny every
country — so the fieldnames, the seed data shape, the allowlist constant and
the one-shot patch are all pinned here. Runs under plain ``pytest`` with no
Frappe runtime, matching the existing contract-test style.
"""

import json
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.admin_panel.doctype.allowed_country.kyc_allowlist import (
	ADDITIONAL_COUNTRIES,
	BRIDGE_KYC_ALLOWLIST,
	apply_plan_to_rows,
	flash_allowed_for,
	plan_reseed,
)

ADMIN_PANEL = REPO_ROOT / "admin_panel"
ALLOWED_COUNTRY_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "allowed_country"

# The exact fieldnames the flash reader selects/filters on — keep in sync with
# src/services/frappe/ in the flash repo.
FLASH_CONTRACT_FIELDS = ("alpha2_code", "flash_allowed", "country_name")

# The operator's seed list (2026-09-01): Caribbean + US/CA/GB + MX/SV/SN/KE.
EXPECTED_ALLOWLIST = frozenset(
	"JM TT BB BS DO KY AG DM GD KN LC VC BZ GY SR AW CW SX BM TC VG AI MS US CA GB MX SV SN KE PR VI GU AS MP".split()
)

ALPHA2 = re.compile(r"^[A-Z]{2}$")


def load_doctype():
	return json.loads((ALLOWED_COUNTRY_DIR / "allowed_country.json").read_text())


def load_seed_rows():
	# Import lazily: seed.py imports frappe at module level.
	try:
		import frappe
	except ImportError:
		sys.modules.setdefault("frappe", types.ModuleType("frappe"))
	from admin_panel.admin_panel.doctype.allowed_country.seed import SUPPORTED_COUNTRIES, all_seed_rows

	return SUPPORTED_COUNTRIES, all_seed_rows()


def test_doctype_defines_every_flash_contract_field():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	# The reader addresses the resource as "Allowed Country"; renaming it is
	# exactly as silent as a fieldname drift — flash would deny everyone.
	assert doctype["name"] == "Allowed Country"
	for fieldname in FLASH_CONTRACT_FIELDS:
		assert fieldname in fields, f"{fieldname} missing from Allowed Country"
		assert fieldname in doctype["field_order"]
	assert fields["flash_allowed"]["fieldtype"] == "Check"
	assert fields["alpha2_code"]["fieldtype"] == "Data"


def test_flash_allowed_defaults_off_and_tells_the_operator_what_it_gates():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}

	# Deny-unless-checked: a country an operator adds by hand must not be
	# allowed by accident.
	assert fields["flash_allowed"]["default"] == "0"
	assert fields["flash_allowed"]["in_list_view"] == 1
	assert fields["flash_allowed"]["in_standard_filter"] == 1
	description = fields["flash_allowed"]["description"]
	assert "Bridge KYC" in description
	assert "60s" in description
	# Operators toggle this; the audit trail has to survive.
	assert doctype["track_changes"] == 1
	# A settings list is scanned by name, not by last-modified.
	assert doctype["sort_field"] == "country_name"


def test_risk_tier_is_optional_so_territories_without_a_published_tier_can_exist():
	doctype = load_doctype()
	fields = {f["fieldname"]: f for f in doctype["fields"]}
	assert not fields["bridge_risk_tier"].get("reqd")


def test_allowlist_constant_is_exactly_the_operator_seed_list():
	assert BRIDGE_KYC_ALLOWLIST == EXPECTED_ALLOWLIST
	assert len(BRIDGE_KYC_ALLOWLIST) == 35
	# Haiti and Cuba are deliberately absent; India/Nigeria/Pakistan/Bangladesh
	# too (the 2026-09-01 wave, refused a USD virtual account after approval).
	for code in ("HT", "CU", "IN", "NG", "PK", "BD"):
		assert code not in BRIDGE_KYC_ALLOWLIST


def test_seed_rows_are_well_formed_and_cover_the_allowlist():
	supported, seed_rows = load_seed_rows()
	assert len(supported) == 168
	iso3 = [row["iso_code"] for row in seed_rows]
	assert len(iso3) == len(set(iso3)), "duplicate iso_code in seed data"
	for row in seed_rows:
		assert ALPHA2.match(row["alpha2_code"]), row
		assert row["country_name"]
		assert row["bridge_risk_tier"] in ("", "Restricted", "Not High Risk", "Controlled", "Prohibited")
		# The seed no longer decides the allowlist; only kyc_allowlist does.
		assert "flash_allowed" not in row
	alpha2 = {row["alpha2_code"] for row in seed_rows}
	missing = sorted(BRIDGE_KYC_ALLOWLIST - alpha2)
	assert not missing, f"allowlisted countries with no seed row (no checkbox to toggle): {missing}"
	for extra in ADDITIONAL_COUNTRIES:
		assert extra["alpha2_code"] in alpha2


@pytest.mark.parametrize(
	("code", "expected"), [("JM", 1), ("jm", 1), ("KE", 1), ("IN", 0), ("", 0), (None, 0)]
)
def test_flash_allowed_for(code, expected):
	assert flash_allowed_for(code) == expected


def _prod_like_state(seed_rows):
	"""Roughly today's prod: Bridge's 168 rows present, nearly all allowed,
	the territories missing, plus one operator-added row."""
	rows = {}
	for row in seed_rows:
		if row["alpha2_code"] in {
			"KY",
			"AW",
			"CW",
			"SX",
			"BM",
			"TC",
			"VG",
			"AI",
			"MS",
			"PK",
			"BD",
			"HT",
			"PR",
			"VI",
			"GU",
			"AS",
			"MP",
		}:
			continue  # not on prod yet
		rows[row["iso_code"]] = {**row, "flash_allowed": 0 if row["alpha2_code"] in {"BI", "JP", "TN"} else 1}
	rows["XKX"] = {
		"iso_code": "XKX",
		"alpha2_code": "XK",
		"country_name": "Kosovo (operator-added)",
		"bridge_risk_tier": "",
		"flash_allowed": 1,
	}
	return rows


def test_one_shot_reseed_converges_and_is_idempotent():
	_, seed_rows = load_seed_rows()
	state = _prod_like_state(seed_rows)

	inserts, updates = plan_reseed(state, seed_rows, apply_allowlist=True)
	assert {row["alpha2_code"] for row in inserts} == {
		"KY",
		"AW",
		"CW",
		"SX",
		"BM",
		"TC",
		"VG",
		"AI",
		"MS",
		"PK",
		"BD",
		"HT",
		"PR",
		"VI",
		"GU",
		"AS",
		"MP",
	}
	# Everything not on the allowlist is switched off, including the
	# operator-added row; allowlisted rows that were already 1 are untouched.
	assert updates["IND"]["flash_allowed"] == 0
	assert updates["NGA"]["flash_allowed"] == 0
	assert updates["XKX"]["flash_allowed"] == 0
	assert "JAM" not in updates
	assert "flash_allowed" not in updates.get("USA", {})

	after = apply_plan_to_rows(state, inserts, updates)
	allowed = {row["alpha2_code"] for row in after.values() if row["flash_allowed"] == 1}
	assert allowed == BRIDGE_KYC_ALLOWLIST

	# Second pass: nothing left to do.
	assert plan_reseed(after, seed_rows, apply_allowlist=True) == ([], {})


def test_every_migrate_seed_never_touches_an_operators_toggle():
	_, seed_rows = load_seed_rows()
	state = _prod_like_state(seed_rows)
	first_inserts, first_updates = plan_reseed(state, seed_rows, apply_allowlist=True)
	converged = apply_plan_to_rows(state, first_inserts, first_updates)

	# Operator later unchecks Kenya and checks India.
	converged["KEN"]["flash_allowed"] = 0
	converged["IND"]["flash_allowed"] = 1

	inserts, updates = plan_reseed(converged, seed_rows, apply_allowlist=False)
	assert inserts == []
	assert all("flash_allowed" not in changes for changes in updates.values())
	assert updates == {}

	# A renamed country still gets its descriptive fields refreshed — without
	# the allowlist being re-applied.
	converged["KEN"]["country_name"] = "Kenya (typo)"
	_, updates = plan_reseed(converged, seed_rows, apply_allowlist=False)
	assert updates == {"KEN": {"country_name": "Kenya"}}


def test_reseed_patch_is_registered_post_model_sync_and_wired_to_the_plan():
	patches = (ADMIN_PANEL / "patches.txt").read_text()
	post = patches.split("[post_model_sync]", 1)[1]
	assert "admin_panel.patches.reseed_bridge_kyc_allowlist" in post

	patch_src = (ADMIN_PANEL / "patches" / "reseed_bridge_kyc_allowlist.py").read_text()
	assert "apply_allowlist=True" in patch_src
	assert "write_plan(inserts, updates)" in patch_src

	# after_migrate must keep calling the seed, and the seed must be the
	# never-touch-flash_allowed variant.
	setup_src = (ADMIN_PANEL / "admin_panel" / "setup.py").read_text()
	assert "seed_allowed_countries()" in setup_src
	seed_src = (ALLOWED_COUNTRY_DIR / "seed.py").read_text()
	assert "apply_allowlist=False" in seed_src


def test_workspace_exposes_the_allowlist_as_a_settings_shortcut():
	ws = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
	shortcuts = {s["label"]: s for s in ws["shortcuts"]}
	assert "Bridge KYC Allowlist" in shortcuts
	shortcut = shortcuts["Bridge KYC Allowlist"]
	assert shortcut["link_to"] == "Allowed Country"
	assert shortcut["type"] == "DocType"
	assert json.loads(shortcut["stats_filter"]) == {"flash_allowed": 1}
	blocks = json.loads(ws["content"])
	assert any(
		b["type"] == "shortcut" and b["data"]["shortcut_name"] == "Bridge KYC Allowlist" for b in blocks
	), "shortcut row exists but is not placed on the workspace canvas"

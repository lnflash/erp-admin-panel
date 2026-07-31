"""Static contract checks for the Referral Rewards page.

Plain text/JSON assertions over the source files — no Frappe/mongo runtime.
Mirrors test_wallet_census_page_contract.py.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
PAGE_DIR = ADMIN_PANEL / "admin_panel" / "page" / "referral_rewards"


def read_text(path):
	return path.read_text()


def lines_above_def(source, def_name, count=5):
	return source.split(f"def {def_name}")[0].splitlines()[-count:]


def test_setup_registers_referral_rewards_page():
	setup_py = read_text(ADMIN_PANEL / "admin_panel" / "setup.py")

	assert '"name": "referral-rewards"' in setup_py
	assert '"title": "Referral Rewards"' in setup_py


def test_page_fixture_name_matches_page_name():
	page_json = json.loads((PAGE_DIR / "referral_rewards.json").read_text())

	assert page_json["name"] == "referral-rewards"
	assert page_json["page_name"] == "referral-rewards"
	assert page_json["standard"] == "Yes"


def test_endpoint_decorator_stack_and_gating():
	api_py = read_text(ADMIN_PANEL / "api" / "referral_rewards.py")

	assert "def get_referral_rewards" in api_py
	above = "\n".join(lines_above_def(api_py, "get_referral_rewards"))
	# exact order: whitelist -> require_admin -> handle_api_errors
	assert re.search(
		r"@frappe\.whitelist\(\)\s*\n\s*@require_admin\(\)\s*\n\s*@handle_api_errors",
		above,
	)


def test_js_wires_endpoint_and_gates_roles():
	js = read_text(PAGE_DIR / "referral_rewards.js")

	assert 'method: "admin_panel.api.referral_rewards.get_referral_rewards"' in js
	# role gate is present and up front (before the class is constructed)
	assert "RR_ALLOWED_ROLES" in js
	assert "Flash Admin" in js
	gate_idx = js.index("RR_ALLOWED_ROLES.some")
	construct_idx = js.index("new ReferralRewards(")
	assert gate_idx < construct_idx


def test_js_escapes_user_data():
	"""Every `${...}` interpolation of server data must be escaped or provably safe.

	Static sweep: an interpolation that references response/row data (r., d.,
	s., f., t., counts[, this.) must run through an escaping/formatting helper
	(esc / escape_html / rr_money / rr_ago / paidMark / Number) or be an
	explicitly reviewed numeric expression in the allowlist below. Adding e.g.
	`${r.contact}` unescaped fails this test.
	"""
	js = read_text(PAGE_DIR / "referral_rewards.js")
	assert "frappe.utils.escape_html" in js

	exprs = re.findall(r"\$\{(.*?)\}", js, re.DOTALL)
	assert len(exprs) > 20, "interpolation sweep found suspiciously few expressions"

	safe_calls = (
		"esc(",
		"frappe.utils.escape_html(",
		"rr_money(",
		"rr_ago(",
		"paidMark(",
		"Number(",
	)
	data_ref = re.compile(r"\b[rdfts]\.|counts\[|this\.")
	# Reviewed-safe raw interpolations: numeric server fields (never strings).
	allowed_numeric = {
		"f.count || 0",
		'f.conversion === null || f.conversion === undefined ? "&nbsp;" : f.conversion + "% of prev"',
		"counts[b.key] || 0",
		"s.rewarded || 0",
		"s.counter_seq || 0",
		"s.needs_reconciliation || 0",
		"s.partial || 0",
		"s.failed || 0",
		"s.pending || 0",
		"s.wallet_runway_referrals",
		"t.count_parties",
	}
	for expr in exprs:
		norm = " ".join(expr.split())
		if not data_ref.search(norm):
			continue
		if any(call in norm for call in safe_calls):
			continue
		assert norm in allowed_numeric, f"unescaped data interpolation: ${{{norm}}}"


def test_js_relative_time_uses_server_clock_not_local():
	js = read_text(PAGE_DIR / "referral_rewards.js")
	# The relative-time helper must not read the viewer's clock.
	assert "Date.now()" not in js
	assert "new Date(" not in js
	assert "function rr_ago" in js


def test_js_css_is_scoped_to_the_page():
	js = read_text(PAGE_DIR / "referral_rewards.js")
	m = re.search(r"const RR_CSS = `(.*?)`;", js, re.DOTALL)
	assert m, "RR_CSS block not found"
	css = m.group(1)
	for line in css.splitlines():
		if "{" not in line:
			continue
		stripped = line.strip()
		# allow at-rules (none currently, but future-proof)
		if stripped.startswith("@") or stripped.startswith("}"):
			continue
		assert "referral-rewards-page" in line, f"unscoped CSS selector: {stripped}"


def test_workspace_links_referral_rewards_once():
	workspace = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
	ws = workspace[0] if isinstance(workspace, list) else workspace
	links = [l for l in ws["links"] if l.get("link_to") == "referral-rewards"]

	assert len(links) == 1
	assert links[0]["link_type"] == "Page"
	assert links[0]["label"] == "Referral Rewards"


def test_core_module_has_no_frappe_or_pymongo_imports():
	core = read_text(ADMIN_PANEL / "api" / "referral_rewards_core.py")
	assert "import frappe" not in core
	assert "pymongo" not in core
	assert "import requests" not in core

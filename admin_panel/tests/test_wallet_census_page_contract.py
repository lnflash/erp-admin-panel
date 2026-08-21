import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_PANEL = REPO_ROOT / "admin_panel"
PAGE_DIR = ADMIN_PANEL / "admin_panel" / "page" / "wallet_census"
DOCTYPE_DIR = ADMIN_PANEL / "admin_panel" / "doctype" / "wallet_census_snapshot"


def read_text(path):
	return path.read_text()


def lines_above_def(source, def_name, count=5):
	return source.split(f"def {def_name}")[0].splitlines()[-count:]


def test_setup_registers_wallet_census_page():
	setup_py = read_text(ADMIN_PANEL / "admin_panel" / "setup.py")

	assert '"name": "wallet-census"' in setup_py
	assert '"title": "Wallet Census"' in setup_py


def test_wallet_census_page_fixture_name_matches_page_name():
	page_json = json.loads((PAGE_DIR / "wallet_census.json").read_text())

	assert page_json["name"] == "wallet-census"
	assert page_json["page_name"] == "wallet-census"


def test_snapshot_doctype_does_not_track_changes():
	doctype_json = json.loads((DOCTYPE_DIR / "wallet_census_snapshot.json").read_text())

	assert doctype_json["track_changes"] == 0


def test_run_census_now_is_bench_execute_only_while_start_census_is_whitelisted():
	census_py = read_text(ADMIN_PANEL / "api" / "census.py")

	# run_census_now blocks the caller for the full scan — it must never grow
	# a whitelist decorator. start_census is the whitelisted (queued) path.
	assert "def run_census_now" in census_py
	assert "@frappe.whitelist()" not in "\n".join(lines_above_def(census_py, "run_census_now"))
	assert "def start_census" in census_py
	assert "@frappe.whitelist()" in "\n".join(lines_above_def(census_py, "start_census"))


def test_census_defines_stale_run_and_retention_constants():
	census_py = read_text(ADMIN_PANEL / "api" / "census.py")

	assert "STALE_RUN_SECONDS" in census_py
	assert "KEEP_SNAPSHOTS" in census_py


def test_wallet_census_js_gates_roles_pages_rows_and_guards_csv_formulas():
	js = read_text(PAGE_DIR / "wallet_census.js")

	assert "WC_ALLOWED_ROLES" in js
	assert "Flash Admin" in js
	assert r"^[=+\-@]" in js
	assert "Show all" in js


def test_customer_detail_caps_tx_limit():
	customer_py = read_text(ADMIN_PANEL / "api" / "customer.py")

	assert "cint(tx_limit)" in customer_py


def test_admin_dashboard_has_wallet_census_card():
	"""Tiles come from the nav registry, not from markup in the page."""
	from admin_panel.api.nav_core import by_route

	link = by_route()["wallet-census"]

	assert link["kind"] == "page"
	assert link["label"] == "Wallet Census"


def test_workspace_links_include_wallet_census_page():
	workspace = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
	ws = workspace[0] if isinstance(workspace, list) else workspace
	links = [l for l in ws["links"] if l.get("link_to") == "wallet-census"]

	assert len(links) == 1
	assert links[0]["link_type"] == "Page"
	assert links[0]["label"] == "Wallet Census"


def test_pulse_endpoint_is_admin_gated():
	pulse_py = (ADMIN_PANEL / "api" / "pulse.py").read_text()

	assert "@frappe.whitelist()" in pulse_py
	assert "@require_admin()" in pulse_py
	assert "@handle_api_errors" in pulse_py
	assert "def get_dashboard_pulse" in pulse_py
	# never ship the heavy rows payload from the pulse
	assert "rows_json" not in pulse_py


def test_dashboard_renders_pulse_layer():
	js = (ADMIN_PANEL / "admin_panel" / "page" / "admin_dashboard" / "admin_dashboard.js").read_text()

	assert "admin_panel.api.pulse.get_dashboard_pulse" in js
	assert 'id="fp-trend"' in js
	assert "USDT float" in js
	assert "Cashouts needing action" in js
	# existing flows preserved
	assert "admin_panel.api.admin_api.get_dashboard_stats" in js
	assert "account_hub_query" in js
	assert "ad-smart-search" in js
	# hash hrefs get eaten by the desk router ("Page #x not found") — tiles
	# must use data-scroll or /app/ routes
	assert 'href="#fp-' not in js

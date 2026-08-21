"""Contract tests for the bridge-kyc page + API wiring.

Plain-text assertions over source files (no frappe import) — same convention
as the other *_page_contract tests.
"""

import json
import re
from pathlib import Path

ADMIN_PANEL = Path(__file__).resolve().parents[1]
API = ADMIN_PANEL / "api"
PAGE = ADMIN_PANEL / "admin_panel" / "page" / "bridge_kyc"


def read(path):
	return path.read_text()


BRIDGE_KYC_PY = read(API / "bridge_kyc.py")
BRIDGE_CLIENT_PY = read(API / "bridge_client.py")
COMMON_PY = read(API / "common.py")
PAGE_JS = read(PAGE / "bridge_kyc.js")
PAGE_JSON = json.loads(read(PAGE / "bridge_kyc.json"))
WORKSPACE = json.loads(read(ADMIN_PANEL / "fixtures" / "workspace.json"))


def test_endpoints_are_whitelisted_and_admin_gated():
	"""Both endpoints carry the full decorator stack, in order — whitelist
	alone would expose customer KYC PII to any logged-in user."""
	for fn in ("get_kyc_overview", "get_kyc_customer"):
		stack = f"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef {fn}("
		assert stack in BRIDGE_KYC_PY, f"{fn} is missing the whitelist/require_admin/handle_api_errors stack"


def test_bridge_client_is_read_only():
	"""The Bridge client must never grow a write — KYC state is owned by the
	flash backend + Bridge dashboard, this page only observes it."""
	assert "def _post" not in BRIDGE_CLIENT_PY
	assert ".post(" not in BRIDGE_CLIENT_PY
	assert ".put(" not in BRIDGE_CLIENT_PY
	assert ".delete(" not in BRIDGE_CLIENT_PY


def test_pagination_terminates_only_on_empty_page():
	"""Short pages are NOT proof of the end (the IBEX hub silently caps page
	sizes and short-page inference truncated the first wallet census)."""
	assert "if not batch:" in BRIDGE_CLIENT_PY
	assert "MAX_PAGES" in BRIDGE_CLIENT_PY
	assert not re.search(
		r"len\(batch\)\s*<", BRIDGE_CLIENT_PY
	), "bridge_client must not infer end-of-data from a short page"
	assert "< PAGE_LIMIT" not in BRIDGE_CLIENT_PY


def test_common_error_handler_catches_bridge_errors():
	"""BridgeApiError must map to the {"success": False} envelope, not a
	masked 'internal error'."""
	assert "from .bridge_client import BridgeApiError" in COMMON_PY
	assert "BridgeApiError" in COMMON_PY.split("except (GraphQLError", 1)[1].split(")")[0]


def test_js_wires_the_bridge_kyc_endpoints():
	assert 'method: "admin_panel.api.bridge_kyc.get_kyc_overview"' in PAGE_JS
	assert 'method: "admin_panel.api.bridge_kyc.get_kyc_customer"' in PAGE_JS


def test_js_role_gates_up_front():
	assert "BK_VIEW_ROLES" in PAGE_JS
	assert "frappe.user_roles.includes(r)" in PAGE_JS
	assert "Access Denied" in PAGE_JS


def test_js_age_math_uses_server_clock():
	"""Ages are computed from the server-provided `now`, never the browser
	clock (tz skew + WebKit non-ISO parsing burned the pulse pages)."""
	assert "function bkAgo(iso, nowIso)" in PAGE_JS
	assert "Date.now" not in PAGE_JS
	assert "new Date()" not in PAGE_JS


def test_js_escapes_untrusted_strings():
	"""Customer names/emails come from Bridge (user-entered) — everything
	interpolated into HTML must run through the escaper."""
	assert "frappe.utils.escape_html" in PAGE_JS


def test_page_css_stays_scoped():
	"""Every CSS rule must be scoped under .bridge-kyc-page so styles cannot
	bleed into other desk pages (the account_management lesson)."""
	css = PAGE_JS.split("const BK_CSS = `", 1)[1].split("`;", 1)[0]
	for line in css.splitlines():
		stripped = line.strip()
		if not stripped or stripped.startswith(("@", "}", "--", "/*")):
			continue
		if "{" not in stripped or stripped.index("{") == 0:
			continue
		selector = stripped.split("{", 1)[0].strip()
		if not selector or selector.startswith(("from", "to", "0%", "100%")):
			continue
		assert ".bridge-kyc-page" in selector, f"unscoped CSS selector: {selector}"
	assert ".modern-" not in css, "reuse of global .modern-* classes must stay scoped"
	assert ".form-control" not in css


def test_page_json_registration():
	assert PAGE_JSON["doctype"] == "Page"
	assert PAGE_JSON["module"] == "Admin Panel"
	assert PAGE_JSON["name"] == "bridge-kyc"
	assert PAGE_JSON["page_name"] == "bridge-kyc"
	assert PAGE_JSON["standard"] == "Yes"


def test_workspace_links_the_page():
	workspace = WORKSPACE[0] if isinstance(WORKSPACE, list) else WORKSPACE
	links = [l for l in workspace.get("links", []) if l.get("link_to") == "bridge-kyc"]
	assert len(links) == 1, "bridge-kyc must appear exactly once in the workspace links"
	assert links[0]["link_type"] == "Page"
	assert links[0]["label"] == "Bridge KYC"


def test_customer_id_is_validated_and_percent_encoded():
	"""customer_id comes from the browser and ends up in a URL path — without
	UUID validation + percent-encoding, `x?limit=` or `../transfers` turns the
	detail endpoint into a GET proxy for arbitrary Bridge API paths."""
	assert "CUSTOMER_ID_RE = re.compile(" in BRIDGE_CLIENT_PY
	assert "CUSTOMER_ID_RE.fullmatch(customer_id)" in BRIDGE_KYC_PY
	assert "quote(str(customer_id), safe='')" in BRIDGE_CLIENT_PY.replace('"', "'")


def test_detail_drawer_shows_linked_flash_accounts():
	"""The shared-link data smell must survive into the detail drawer, not
	just the table chip — the drawer is where an operator investigates."""
	assert "detail_html(d.customer, overviewRow)" in PAGE_JS
	assert "Linked Flash account" in PAGE_JS
	assert "shared link" in PAGE_JS


def test_api_key_never_reaches_the_client():
	"""The Bridge API key stays server-side: the JS must never reference it and
	the overview/detail payloads are built from explicit whitelisted fields."""
	assert "bridge_api_key" not in PAGE_JS
	assert "api_key" not in PAGE_JS


def test_admin_dashboard_tools_grid_links_the_page():
	"""Tiles come from the nav registry, not from markup in the page."""
	from admin_panel.api.nav_core import by_route

	link = by_route()["bridge-kyc"]

	assert link["kind"] == "page"
	assert link["label"] == "Bridge KYC"

"""Contract tests for the Admin Dashboard as the desk landing page.

The dashboard's tile markup used to be its own registry: six hand-written
cards in ``admin_dashboard.js``. Four features shipped past it (Treasury
Funding, Fee Discount, Fygaro Settings, Referral Rewards) and the grid never
moved, because nothing in the build could tell that it hadn't. These tests
are that missing signal — the anti-drift pair below fails as soon as a page
or doctype exists without a decision recorded about it.
"""

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.nav_core import (
	FREQUENT_LIMIT,
	NAV_GROUPS,
	UNLISTED,
	all_links,
	by_route,
	normalize_route,
	rank_frequent,
)

ADMIN_PANEL = REPO_ROOT / "admin_panel"
DASHBOARD_JS = (ADMIN_PANEL / "admin_panel" / "page" / "admin_dashboard" / "admin_dashboard.js").read_text()
SETUP_PY = (ADMIN_PANEL / "admin_panel" / "setup.py").read_text()
AUTH_PY = (ADMIN_PANEL / "api" / "auth.py").read_text()
NAV_PY = (ADMIN_PANEL / "api" / "nav.py").read_text()
REVENUE_PY = (ADMIN_PANEL / "api" / "revenue.py").read_text()
WORKSPACE = json.loads((ADMIN_PANEL / "fixtures" / "workspace.json").read_text())
DASHBOARD_PAGE = json.loads(
	(ADMIN_PANEL / "admin_panel" / "page" / "admin_dashboard" / "admin_dashboard.json").read_text()
)


def synced_pages():
	"""The page dicts that ``setup.sync_pages`` registers."""
	fn = next(
		node
		for node in ast.walk(ast.parse(SETUP_PY))
		if isinstance(node, ast.FunctionDef) and node.name == "sync_pages"
	)
	assign = next(node for node in fn.body if isinstance(node, ast.Assign))
	return ast.literal_eval(assign.value)


def app_doctypes():
	doctype_dir = ADMIN_PANEL / "admin_panel" / "doctype"
	names = []
	for child in sorted(doctype_dir.iterdir()):
		definition = child / f"{child.name}.json"
		if definition.exists():
			names.append(json.loads(definition.read_text())["name"])
	return names


# ── anti-drift: the reason this file exists ───────────────────────────────


def test_every_registered_page_is_on_the_dashboard_or_explicitly_unlisted():
	routes = set(by_route()) | set(UNLISTED)
	missing = [p["name"] for p in synced_pages() if p["name"] not in routes]

	assert not missing, (
		f"{missing} are registered in setup.sync_pages but absent from the dashboard. "
		"Add each to nav_core.NAV_GROUPS, or to UNLISTED with the reason it has no tile."
	)


def test_every_app_doctype_is_on_the_dashboard_or_explicitly_unlisted():
	routes = set(by_route()) | set(UNLISTED)
	missing = [name for name in app_doctypes() if name.lower().replace(" ", "-") not in routes]

	assert not missing, (
		f"{missing} are doctypes in this app but absent from the dashboard. "
		"Add each to nav_core.NAV_GROUPS, or to UNLISTED with the reason it has no tile."
	)


def test_registry_entries_are_complete_and_unique():
	links = all_links()
	routes = [link["route"] for link in links]

	assert len(routes) == len(set(routes)), "duplicate route in NAV_GROUPS"
	for link in links:
		assert link["label"] and link["desc"], f"{link['route']} needs a label and a description"
		# The badge is the tile's icon; two characters is what the 34px
		# .ad-tool-icon square fits without clipping.
		assert len(link["badge"]) == 2, f"{link['route']} badge must be two characters"
		assert link["kind"] in ("page", "doctype")
		if link["kind"] == "doctype":
			assert link["route"] == link["doctype"].lower().replace(" ", "-")


def test_workspace_sidebar_lists_every_dashboard_destination():
	"""The sidebar and the dashboard must not drift apart either."""
	linked = {row.get("link_to") for row in WORKSPACE["links"] if row.get("type") == "Link"}
	missing = [
		link["doctype"] if link["kind"] == "doctype" else link["route"]
		for link in all_links()
		if (link["doctype"] if link["kind"] == "doctype" else link["route"]) not in linked
	]

	assert not missing, f"{missing} are on the dashboard but missing from the workspace fixture"


def test_workspace_cards_match_the_registry_groups():
	breaks = [row["label"] for row in WORKSPACE["links"] if row.get("type") == "Card Break"]
	cards = [
		block["data"]["card_name"] for block in json.loads(WORKSPACE["content"]) if block["type"] == "card"
	]

	assert breaks == [group["title"] for group in NAV_GROUPS]
	# A content card naming a card break that does not exist renders empty.
	assert cards == breaks


# ── frequently-used ranking ───────────────────────────────────────────────


def test_normalize_route_folds_doctype_views_onto_one_destination():
	assert normalize_route("List/Cashout/List") == "cashout"
	assert normalize_route("List/Bridge Transfer Request/Report") == "bridge-transfer-request"
	assert normalize_route("Tree/Allowed Country") == "allowed-country"
	assert normalize_route("transfer-requests") == "transfer-requests"


def test_normalize_route_rejects_what_is_not_a_destination():
	assert normalize_route("Workspaces/Admin Panel") is None
	assert normalize_route("Form/Cashout/CO-0001") is None
	assert normalize_route("") is None
	assert normalize_route(None) is None
	# A doctype prefix with nothing after it is not a destination either.
	assert normalize_route("List") is None


def test_rank_frequent_sums_hits_across_views_of_one_destination():
	"""List, Report and the bare route are the same tile — hits must add up,
	or a doctype the operator lives in loses to one they open once a week."""
	known = by_route()
	ranked = rank_frequent(
		[
			{"route": "List/Cashout/List", "hits": 5},
			{"route": "List/Cashout/Report", "hits": 4},
			{"route": "account-hub", "hits": 7},
		],
		known,
	)

	assert [link["route"] for link in ranked] == ["cashout", "account-hub"]
	assert ranked[0]["hits"] == 9


def test_rank_frequent_drops_unknown_routes_and_honours_the_limit():
	known = by_route()
	rows = [{"route": link["route"], "hits": 100 - i} for i, link in enumerate(all_links())]
	rows.append({"route": "List/User/List", "hits": 9999})

	ranked = rank_frequent(rows, known)

	assert len(ranked) == FREQUENT_LIMIT
	assert all(link["route"] in known for link in ranked)


def test_rank_frequent_breaks_ties_on_label_so_the_strip_is_stable():
	known = by_route()
	rows = [{"route": "cashout", "hits": 3}, {"route": "account-hub", "hits": 3}]

	assert [link["route"] for link in rank_frequent(rows, known)] == ["account-hub", "cashout"]


def test_rank_frequent_tolerates_null_hit_counts():
	assert rank_frequent([{"route": "cashout", "hits": None}], by_route())[0]["hits"] == 0


# ── endpoint gating ───────────────────────────────────────────────────────


def test_nav_endpoints_are_whitelisted_and_admin_gated():
	for fn in ("get_nav", "record_visit"):
		stack = f"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef {fn}("
		assert stack in NAV_PY, f"{fn} is missing the whitelist/require_admin/handle_api_errors stack"


def test_revenue_endpoint_is_whitelisted_and_admin_gated():
	stack = "@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef get_revenue_summary("
	assert stack in REVENUE_PY


def test_revenue_counts_only_settled_money():
	"""A pending cashout has not earned its fee yet, and a cancelled document
	(docstatus 2) never will."""
	assert 'REVENUE_CASHOUT_STATUS = "Completed"' in REVENUE_PY
	assert "cashout.docstatus < 2" in REVENUE_PY
	assert "cashout.status == REVENUE_CASHOUT_STATUS" in REVENUE_PY


def test_revenue_reads_card_fees_only_from_fygaro():
	"""Bridge transfers carry no fee breakdown; including them would add a
	column of empty strings to the pending count for no reason."""
	assert 'REVENUE_TOPUP_PROVIDER = "Fygaro"' in REVENUE_PY
	assert "provider = %(provider)s" in REVENUE_PY


def test_revenue_counts_both_terminal_fygaro_success_statuses():
	"""fygaro_topup_core names BOTH Completed and Settled as terminal Fygaro
	statuses — the operator Complete action stamps one, webhook settlement
	lands at the other — and the fee is revenue either way. Filtering on a
	single status silently drops every Settled row's fee: the exact
	understatement this dashboard exists to prevent, one status value over."""
	assert 'REVENUE_TOPUP_STATUSES = ("Completed", "Settled")' in REVENUE_PY
	assert "status IN %(statuses)s" in REVENUE_PY


def test_card_fees_are_aggregated_in_sql_behind_the_numeric_guard():
	"""The dashboard is the desk landing page and top-up rows grow without
	bound, so the fees must be aggregated server-side — but a bare SUM over
	the Data-typed flash_fee column casts empty and garbage strings to 0,
	which is precisely the silent understatement revenue_core exists to
	prevent. Every sum of the column therefore goes through FEE_SQL's
	REGEXP guard, and the rows the guard rejects surface as fee_pending."""
	# No unguarded aggregation of the Data column anywhere in the module.
	assert "Sum(flash_fee" not in REVENUE_PY
	assert "SUM(flash_fee" not in REVENUE_PY
	assert "frappe.get_all(" not in REVENUE_PY, "top-up rows must be aggregated in SQL, not fetched"
	assert "REGEXP %(fee_pattern)s" in REVENUE_PY
	# Both the match and the cast must strip the SAME whitespace set: TRIM()
	# strips only spaces, so a TRIM-based cast would diverge from the
	# [[:space:]] rule coerce_fee mirrors (e.g. "1.25\t").
	assert "REGEXP_REPLACE(flash_fee, '^[[:space:]]+|[[:space:]]+$', '')" in REVENUE_PY
	assert "CAST(TRIM(flash_fee)" not in REVENUE_PY
	assert "FEE_PATTERN_SQL" in REVENUE_PY

	topup_block = REVENUE_PY[REVENUE_PY.index("def _topup_fees") :]
	assert "SUM({FEE_SQL})" in topup_block
	assert "COUNT(*) - COUNT({FEE_SQL})" in topup_block


def test_topup_windows_are_half_open_like_the_cashout_ones():
	"""Both revenue lines must window creation the same way — inclusive
	start, exclusive end, exactly revenue_core.in_window — or the two lines
	of one tile could disagree about a boundary row."""
	topup_block = REVENUE_PY[REVENUE_PY.index("def _topup_fees") :]
	assert "creation >= %(start)s" in topup_block
	assert "creation < %(end)s" in topup_block


def test_record_visit_only_accepts_registry_routes():
	"""record_visit writes into a shared core table; an unvalidated route
	would let any admin-role caller inject arbitrary rows into it."""
	assert "if normalize_route(route) not in by_route():" in NAV_PY
	assert '{"recorded": False}' in NAV_PY


# ── the page itself ───────────────────────────────────────────────────────


def test_dashboard_role_gate_matches_the_api_gate():
	"""The page is the desk landing page. A gate narrower than ADMIN_ROLES
	greets a Flash Admin with Access Denied on a page whose data every
	endpoint behind it would happily have served them."""
	admin_roles = ast.literal_eval(
		next(
			line.split("=", 1)[1].strip() for line in AUTH_PY.splitlines() if line.startswith("ADMIN_ROLES =")
		)
	)

	assert f"const ADMIN_ROLES = {json.dumps(admin_roles)};" in DASHBOARD_JS
	assert "ADMIN_ROLES.some((role) => frappe.user_roles.includes(role))" in DASHBOARD_JS
	assert 'frappe.user_roles.includes("Accounts Manager")' not in DASHBOARD_JS


def test_dashboard_renders_tiles_from_the_registry_not_from_markup():
	"""No hand-written tile may come back: that is the drift this fixes."""
	assert 'method: "admin_panel.api.nav.get_nav"' in DASHBOARD_JS
	assert 'id="ad-directory"' in DASHBOARD_JS
	# A tile title interpolates its label; a literal one is hand-written markup.
	assert not re.search(r'ad-tool-title">[A-Za-z]', DASHBOARD_JS)
	assert not re.search(r'data-route="/app/', DASHBOARD_JS)


def test_dashboard_wires_revenue_at_the_top():
	revenue_at = DASHBOARD_JS.index('id="ad-revenue"')
	pulse_at = DASHBOARD_JS.index('id="fp-pulse"')

	assert 'method: "admin_panel.api.revenue.get_revenue_summary"' in DASHBOARD_JS
	assert revenue_at < pulse_at, "revenue must render above the ops pulse"


def test_dashboard_discloses_what_the_revenue_total_excludes():
	"""An understated total that looks precise is worse than no total."""
	assert "fee_pending" in DASHBOARD_JS
	assert "other_currency" in DASHBOARD_JS
	assert "excluded, not counted as zero" in DASHBOARD_JS


def test_tile_clicks_are_delegated_and_recorded():
	"""Tiles render after the shell, so a .find() binding at shell time would
	catch none of them."""
	assert '$m.on("click", ".ad-tool-card, .ad-freqchip"' in DASHBOARD_JS
	assert 'method: "admin_panel.api.nav.record_visit"' in DASHBOARD_JS


def test_dashboard_css_stays_scoped_to_the_page():
	"""Desk keeps page wrappers in the DOM; an unscoped rule restyles every
	other desk page for as long as this one has been visited."""
	css = DASHBOARD_JS[DASHBOARD_JS.index("const FP_CSS = `") : DASHBOARD_JS.index("class OpsDashboard")]
	for line in css.splitlines():
		stripped = line.strip()
		if "{" not in stripped:
			continue
		selector = stripped.split("{")[0].strip()
		if not selector or selector.startswith(("@", "}", "/*", "*", "to ", "from ")):
			continue
		assert selector.startswith((".fp", "[data-theme=", ".dark")), f"unscoped selector: {selector}"


# ── back-to-dashboard button ──────────────────────────────────────────────

BACK_JS = (ADMIN_PANEL / "public" / "js" / "back_to_dashboard.js").read_text()
HOOKS_PY = (ADMIN_PANEL / "hooks.py").read_text()


def _js_string_array(source, name):
	"""The string literals of a ``const NAME = [ ... ];`` block."""
	block = re.search(rf"const {name} = \[(.*?)\];", source, re.DOTALL)
	assert block, f"const {name} missing from back_to_dashboard.js"
	return re.findall(r'"([^"]+)"', block.group(1))


def test_back_button_covers_every_dashboard_destination():
	"""The include script is one file so a new destination cannot ship
	without the button — but only while these lists track the registry."""
	links = all_links()

	assert _js_string_array(BACK_JS, "PAGES") == [link["route"] for link in links if link["kind"] == "page"]
	assert _js_string_array(BACK_JS, "DOCTYPES") == [
		link["doctype"] for link in links if link["kind"] == "doctype"
	]


def test_back_button_script_is_included_desk_wide_and_skips_the_dashboard():
	assert 'app_include_js = "/assets/admin_panel/js/back_to_dashboard.js"' in HOOKS_PY
	# No button to itself: the dashboard's own route must not be a target.
	assert '"admin-dashboard"' not in re.search(r"const PAGES = \[.*?\];", BACK_JS, re.DOTALL).group(0)
	# Navigation must go through the router, not a page reload.
	assert 'frappe.set_route("admin-dashboard")' in BACK_JS
	# Injection must hang off the container's "page-change" (fired AFTER
	# frappe.container.page is updated), never frappe.router.on("change"),
	# which fires while an async custom-Page render is still in flight and
	# would inject the button into the page being LEFT — including the
	# dashboard itself.
	assert '$(document).on("page-change"' in BACK_JS
	assert 'frappe.router.on("change"' not in BACK_JS


# ── desk landing page ─────────────────────────────────────────────────────


def test_after_migrate_sets_the_desk_home_page():
	assert "ensure_desk_home_page()" in SETUP_PY
	# boot.add_home_page reads this exact global default and falls back to the
	# Workspaces view when the Page does not exist or is not permitted.
	assert 'frappe.db.set_default("desktop:home_page", configured)' in SETUP_PY
	assert 'DESK_HOME_PAGE = "admin-dashboard"' in SETUP_PY


def test_desk_home_page_is_overridable_and_converges_quietly():
	assert 'frappe.conf.get("desk_home_page", DESK_HOME_PAGE)' in SETUP_PY
	# Already-correct sites must be a no-op, not a write on every migrate.
	assert "if current == configured:" in SETUP_PY


def test_desk_home_page_opt_out_undoes_a_previously_set_default():
	"""Merely skipping the write is not an opt-out: on any site that migrated
	once, the default is already set and admins would keep landing on the
	dashboard forever. Only our own value may be cleared — an operator's
	hand-picked home page is not ours to remove."""
	assert "if current == DESK_HOME_PAGE:" in SETUP_PY
	assert 'frappe.defaults.clear_default("desktop:home_page", parent="__default")' in SETUP_PY


def test_dashboard_page_is_role_gated_so_others_keep_their_landing_page():
	"""The role gate on the Page IS the opt-out: boot falls back to Workspaces
	on PermissionError, so no separate exclusion list has to be maintained."""
	dashboard = next(p for p in synced_pages() if p["name"] == "admin-dashboard")
	admin_roles = ast.literal_eval(
		next(
			line.split("=", 1)[1].strip() for line in AUTH_PY.splitlines() if line.startswith("ADMIN_ROLES =")
		)
	)

	assert [row["role"] for row in dashboard["roles"]] == admin_roles
	# The Page JSON is what `bench migrate` file-syncs BEFORE after_migrate
	# runs; if only setup.py carried the roles, every migrate would blank them
	# and re-add them, and any code reading the Page in between would see an
	# ungated landing page.
	assert [row["role"] for row in DASHBOARD_PAGE["roles"]] == admin_roles
	# ...but the file only syncs at all when its "modified" stamp is newer
	# than the DB row's. The roles were added after the page first shipped, so
	# a "modified" still equal to "creation" means every existing site skips
	# the file and the rationale above is only true on fresh installs. Bump
	# "modified" whenever this JSON changes.
	assert DASHBOARD_PAGE["modified"] > DASHBOARD_PAGE["creation"], (
		"admin_dashboard.json changed without bumping 'modified' — "
		"bench migrate will skip file-syncing it on existing sites"
	)


def test_every_dashboard_page_destination_is_registered_for_sync():
	"""A tile pointing at a Page that setup never creates is a dead tile."""
	synced = {p["name"] for p in synced_pages()}
	missing = [
		link["route"] for link in all_links() if link["kind"] == "page" and link["route"] not in synced
	]

	assert not missing, f"{missing} have dashboard tiles but are not registered in setup.sync_pages"

"""Pure navigation registry for the Admin Dashboard — no Frappe runtime.

One list, in one place, of every destination the admin panel ships. The
dashboard renders its link directory straight from this registry, so a new
page or doctype appears on the dashboard the moment it is registered here
instead of drifting until someone remembers to hand-edit tile markup. The
tile markup used to BE the registry, which is exactly how the dashboard fell
behind Treasury Funding, Fee Discount, Fygaro Settings and Referral Rewards.

``test_admin_dashboard_nav_contract`` fails the build when a page in
``setup.sync_pages`` or a doctype in the app is missing from ``NAV_GROUPS``
and from ``UNLISTED``, which is what keeps "one place" true.
"""

# How many tiles the "Frequently used" strip shows.
FREQUENT_LIMIT = 6

# Route History is ranked over this trailing window, so the strip tracks what
# the operator uses *now* rather than what they hammered six months ago.
FREQUENT_WINDOW_DAYS = 60

# Desk route prefixes that carry a doctype in their second segment.
DOCTYPE_ROUTE_PREFIXES = ("List", "Tree", "Report", "Dashboard")

# Prefixes that never map onto a registry destination.
IGNORED_ROUTE_PREFIXES = ("Workspaces", "Form", "query-report", "dashboard-view")


def _page(label, route, badge, desc):
	return {"label": label, "route": route, "kind": "page", "badge": badge, "desc": desc}


def _doctype(label, doctype, badge, desc):
	return {
		"label": label,
		"route": doctype.lower().replace(" ", "-"),
		"kind": "doctype",
		"doctype": doctype,
		"badge": badge,
		"desc": desc,
	}


NAV_GROUPS = (
	{
		"title": "Money movement",
		"links": (
			_page(
				"Transfer Requests",
				"transfer-requests",
				"TR",
				"Cashout, Bridge and Fygaro settlement queue",
			),
			_page(
				"System Accounts",
				"system-accounts",
				"SA",
				"Treasury balances and role-wallet funding",
			),
			_doctype("Cashout", "Cashout", "CO", "Every cashout record and its journal entries"),
			_doctype(
				"Bridge Transfer Request",
				"Bridge Transfer Request",
				"BT",
				"Raw Bridge and Fygaro top-up rows",
			),
		),
	},
	{
		"title": "Accounts",
		"links": (
			_page("Account Hub", "account-hub", "AH", "Search, inspect and manage any account"),
			_page(
				"Account Management",
				"account-management",
				"AM",
				"Levels, locks and merchant validation",
			),
			_page("Wallet Census", "wallet-census", "WC", "Live IBEX balances, buckets and CSV export"),
			_doctype(
				"Account Upgrade Request",
				"Account Upgrade Request",
				"UR",
				"Level-upgrade queue and its decision history",
			),
			_doctype(
				"Bank Account Update Request",
				"Bank Account Update Request",
				"BA",
				"Customer bank-detail changes awaiting review",
			),
			_doctype(
				"Wallet Census Snapshot",
				"Wallet Census Snapshot",
				"CS",
				"Past census runs and their totals",
			),
		),
	},
	{
		"title": "Growth",
		"links": (
			_page("Referral Rewards", "referral-rewards", "RR", "Referral payouts and reward ledger"),
			_page("Alert Users", "alert-users", "AL", "Broadcast or per-user email and push alerts"),
			_doctype("User Alerts", "User Alerts", "UA", "Alert history and delivery audit trail"),
			_doctype("Fee Discount", "Fee Discount", "FD", "Per-user percentage off the Flash fee"),
		),
	},
	{
		"title": "Compliance",
		"links": (
			_page("Bridge KYC", "bridge-kyc", "BK", "Live Bridge KYC status for every customer"),
			_doctype("Allowed Country", "Allowed Country", "AC", "Countries cleared for onboarding"),
			_doctype("System Watchlist", "System Watchlist", "SW", "Flagged wallets under active watch"),
		),
	},
	{
		"title": "Settings and audit",
		"links": (
			_doctype(
				"Fygaro Settings",
				"Fygaro Settings",
				"FS",
				"Card top-up toggles and per-level daily limits",
			),
			_doctype("Cashout Settings", "Cashout Settings", "CC", "Cashout fees, rates and limits"),
			_doctype(
				"System Funding Log",
				"System Funding Log",
				"FL",
				"Every treasury funding transaction",
			),
			_doctype(
				"System Transfer Log",
				"System Transfer Log",
				"TL",
				"System-wallet transfer audit trail",
			),
		),
	},
)

# Destinations that deliberately have no dashboard tile, each with its reason.
# The anti-drift test reads this, so a new page or doctype forces a decision
# here or in NAV_GROUPS instead of silently going missing.
UNLISTED = {
	"admin-dashboard": "This page. The directory does not list itself.",
}


def all_links():
	"""Every registry link, flattened, in display order."""
	return [link for group in NAV_GROUPS for link in group["links"]]


def by_route():
	return {link["route"]: link for link in all_links()}


def normalize_route(route):
	"""Map a Route History route string onto a registry route.

	``List/Cashout/List`` -> ``cashout``; ``transfer-requests`` -> itself;
	workspace and form routes -> ``None``.
	"""
	parts = [p for p in (route or "").split("/") if p]
	if not parts:
		return None
	if parts[0] in DOCTYPE_ROUTE_PREFIXES:
		return parts[1].lower().replace(" ", "-") if len(parts) > 1 else None
	if parts[0] in IGNORED_ROUTE_PREFIXES:
		return None
	return parts[0]


def rank_frequent(rows, known, limit=FREQUENT_LIMIT):
	"""Collapse raw Route History rows onto registry links, most-used first.

	``rows`` are ``{"route", "hits"}`` dicts. Several raw routes fold onto one
	destination (``cashout``, ``List/Cashout/List``, ``List/Cashout/Report``),
	so hits are summed after normalising, never before. Ties break on label so
	the strip does not reshuffle between loads.
	"""
	tally = {}
	for row in rows:
		route = normalize_route(row.get("route"))
		if route in known:
			tally[route] = tally.get(route, 0) + (row.get("hits") or 0)

	ranked = sorted(tally.items(), key=lambda kv: (-kv[1], known[kv[0]]["label"]))
	return [dict(known[route], hits=hits) for route, hits in ranked[:limit]]

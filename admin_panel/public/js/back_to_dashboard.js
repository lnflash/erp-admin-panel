/* Back-to-Dashboard button on every destination the Admin Dashboard links to.
 *
 * Loaded desk-wide via hooks.app_include_js — ONE file instead of an edit in
 * every page's own JS, so a new page cannot ship without the button (the
 * route lists below are pinned to api/nav_core.py by
 * test_admin_dashboard_nav_contract, the same anti-drift net the tiles use).
 *
 * Covers both destination kinds the dashboard opens: custom Pages (route
 * ["account-hub"]) and doctype List views (route ["List", "Cashout", ...]).
 * The dashboard itself is deliberately absent — no button to itself.
 */

(function () {
	// Mirrors nav_core.NAV_GROUPS — pages by route, doctypes by name.
	const PAGES = [
		"transfer-requests",
		"system-accounts",
		"account-hub",
		"account-management",
		"wallet-census",
		"referral-rewards",
		"alert-users",
		"bridge-kyc",
	];
	const DOCTYPES = [
		"Cashout",
		"Bridge Transfer Request",
		"Account Upgrade Request",
		"Bank Account Update Request",
		"Wallet Census Snapshot",
		"User Alerts",
		"Fee Discount",
		"Allowed Country",
		"System Watchlist",
		"ID Verification",
		"Identity Document Type",
		"ID Verification Settings",
		"Compliance Audit Event",
		"Fygaro Settings",
		"Cashout Settings",
		"Referral Settings",
		"System Funding Log",
		"System Transfer Log",
	];

	function is_destination(route) {
		if (!route || !route.length) return false;
		if (route.length === 1 && PAGES.includes(route[0])) return true;
		// List views only: a Form opened FROM a list already has the list to
		// go back to, and Frappe's own back affordances cover it.
		return route[0] === "List" && DOCTYPES.includes(route[1]);
	}

	function inject() {
		const route = frappe.get_route ? frappe.get_route() : null;
		if (!is_destination(route)) return;

		const wrapper = frappe.container && frappe.container.page;
		if (!wrapper) return;
		// Desk keeps page wrappers alive across navigation — inject once per
		// wrapper and the button simply persists on revisits.
		if (wrapper.querySelector(".ad-back-to-dashboard")) return;

		const title = wrapper.querySelector(".page-head .page-title");
		if (!title) return;

		const btn = document.createElement("button");
		btn.className = "btn btn-default btn-sm ad-back-to-dashboard";
		btn.setAttribute("aria-label", __("Back to Dashboard"));
		btn.style.cssText =
			"margin-right: 10px; flex: none; display: inline-flex; align-items: center; gap: 5px;";
		btn.innerHTML =
			'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
			'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
			'<path d="m15 18-6-6 6-6"></path></svg>' +
			`<span class="hidden-xs">${__("Dashboard")}</span>`;
		btn.addEventListener("click", () => frappe.set_route("admin-dashboard"));

		const title_area = title.querySelector(".title-area");
		title.insertBefore(btn, title_area || title.firstChild);
	}

	// NOT the router's "change" event: the router fires it BEFORE the
	// container switches pages when the destination renders async (custom
	// Pages go through frappe.call on the first visit of a session), so
	// frappe.container.page would still be the page being LEFT — injecting
	// the button into the wrong page head. Container.change_to triggers
	// "page-change" only AFTER this.page is updated, and both page factories
	// build the page head before calling change_to, so the wrapper is always
	// current and the title always exists — no retry loop needed. The extra
	// ready-call covers a desk boot where the first page-change beats our
	// listener registration.
	$(document).ready(() => {
		$(document).on("page-change", () => inject());
		inject();
	});
})();

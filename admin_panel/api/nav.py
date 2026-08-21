"""Frappe-facing navigation endpoints for the Admin Dashboard.

The registry itself and all the pure ranking logic live in ``nav_core`` so
they are testable without a Frappe runtime; this module is only the database
and permission layer on top.

Frequently-used ranking reads Frappe's own ``Route History``. The desk records
that history itself, but ``router_history.js`` drops any route with a single
path segment (``is_route_useful`` returns False when ``!route[1]``) — which is
the shape of every custom Page in this app. Left alone, the desk only ever
logs doctype lists, so ``record_visit`` writes tile clicks back into Route
History through the core ``deferred_insert`` endpoint. One table, one
retention policy, and the pages become frequent in the awesomebar too.
"""

import frappe

from .auth import require_admin
from .common import handle_api_errors
from .nav_core import FREQUENT_WINDOW_DAYS, NAV_GROUPS, by_route, normalize_route, rank_frequent


def _frequent(known):
	"""Top registry destinations for the current user, ranked by visit count."""
	since = frappe.utils.add_days(frappe.utils.now_datetime(), -FREQUENT_WINDOW_DAYS)
	rows = frappe.get_all(
		"Route History",
		filters={"user": frappe.session.user, "creation": [">=", since]},
		fields=["route", "count(name) as hits"],
		group_by="route",
		order_by="hits desc",
		# Generous cap: many raw routes collapse onto one registry entry, and
		# plenty resolve to nothing at all (forms, workspaces, core doctypes).
		limit=200,
	)
	return rank_frequent([{"route": r.route, "hits": r.hits} for r in rows], known)


def _visible(link):
	"""Hide a doctype tile the user cannot read, so no tile 403s on click.

	Pages carry no per-tile check: they are all gated by the same ADMIN_ROLES
	the caller of this endpoint has already passed.
	"""
	if link["kind"] != "doctype":
		return True
	return frappe.has_permission(link["doctype"], "read")


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_nav():
	"""The dashboard's link directory plus this user's frequently-used tiles."""
	groups = []
	for group in NAV_GROUPS:
		links = [link for link in group["links"] if _visible(link)]
		if links:
			groups.append({"title": group["title"], "links": links})

	known = {link["route"]: link for group in groups for link in group["links"]}
	return {"groups": groups, "frequent": _frequent(known)}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def record_visit(route):
	"""Log a dashboard tile click into Route History.

	Fire-and-forget from the page: navigation must never wait on, or be
	blocked by, this bookkeeping.
	"""
	from frappe.desk.doctype.route_history.route_history import deferred_insert

	if normalize_route(route) not in by_route():
		# Registry destinations only — never let an arbitrary caller-supplied
		# string through into the shared history table.
		return {"recorded": False}

	deferred_insert(frappe.as_json([{"route": route, "creation": frappe.utils.now()}]))
	return {"recorded": True}

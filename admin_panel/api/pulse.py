"""Ops-pulse payload for the Admin Dashboard.

One fast call feeding the dashboard's live layer: census float + history
(scalar snapshot fields only — never the heavy per-account rows payload), the cashout settlement
queue, and pending upgrade requests. Everything the operator needs to answer
"how's the money?" and "who needs me?" at a glance.
"""

import frappe

from .auth import require_admin
from .common import handle_api_errors

# Cashout statuses that mean "an operator still has work to do".
ACTIONABLE_CASHOUT_STATUSES = ["Pending", "In Progress"]


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_dashboard_pulse():
	"""Census totals + deltas + history, cashout queue, upgrade queue."""
	snaps = frappe.get_all(
		"Wallet Census Snapshot",
		filters={"status": "Complete"},
		fields=[
			"name",
			"usdt_total",
			"usd_total",
			"funded_count",
			"total_accounts",
			"completed_at",
		],
		order_by="completed_at desc",
		limit=20,
	)
	latest = snaps[0] if snaps else None
	previous = snaps[1] if len(snaps) > 1 else None

	census = None
	if latest:
		census = {
			"snapshot": latest.name,
			"usdt_total": latest.usdt_total,
			"usd_total": latest.usd_total,
			"funded": latest.funded_count,
			"accounts": latest.total_accounts,
			"completed_at": str(latest.completed_at),
			"usdt_delta": round(latest.usdt_total - previous.usdt_total, 2) if previous else None,
			"funded_delta": (latest.funded_count - previous.funded_count) if previous else None,
			# oldest → newest for charting
			"history": [
				{
					"usdt": s.usdt_total,
					"funded": s.funded_count,
					"at": str(s.completed_at),
					"snapshot": s.name,
				}
				for s in reversed(snaps)
			],
		}

	cashout_filters = {"status": ["in", ACTIONABLE_CASHOUT_STATUSES]}
	cashouts = {
		"count": frappe.db.count("Cashout", cashout_filters),
		"rows": frappe.get_all(
			"Cashout",
			filters=cashout_filters,
			fields=["name", "customer", "status", "user_receives", "currency", "creation"],
			order_by="creation asc",
			limit=4,
		),
	}
	for row in cashouts["rows"]:
		row["creation"] = str(row["creation"])
	cashouts["oldest_at"] = cashouts["rows"][0]["creation"] if cashouts["rows"] else None

	upgrade_filters = {"status": "Pending"}
	upgrades = {
		"count": frappe.db.count("Account Upgrade Request", upgrade_filters),
		"rows": frappe.get_all(
			"Account Upgrade Request",
			filters=upgrade_filters,
			fields=["name", "username", "requested_level", "creation"],
			order_by="creation asc",
			limit=3,
		),
	}
	for row in upgrades["rows"]:
		row["creation"] = str(row["creation"])

	return {
		"census": census,
		"cashouts": cashouts,
		"upgrades": upgrades,
		"now": str(frappe.utils.now_datetime()),
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_transfer_pulse():
	"""Queue vitals for the Transfer Requests page tiles.

	Counts are DB-wide (not the current table page/filter) so the tiles
	stay honest under pagination and status filters.
	"""
	oldest = frappe.get_all(
		"Cashout",
		filters={"status": ["in", ACTIONABLE_CASHOUT_STATUSES]},
		fields=["name", "creation"],
		order_by="creation asc",
		limit=1,
	)

	def audit_counts(provider, keys):
		return {
			key: frappe.db.count("Bridge Transfer Request", {"status": status, "provider": provider})
			for key, status in keys
		}

	bridge_counts = audit_counts(
		"Bridge",
		(
			("pending", "Pending"),
			("fiat_received", "Fiat Received"),
			("failed", "Failed"),
		),
	)
	fygaro_counts = audit_counts(
		"Fygaro",
		(
			("fiat_received", "Fiat Received"),
			("completed", "Completed"),
			("failed", "Failed"),
		),
	)
	return {
		"cashouts": {
			"pending": frappe.db.count("Cashout", {"status": "Pending"}),
			"in_progress": frappe.db.count("Cashout", {"status": "In Progress"}),
			"oldest_at": str(oldest[0].creation) if oldest else None,
			"oldest_id": oldest[0].name if oldest else None,
		},
		"bridge": bridge_counts,
		"fygaro": fygaro_counts,
		"now": str(frappe.utils.now_datetime()),
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_upgrade_pulse():
	"""Queue vitals for the Account Management (upgrade requests) tiles."""
	oldest = frappe.get_all(
		"Account Upgrade Request",
		filters={"status": "Pending"},
		fields=["name", "username", "creation"],
		order_by="creation asc",
		limit=1,
	)
	week_ago = frappe.utils.add_days(frappe.utils.now_datetime(), -7)
	return {
		"pending": frappe.db.count("Account Upgrade Request", {"status": "Pending"}),
		# Approximation: `modified` bumps on ANY re-save of an already
		# processed request (e.g. phone sync), not just the approve/reject
		# transition — the doctype records no processed-at timestamp.
		"processed_week": frappe.db.count(
			"Account Upgrade Request",
			{"status": ["in", ["Approved", "Rejected"]], "modified": [">=", week_ago]},
		),
		"oldest_at": str(oldest[0].creation) if oldest else None,
		"oldest_who": (oldest[0].username or oldest[0].name) if oldest else None,
		"now": str(frappe.utils.now_datetime()),
	}

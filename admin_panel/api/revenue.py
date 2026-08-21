"""Flash fee revenue aggregates for the top of the Admin Dashboard.

The shape of each revenue line, and why the two are handled differently, is
documented in ``revenue_core``; this module is only the query layer.

**Windowing caveat:** neither doctype records when its money actually settled
— ``Cashout`` has no completed-at field, and ``Bridge Transfer
Request.first_seen_at`` is nullable, so windowing on it would silently drop
rows. Windows therefore run on ``creation``, which is when the row landed in
ERPNext. For a backfilled row that is not the economic event date. The
all-time figure is unaffected, and the dashboard states the caveat on screen.
"""

import frappe
from frappe.query_builder.functions import Sum

from .auth import require_admin
from .common import handle_api_errors
from .revenue_core import BASE_CURRENCY, coerce_fee, pct_change, topup_fees, window_starts

# A cashout only earns its fee once the fiat actually went out.
REVENUE_CASHOUT_STATUS = "Completed"

# Fygaro is the only provider carrying a Flash fee; Bridge never does.
REVENUE_TOPUP_STATUS = "Completed"
REVENUE_TOPUP_PROVIDER = "Fygaro"


def _cashout_fees(start, end):
	"""SUM of completed-cashout Flash fees in a window, in USD.

	Aggregated server-side rather than fetched: cashout rows grow without
	bound and the dashboard only ever needs the total.
	"""
	cashout = frappe.qb.DocType("Cashout")
	query = (
		frappe.qb.from_(cashout)
		.select(Sum(cashout.flash_fee))
		.where(cashout.status == REVENUE_CASHOUT_STATUS)
		# Cancelled documents (docstatus 2) are not revenue.
		.where(cashout.docstatus < 2)
	)
	if start is not None:
		query = query.where(cashout.creation >= start)
	if end is not None:
		query = query.where(cashout.creation < end)

	result = query.run()
	return float(result[0][0] or 0.0) if result else 0.0


def _topup_rows():
	"""Completed Fygaro rows, coerced once and reused for every window.

	Fetched rather than aggregated, unlike cashouts: the fee column is Data,
	so summing it in SQL would cast empty strings to 0 and silently bury the
	uncomputed-fee rows the dashboard has to disclose.
	"""
	rows = frappe.get_all(
		"Bridge Transfer Request",
		filters={"status": REVENUE_TOPUP_STATUS, "provider": REVENUE_TOPUP_PROVIDER},
		fields=["creation", "flash_fee", "currency"],
	)
	return [
		{
			"creation": row.creation,
			"fee": coerce_fee(row.flash_fee),
			"currency": (row.currency or BASE_CURRENCY).upper(),
		}
		for row in rows
	]


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_revenue_summary():
	"""Flash fee revenue by window, split by the line that earned it."""
	now = frappe.utils.now_datetime()
	topup_rows = _topup_rows()

	windows = {}
	for key, (start, end) in window_starts(now).items():
		cashout = round(_cashout_fees(start, end), 2)
		topup = topup_fees(topup_rows, start, end)
		windows[key] = {
			"total": round(cashout + topup["usd"], 2),
			"cashout": cashout,
			"topup": topup["usd"],
			"fee_pending": topup["fee_pending"],
			"other_currency": topup["other_currency"],
		}

	return {
		"currency": BASE_CURRENCY,
		"windows": windows,
		"d30_change_pct": pct_change(windows["d30"]["total"], windows["prev_d30"]["total"]),
		"now": str(now),
	}

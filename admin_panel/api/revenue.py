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
from .revenue_core import BASE_CURRENCY, FEE_PATTERN_SQL, pct_change, topup_fees, window_starts

# A cashout only earns its fee once the fiat actually went out.
REVENUE_CASHOUT_STATUS = "Completed"

# Fygaro is the only provider carrying a Flash fee; Bridge never does. A
# Fygaro row can terminate at either success status — ``Completed`` (the
# operator status action) or ``Settled`` (``fygaro_topup_core`` names both
# terminal) — and its fee is revenue either way. Counting only one of them
# would silently understate, which is the failure this module exists to
# prevent.
REVENUE_TOPUP_STATUSES = ("Completed", "Settled")
REVENUE_TOPUP_PROVIDER = "Fygaro"

# The SQL twin of ``revenue_core.coerce_fee``: ``flash_fee`` is a Data
# column, and a bare SUM(CAST(...)) would cast NULL, empty and garbage
# strings to 0 — burying exactly the uncomputed-fee rows the dashboard has
# to disclose. Only a value matching ``FEE_PATTERN`` enters the SUM; every
# other row stays NULL so it lands in the pending count instead.
# ``TRIM()`` strips only spaces — a "1.25\t" must not be pending here while
# ``coerce_fee`` calls it computed — so both the match and the cast strip the
# full ``[[:space:]]`` set, mirroring ``revenue_core.SQL_WHITESPACE`` exactly.
FEE_STRIP_SQL = "REGEXP_REPLACE(flash_fee, '^[[:space:]]+|[[:space:]]+$', '')"
FEE_SQL = f"CASE WHEN flash_fee REGEXP %(fee_pattern)s THEN CAST({FEE_STRIP_SQL} AS DECIMAL(20, 6)) END"


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


def _topup_fees(start, end):
	"""Fygaro fee aggregates for one window, grouped by currency in SQL.

	Aggregated server-side for the same reason as cashouts: this page is the
	desk landing page and top-up rows grow without bound, so fetching every
	row on every load would make login latency grow with volume forever. The
	Data-typed fee column's empty-string trap (see ``revenue_core``) is
	handled by ``FEE_SQL`` — uncomputed fees are counted, never cast to 0 —
	and the window bounds are half-open exactly like ``revenue_core.in_window``.
	"""
	conditions = ["provider = %(provider)s", "status IN %(statuses)s"]
	values = {
		"provider": REVENUE_TOPUP_PROVIDER,
		"statuses": REVENUE_TOPUP_STATUSES,
		"fee_pattern": FEE_PATTERN_SQL,
		"base": BASE_CURRENCY,
	}
	if start is not None:
		conditions.append("creation >= %(start)s")
		values["start"] = start
	if end is not None:
		conditions.append("creation < %(end)s")
		values["end"] = end

	groups = frappe.db.sql(
		f"""
		SELECT
			UPPER(COALESCE(NULLIF(TRIM(currency), ''), %(base)s)) AS currency,
			SUM({FEE_SQL}) AS fee_total,
			COUNT(*) - COUNT({FEE_SQL}) AS fee_pending
		FROM `tabBridge Transfer Request`
		WHERE {" AND ".join(conditions)}
		GROUP BY 1
		""",
		values,
		as_dict=True,
	)
	return topup_fees(groups)


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_revenue_summary():
	"""Flash fee revenue by window, split by the line that earned it."""
	now = frappe.utils.now_datetime()

	windows = {}
	for key, (start, end) in window_starts(now).items():
		cashout = round(_cashout_fees(start, end), 2)
		topup = _topup_fees(start, end)
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

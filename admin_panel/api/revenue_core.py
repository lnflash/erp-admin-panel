"""Pure revenue math for the Admin Dashboard — no Frappe runtime.

Two revenue lines exist in this database and they are shaped differently:

* **Cashout** — ``flash_fee`` is a Float and always USD (the field's own label
  says so, and ``system_accounts._outstanding_payables`` subtracts it straight
  off ``user_pays``). The row's ``currency`` denominates ``user_receives``, not
  the fee. Summed in SQL by the caller; nothing to coerce.
* **Card top-ups** — ``Bridge Transfer Request.flash_fee`` is a *Data* column
  denominated in the row's own ``currency``, and only Fygaro rows ever carry
  one (Bridge transfers have no fee breakdown at all). Being Data-typed, an
  uncomputed fee is NULL or empty rather than 0.0. That is the whole reason
  this module exists: a fee that was never computed must surface as *pending*,
  not total as zero, and a non-USD fee must be reported on its own rather than
  added into a USD figure. The caller sums these in SQL too — but only behind
  the ``FEE_PATTERN`` numeric guard, never as a blind cast.
"""

import re
from datetime import datetime, timedelta

# The currency every headline number is expressed in.
BASE_CURRENCY = "USD"

# What a computed fee looks like as a string. ``revenue.FEE_SQL`` uses this
# (via REGEXP) to decide which Data-typed values may enter the SQL SUM;
# anything that does not match is counted as pending instead of casting to 0.
# ``coerce_fee`` is the Python reference for the same rule — the test suite
# pins the two against each other.
FEE_PATTERN = r"^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)$"


def _midnight(moment):
	return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def window_starts(now):
	"""Inclusive lower and exclusive upper bounds per reported window.

	``None`` means unbounded on that side. ``prev_d30`` exists only to give
	the 30-day figure something honest to compare against.
	"""
	if isinstance(now, str):
		now = datetime.fromisoformat(now)
	return {
		"today": (_midnight(now), None),
		"mtd": (_midnight(now).replace(day=1), None),
		"d30": (now - timedelta(days=30), None),
		"prev_d30": (now - timedelta(days=60), now - timedelta(days=30)),
		"all": (None, None),
	}


def coerce_fee(raw):
	"""A Data-typed fee as a float, or ``None`` when it was never computed.

	Returning ``None`` rather than 0.0 is the point: the caller counts these
	separately so the dashboard can say "excluded" instead of quietly
	understating revenue. This is the Python reference semantics for
	``FEE_PATTERN`` / ``revenue.FEE_SQL``, which apply the same rule inside
	the aggregate query.
	"""
	if isinstance(raw, str):
		# Same gate as the SQL: only what FEE_PATTERN admits may become a
		# number. ``float()`` alone would also accept scientific notation and
		# specials ("1e3", "nan", "inf") that the SQL discloses as pending.
		raw = raw.strip()
		if not re.match(FEE_PATTERN, raw):
			return None
		return float(raw)
	if raw is None:
		return None
	try:
		return float(raw)
	except (TypeError, ValueError):
		return None


def in_window(moment, start, end):
	"""The half-open window contract — inclusive start, exclusive end.

	The revenue queries implement exactly this in SQL (``creation >= start``
	/ ``creation < end``); this stays as the executable reference so the
	boundary semantics have a pinned, runnable definition.
	"""
	if start is not None and moment < start:
		return False
	if end is not None and moment >= end:
		return False
	return True


def topup_fees(groups):
	"""Assemble per-currency Fygaro fee aggregates into a USD total plus caveats.

	``groups`` are ``{"currency", "fee_total", "fee_pending"}`` rows — one
	per currency, already windowed and summed in SQL by ``revenue._topup_fees``.
	``fee_total`` is ``None`` when no row in that currency carried a computed
	fee; the pending count still surfaces, never folded into the total.
	"""
	total = 0.0
	pending = 0
	other = {}
	for group in groups:
		pending += int(group["fee_pending"] or 0)
		if group["fee_total"] is None:
			continue
		fee = float(group["fee_total"])
		if group["currency"] == BASE_CURRENCY:
			total += fee
		else:
			other[group["currency"]] = round(fee, 2)
	return {"usd": round(total, 2), "fee_pending": pending, "other_currency": other}


def pct_change(current, previous):
	"""Percent change, or ``None`` when there is no base to compare against."""
	if not previous:
		return None
	return round((current - previous) / previous * 100.0, 1)

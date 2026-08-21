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
  added into a USD figure.
"""

from datetime import datetime, timedelta

# The currency every headline number is expressed in.
BASE_CURRENCY = "USD"


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
	understating revenue.
	"""
	if isinstance(raw, str):
		raw = raw.strip()
	if raw in (None, ""):
		return None
	try:
		return float(raw)
	except (TypeError, ValueError):
		return None


def in_window(moment, start, end):
	if start is not None and moment < start:
		return False
	if end is not None and moment >= end:
		return False
	return True


def topup_fees(rows, start, end):
	"""Window coerced Fygaro rows into a USD total plus its caveats.

	``rows`` are ``{"creation", "fee", "currency"}`` dicts, already coerced.
	"""
	total = 0.0
	pending = 0
	other = {}
	for row in rows:
		if not in_window(row["creation"], start, end):
			continue
		if row["fee"] is None:
			pending += 1
		elif row["currency"] == BASE_CURRENCY:
			total += row["fee"]
		else:
			other[row["currency"]] = round(other.get(row["currency"], 0.0) + row["fee"], 2)
	return {"usd": round(total, 2), "fee_pending": pending, "other_currency": other}


def pct_change(current, previous):
	"""Percent change, or ``None`` when there is no base to compare against."""
	if not previous:
		return None
	return round((current - previous) / previous * 100.0, 1)

"""Unit tests for the dashboard's Flash fee revenue math.

The risk here is not arithmetic, it is *silence*. ``Bridge Transfer
Request.flash_fee`` is a Data column, so an uncomputed fee is an empty string;
summed in SQL it casts to 0 and the headline number quietly understates
revenue with no sign that anything was missing. And a JMD fee added into a USD
total is wrong in a way nobody can see on the tile. Both are covered below.
"""

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.revenue_core import (
	BASE_CURRENCY,
	coerce_fee,
	in_window,
	pct_change,
	topup_fees,
	window_starts,
)

NOW = datetime(2026, 8, 21, 14, 30, 0)


def row(fee, currency="USD", creation=NOW):
	return {"creation": creation, "fee": coerce_fee(fee), "currency": currency}


# ── coercion: the uncomputed-fee trap ─────────────────────────────────────


def test_coerce_fee_reads_a_data_typed_number():
	assert coerce_fee("1.25") == 1.25
	assert coerce_fee(" 2.50 ") == 2.5
	assert coerce_fee(3.75) == 3.75
	assert coerce_fee("0") == 0.0


def test_coerce_fee_distinguishes_absent_from_zero():
	"""None means "never computed" and must not collapse into 0.0 — that
	distinction is the whole reason the rows are coerced in Python instead of
	summed in SQL."""
	assert coerce_fee(None) is None
	assert coerce_fee("") is None
	assert coerce_fee("   ") is None
	assert coerce_fee("pending") is None
	assert coerce_fee("$1.25") is None
	# and the one that matters: zero is a real fee, not an absence
	assert coerce_fee("0.00") == 0.0
	assert coerce_fee("0.00") is not None


# ── windowing ─────────────────────────────────────────────────────────────


def test_window_starts_covers_today_month_and_rolling_thirty():
	windows = window_starts(NOW)

	assert windows["today"][0] == datetime(2026, 8, 21, 0, 0, 0)
	assert windows["mtd"][0] == datetime(2026, 8, 1, 0, 0, 0)
	assert windows["d30"][0] == datetime(2026, 7, 22, 14, 30, 0)
	assert windows["all"] == (None, None)


def test_prev_thirty_abuts_the_current_thirty_without_overlap():
	"""An overlapping comparison window would double-count the boundary day
	and make every delta subtly wrong."""
	windows = window_starts(NOW)

	assert windows["prev_d30"][1] == windows["d30"][0]
	assert windows["prev_d30"][0] == datetime(2026, 6, 22, 14, 30, 0)


def test_in_window_is_half_open():
	start, end = datetime(2026, 8, 1), datetime(2026, 8, 31)

	assert in_window(datetime(2026, 8, 1), start, end)
	assert not in_window(datetime(2026, 8, 31), start, end)
	assert not in_window(datetime(2026, 7, 31), start, end)
	assert in_window(datetime(2020, 1, 1), None, None)


def test_month_start_is_the_first_not_thirty_days_back():
	assert window_starts(datetime(2026, 3, 1, 0, 30))["mtd"][0] == datetime(2026, 3, 1, 0, 0)


# ── totals and their caveats ──────────────────────────────────────────────


def test_topup_fees_totals_usd_rows():
	total = topup_fees([row("1.25"), row("2.75"), row("0.50")], None, None)

	assert total["usd"] == 4.5
	assert total["fee_pending"] == 0
	assert total["other_currency"] == {}


def test_uncomputed_fees_are_counted_not_silently_zeroed():
	total = topup_fees([row("1.25"), row(""), row(None), row("junk")], None, None)

	assert total["usd"] == 1.25
	assert total["fee_pending"] == 3


def test_non_usd_fees_are_reported_separately_never_added_in():
	total = topup_fees([row("1.25"), row("300", "JMD"), row("200", "JMD")], None, None)

	assert total["usd"] == 1.25
	assert total["other_currency"] == {"JMD": 500.0}


def test_windowing_applies_before_totalling():
	old = datetime(2026, 1, 1, 9, 0)
	start = window_starts(NOW)["mtd"][0]
	total = topup_fees([row("1.00", creation=old), row("2.00")], start, None)

	assert total["usd"] == 2.0
	# the excluded row must not leak into the caveat counts either
	assert total["fee_pending"] == 0


def test_pending_count_respects_the_window():
	old = datetime(2026, 1, 1, 9, 0)
	start = window_starts(NOW)["mtd"][0]

	assert topup_fees([row("", creation=old)], start, None)["fee_pending"] == 0
	assert topup_fees([row("")], start, None)["fee_pending"] == 1


def test_empty_input_is_a_zero_total_not_an_error():
	assert topup_fees([], None, None) == {"usd": 0.0, "fee_pending": 0, "other_currency": {}}


def test_totals_are_rounded_to_cents():
	total = topup_fees([row("0.1"), row("0.2")], None, None)

	assert total["usd"] == 0.3


def test_base_currency_matching_is_case_insensitive_at_the_caller():
	"""revenue._topup_rows upper-cases before handing rows over; this pins the
	value it must normalise to."""
	assert BASE_CURRENCY == "USD"


# ── delta ─────────────────────────────────────────────────────────────────


def test_pct_change_reports_growth_and_decline():
	assert pct_change(150.0, 100.0) == 50.0
	assert pct_change(50.0, 100.0) == -50.0
	assert pct_change(100.0, 100.0) == 0.0


def test_pct_change_has_no_answer_without_a_base():
	"""Dividing by a zero prior period would be an infinite or crashing
	"increase"; the tile shows nothing instead."""
	assert pct_change(100.0, 0.0) is None
	assert pct_change(0.0, 0.0) is None
	assert pct_change(100.0, None) is None

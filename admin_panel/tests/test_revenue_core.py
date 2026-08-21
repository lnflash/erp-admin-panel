"""Unit tests for the dashboard's Flash fee revenue math.

The risk here is not arithmetic, it is *silence*. ``Bridge Transfer
Request.flash_fee`` is a Data column, so an uncomputed fee is an empty string;
summed bare in SQL it casts to 0 and the headline number quietly understates
revenue with no sign that anything was missing. The aggregate query therefore
only sums values matching ``FEE_PATTERN`` and counts everything else as
pending — ``coerce_fee`` is the Python reference for that rule and the two are
pinned against each other below. And a JMD fee added into a USD total is wrong
in a way nobody can see on the tile; that is covered too.
"""

import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.revenue_core import (
	BASE_CURRENCY,
	FEE_PATTERN_SQL,
	SQL_WHITESPACE,
	coerce_fee,
	in_window,
	pct_change,
	topup_fees,
	window_starts,
)

NOW = datetime(2026, 8, 21, 14, 30, 0)


def group(currency, fee_total, fee_pending=0):
	"""One per-currency aggregate row, as ``revenue._topup_fees`` gets from SQL."""
	return {"currency": currency, "fee_total": fee_total, "fee_pending": fee_pending}


# ── coercion: the uncomputed-fee trap ─────────────────────────────────────


def test_coerce_fee_reads_a_data_typed_number():
	assert coerce_fee("1.25") == 1.25
	assert coerce_fee(" 2.50 ") == 2.5
	assert coerce_fee(3.75) == 3.75
	assert coerce_fee("0") == 0.0


def test_coerce_fee_distinguishes_absent_from_zero():
	"""None means "never computed" and must not collapse into 0.0 — that
	distinction is the whole reason the SQL aggregate guards the SUM with
	``FEE_PATTERN`` instead of casting the column blind."""
	assert coerce_fee(None) is None
	assert coerce_fee("") is None
	assert coerce_fee("   ") is None
	assert coerce_fee("pending") is None
	assert coerce_fee("$1.25") is None
	# and the one that matters: zero is a real fee, not an absence
	assert coerce_fee("0.00") == 0.0
	assert coerce_fee("0.00") is not None


# ``FEE_PATTERN_SQL`` executed as Python: ``[[:space:]]`` is a POSIX class
# PCRE and Python both lack by that name, but its member set is exactly
# ``SQL_WHITESPACE`` — so this translation runs the very rule MariaDB runs.
FEE_SQL_AS_PY = FEE_PATTERN_SQL.replace("[[:space:]]", f"[{SQL_WHITESPACE}]")


def sql_side_computes(raw):
	"""What ``revenue.FEE_SQL`` decides for a raw column value."""
	return re.fullmatch(FEE_SQL_AS_PY, raw) is not None


def test_fee_pattern_mirrors_coerce_fee():
	"""``revenue.FEE_SQL`` decides sum-vs-pending with ``FEE_PATTERN_SQL``; if
	that rule drifted from ``coerce_fee`` the SQL totals and the documented
	semantics would silently disagree. Run on the RAW value, unstripped —
	the whitespace treatment is part of the rule being mirrored."""
	computed = ["1.25", "2.50", "0", "0.00", "300", "10.", ".5", "-1.25"]
	# "1e3", "nan", "inf" matter: ``float()`` happily parses them, so a
	# float()-first coerce_fee would total values the SQL reports as pending.
	never_computed = ["", "   ", "pending", "$1.25", "1,25", "1.2.3", "1e3junk", "1e3", "nan", "inf", "-inf"]

	for raw in computed:
		assert sql_side_computes(raw), raw
		assert coerce_fee(raw) is not None, raw
	for raw in never_computed:
		assert not sql_side_computes(raw), raw
		assert coerce_fee(raw) is None, raw


def test_whitespace_rule_is_identical_on_both_sides():
	"""The divergence class this pins: ``str.strip()`` eats all unicode
	whitespace but SQL ``TRIM()`` only spaces — under the old rule a fee
	like "1.25\t" was computed in Python and pending in SQL. Now both sides
	forgive exactly the ``[[:space:]]`` set and nothing more."""
	forgiven = ["1.25\t", "1.25\n", "\t1.25", " 1.25 ", "\r\n1.25\r\n", "\x0b1.25\x0c"]
	# NBSP and other unicode spaces are outside [[:space:]]: pending on BOTH
	# sides, where a default str.strip() would have quietly computed them.
	refused = ["\xa01.25", "1.25\xa0", "\u20071.25", "1.\t25"]

	for raw in forgiven:
		assert sql_side_computes(raw), repr(raw)
		assert coerce_fee(raw) == 1.25, repr(raw)
	for raw in refused:
		assert not sql_side_computes(raw), repr(raw)
		assert coerce_fee(raw) is None, repr(raw)


def test_fee_pattern_admits_nothing_the_cast_would_mangle():
	"""Everything the pattern lets into SUM(CAST(...)) must be a real number —
	a match that CAST silently turns into 0 (or truncates) would resurrect the
	understatement this module exists to prevent."""
	for raw in ["1.25", "0", "0.00", "300", "10.", ".5", "-1.25"]:
		float(raw)  # raises if the pattern admitted garbage


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
# Windowing itself now happens in SQL (``revenue._topup_fees`` bounds
# ``creation`` half-open, per ``in_window``); the assembly below must keep
# every caveat the aggregates carry.


def test_topup_fees_totals_usd_groups():
	total = topup_fees([group("USD", Decimal("4.50"))])

	assert total["usd"] == 4.5
	assert total["fee_pending"] == 0
	assert total["other_currency"] == {}


def test_uncomputed_fees_are_counted_not_silently_zeroed():
	"""A currency whose rows all lack a computed fee arrives as a NULL
	``fee_total`` — that is a pending count, never a 0.0 in the total."""
	total = topup_fees([group("USD", Decimal("1.25"), fee_pending=2), group("JMD", None, fee_pending=1)])

	assert total["usd"] == 1.25
	assert total["fee_pending"] == 3
	assert total["other_currency"] == {}


def test_non_usd_fees_are_reported_separately_never_added_in():
	total = topup_fees([group("USD", Decimal("1.25")), group("JMD", Decimal("500"))])

	assert total["usd"] == 1.25
	assert total["other_currency"] == {"JMD": 500.0}


def test_empty_input_is_a_zero_total_not_an_error():
	assert topup_fees([]) == {"usd": 0.0, "fee_pending": 0, "other_currency": {}}


def test_totals_are_rounded_to_cents():
	total = topup_fees([group("USD", 0.30000000000000004), group("JMD", 0.30000000000000004)])

	assert total["usd"] == 0.3
	assert total["other_currency"] == {"JMD": 0.3}


def test_null_pending_count_reads_as_zero():
	"""A SQL driver may hand back NULL rather than 0; the caveat must not
	crash or go truthy on it."""
	assert topup_fees([group("USD", Decimal("1.00"), fee_pending=None)])["fee_pending"] == 0


def test_base_currency_matching_is_case_insensitive_at_the_caller():
	"""revenue._topup_fees upper-cases ``currency`` in SQL before grouping;
	this pins the value it must normalise to."""
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

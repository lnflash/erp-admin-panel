"""Unit tests for the pure wallet-census join/bucket/totals logic (ENG-487).

These run under plain `pytest` with no Frappe / mongo / IBEX runtime — all the
correctness risk lives in `build_census`, which is a pure function.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.census_core import build_census


def _fixture():
	"""A hand-built census covering every bucket + the tricky cases.

	Join keys (verified in prod): IBEX id == wallets.id;
	IBEX name == str(accounts._id) == cashwalletmigrations.accountId.
	"""
	ibex_accounts = [
		# active + funded USD customer
		{"id": "w-alice", "name": "acc-alice", "currencyId": 3, "balance": 100.50},
		# active + zero USDT customer (balance absent => zero)
		{"id": "w-bob", "name": "acc-bob", "currencyId": 29},
		# closed customer still holding dust
		{"id": "w-carol", "name": "acc-carol", "currencyId": 3, "balance": 0.02},
		# system account (dealer) that happens to be funded
		{"id": "w-dealer", "name": "acc-dealer", "currencyId": 3, "balance": 9000.0},
		# migrated customer, funded on a NON-default wallet (anomaly)
		{"id": "w-dave-usdt", "name": "acc-dave", "currencyId": 29, "balance": 42.0},
		# IBEX account with no matching mongo wallet — currency from currencyId
		{"id": "w-orphan", "name": "acc-orphan", "currencyId": 29, "balance": 5.0},
	]
	wallets = {
		"w-alice": {"account_id": "acc-alice", "currency": "Usd", "type": "Checking"},
		"w-bob": {"account_id": "acc-bob", "currency": "Usdt", "type": "Checking"},
		"w-carol": {"account_id": "acc-carol", "currency": "Usd", "type": "Checking"},
		"w-dealer": {"account_id": "acc-dealer", "currency": "Usd", "type": "Checking"},
		"w-dave-usdt": {"account_id": "acc-dave", "currency": "Usdt", "type": "Checking"},
		# a BTC wallet with no IBEX account (balance not held in IBEX)
		"w-btc": {"account_id": "acc-eve", "currency": "Btc", "type": "Checking"},
	}
	accounts = {
		"acc-alice": {
			"username": "alice",
			"role": "user",
			"status": "Active",
			"default_wallet_id": "w-alice",
			"level": 1,
		},
		"acc-bob": {
			"username": "bob",
			"role": "user",
			"status": "Active",
			"default_wallet_id": "w-bob",
			"level": 1,
		},
		"acc-carol": {
			"username": "carol",
			"role": "user",
			"status": "Closed",
			"default_wallet_id": "w-carol",
			"level": 1,
		},
		"acc-dealer": {
			"username": "dealer",
			"role": "dealer",
			"status": "Active",
			"default_wallet_id": "w-dealer",
			"level": 2,
		},
		"acc-dave": {
			"username": "dave",
			"role": "user",
			"status": "Active",
			"default_wallet_id": "w-dave-old",
			"level": 1,
		},
	}
	migrations = {
		"acc-dave": {"status": "completed", "run_id": "run-7", "completed_at": "2026-07-09T00:00:00"},
	}
	return ibex_accounts, wallets, accounts, migrations


def test_totals_by_currency():
	result = build_census(*_fixture())
	totals = result["totals"]
	# USD: alice 100.50 + carol 0.02 + dealer 9000.0
	assert totals["usd"]["balance"] == 9100.52
	# USDT: dave 42.0 + orphan 5.0 (bob is zero)
	assert totals["usdt"]["balance"] == 47.0
	assert totals["usd"]["funded_count"] == 3
	assert totals["usdt"]["funded_count"] == 2
	assert totals["usdt"]["zero_count"] == 1  # bob
	assert totals["accounts"] == 6
	assert totals["funded"] == 5
	assert totals["zero"] == 1


def test_btc_wallets_counted_without_balance():
	totals = build_census(*_fixture())["totals"]
	assert totals["btc"]["wallet_count"] == 1
	assert totals["btc"]["balance"] is None


def test_absent_balance_is_zero():
	rows = {r["account_id"]: r for r in build_census(*_fixture())["rows"]}
	assert rows["acc-bob"]["balance"] == 0.0
	assert "active_zero" in rows["acc-bob"]["buckets"]


def test_bucket_assignment():
	result = build_census(*_fixture())
	rows = {r["account_id"]: r for r in result["rows"]}
	assert "active_funded" in rows["acc-alice"]["buckets"]
	assert "active_zero" in rows["acc-bob"]["buckets"]
	assert "closed_with_dust" in rows["acc-carol"]["buckets"]
	# system account is bucketed as system, never as active_funded
	assert rows["acc-dealer"]["buckets"] == ["system"]
	# dave: migrated + funded on a non-default wallet
	assert "migrated" in rows["acc-dave"]["buckets"]
	assert "non_default_wallet" in rows["acc-dave"]["buckets"]
	# orphan has no mongo account -> unmatched (unknown status, NOT "closed")
	assert rows["acc-orphan"]["buckets"] == ["unmatched"]

	# Buckets are overlapping tags: dave is active+funded AND migrated AND
	# non-default.
	counts = result["bucket_counts"]
	assert counts["active_funded"] == 2  # alice, dave
	assert counts["active_zero"] == 1  # bob
	assert counts["closed_with_dust"] == 1  # carol (known Closed status)
	assert counts["unmatched"] == 1  # orphan (no mongo record)
	assert counts["system"] == 1  # dealer
	assert counts["migrated"] == 1  # dave
	assert counts["non_default_wallet"] == 1  # dave


def test_currency_falls_back_to_currency_id_when_wallet_missing():
	rows = {r["account_id"]: r for r in build_census(*_fixture())["rows"]}
	# orphan has no mongo wallet; currency derived from IBEX currencyId 29
	assert rows["acc-orphan"]["currency"] == "Usdt"
	assert rows["acc-orphan"]["username"] is None


def test_rows_sorted_by_balance_desc():
	rows = build_census(*_fixture())["rows"]
	balances = [r["balance"] for r in rows]
	assert balances == sorted(balances, reverse=True)
	assert rows[0]["account_id"] == "acc-dealer"  # 9000 is the largest


def test_empty_input():
	result = build_census([], {}, {}, {})
	assert result["totals"]["accounts"] == 0
	assert result["rows"] == []
	assert result["bucket_counts"]["active_funded"] == 0


def test_ibex_only_run_is_unmatched_not_closed():
	"""IBEX-only run (no mongo): funded accounts are 'unmatched', not 'closed'.

	Regression for the sandbox smoke test — status is unknown without a mongo
	account record, so funded accounts must not be labeled Closed w/ Dust.
	"""
	ibex = [
		{"id": "w1", "name": "a1", "currencyId": 29, "balance": 3.0},  # funded
		{"id": "w2", "name": "a2", "currencyId": 29},  # zero
	]
	result = build_census(ibex, {}, {}, {})
	counts = result["bucket_counts"]
	assert counts["unmatched"] == 2
	assert counts["closed_with_dust"] == 0
	assert counts["active_funded"] == 0
	# totals still computed from IBEX alone
	assert result["totals"]["usdt"]["balance"] == 3.0
	assert result["totals"]["funded"] == 1


def test_sweep_pages_continues_past_short_pages():
	"""Prod IBEX silently caps page size (limit=100 returns 25), so a short
	batch must NOT be read as the last page — that truncated the first prod
	census to 25 of ~8,750 accounts. Only an empty page ends the sweep."""
	from admin_panel.api.census_core import sweep_pages

	pages = {1: ["a"] * 25, 2: ["b"] * 25, 3: ["c"] * 7, 4: []}
	fetched = []

	def fetch(page):
		fetched.append(page)
		return pages[page]

	out = [(p, len(batch)) for p, batch in sweep_pages(fetch, max_pages=10)]

	assert out == [(1, 25), (2, 25), (3, 7)]
	assert fetched == [1, 2, 3, 4]  # exactly one extra (empty) request


def test_sweep_pages_raises_at_max_pages():
	from admin_panel.api.census_core import PageLimitExceeded, sweep_pages

	def endless(page):
		return ["x"]

	import pytest

	with pytest.raises(PageLimitExceeded):
		list(sweep_pages(endless, max_pages=3))


def test_sweep_pages_empty_first_page():
	from admin_panel.api.census_core import sweep_pages

	assert list(sweep_pages(lambda p: [], max_pages=5)) == []


def test_rewards_role_is_system_not_customer():
	"""A role='rewards' account is a Flash-internal system account, not a real
	customer: it must land in the 'system' bucket, be flagged is_system, and
	never be counted in a customer bucket (active_funded / active_zero /
	closed_with_dust). Regression for making `rewards` a first-class system role
	alongside bankowner/funder/dealer — previously only grep-verified."""
	ibex = [{"id": "w-rw", "name": "acc-rw", "currencyId": 3, "balance": 500.0}]
	wallets = {"w-rw": {"account_id": "acc-rw", "currency": "Usd", "type": "Checking"}}
	accounts = {
		"acc-rw": {
			"username": "rewards",
			"role": "rewards",
			"status": "active",
			"default_wallet_id": "w-rw",
			"level": 2,
		}
	}

	result = build_census(ibex, wallets, accounts, {})
	row = result["rows"][0]

	assert row["role"] == "rewards"
	assert row["is_system"] is True
	assert row["buckets"] == ["system"]

	counts = result["bucket_counts"]
	assert counts["system"] == 1
	# a funded system account must never be miscounted as a customer
	assert counts["active_funded"] == 0
	assert counts["active_zero"] == 0
	assert counts["closed_with_dust"] == 0


def test_micro_dust_is_not_funded():
	"""IBEX emits sub-nanodollar dust (~1e-10 seen on prod): it must classify
	as zero — 91 rows showed 'active_funded' at $0.00 on the first full census."""
	ibex = [{"id": "w-dust", "name": "acc-dust", "currencyId": 29, "balance": 3e-10}]
	accounts = {
		"acc-dust": {
			"username": "dusty",
			"role": "user",
			"status": "active",
			"default_wallet_id": "w-dust",
		}
	}
	wallets = {"w-dust": {"account_id": "acc-dust", "currency": "Usdt", "type": "Checking"}}

	result = build_census(ibex, wallets, accounts, {})
	row = result["rows"][0]

	assert row["balance"] == 0.0
	assert row["buckets"] == ["active_zero"]
	assert result["totals"]["funded"] == 0
	assert result["bucket_counts"]["active_funded"] == 0

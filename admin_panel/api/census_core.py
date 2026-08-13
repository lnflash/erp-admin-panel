"""Pure join / bucket / totals logic for the wallet census (ENG-487).

This module deliberately imports NOTHING from frappe, pymongo, or requests so
it can be unit-tested against fixtures with plain `pytest`. All IO (IBEX +
mongo) lives in `census.py`, `ibex_client.py`, and `mongo_reader.py`, which
depend on the constants and `build_census` defined here.
"""

# IBEX currencyId -> our wallet currency. IBEX only custodies USD and USDT;
# BTC balances live on the Lightning side and are not returned by the API.
CURRENCY_BY_ID = {3: "Usd", 29: "Usdt"}

# Account roles that are Flash-internal system accounts, not real customers.
SYSTEM_ROLES = {"dealer", "bankowner", "funder", "rewards"}

# Account status (last statusHistory entry) considered "active", case-insensitive.
ACTIVE_STATUS = "active"

# cashwalletmigrations statuses that count as a completed migration.
MIGRATED_STATUSES = {"completed", "complete", "succeeded", "success", "done"}

# Balances at or below this are zero for classification. IBEX emits
# sub-nanodollar dust (~1e-10 observed on prod, first full census): those rows
# classified as "funded" pre-rounding but displayed $0.00. Matches the cutover
# verifier's dust tolerance.
FUNDED_EPSILON = 1e-6


class PageLimitExceeded(Exception):
	"""sweep_pages hit max_pages — the API is paging forever or the cap is too low."""


def sweep_pages(fetch_page, max_pages):
	"""Yield (page_number, batch) from successive 1-indexed pages until an EMPTY page.

	Termination must NOT infer "last page" from a short batch: the prod IBEX
	hub silently caps the page size (requesting limit=100 returns 25 rows), so
	a short page looks identical to a full one there. That inference truncated
	the first prod census to 25 of ~8,750 accounts (2026-07-10). Only an empty
	page ends the sweep — costing exactly one extra request.
	"""
	page = 1
	while True:
		if page > max_pages:
			raise PageLimitExceeded(f"pagination exceeded {max_pages} pages — aborting sweep")
		batch = fetch_page(page)
		if not batch:
			return
		yield page, batch
		page += 1


def _is_migrated(migration) -> bool:
	if not migration:
		return False
	status = (migration.get("status") or "").lower()
	return status in MIGRATED_STATUSES


def build_census(ibex_accounts, wallets, accounts, migrations) -> dict:
	"""Join IBEX accounts against mongo, bucket them, and total balances.

	Args:
	    ibex_accounts: list of {id, name, currencyId, balance} (balance in
	        dollars; absent/None means zero).
	    wallets:    wallet_id -> {account_id, currency, type}
	    accounts:   account_id -> {username, level, status, role,
	                               default_wallet_id, npub, created_at}
	    migrations: account_id -> {status, run_id, completed_at}

	Returns a dict with `rows`, `totals`, and `bucket_counts` — all
	JSON-serializable.
	"""
	rows = []
	totals = {
		"usd": {"balance": 0.0, "funded_count": 0, "zero_count": 0},
		"usdt": {"balance": 0.0, "funded_count": 0, "zero_count": 0},
	}
	buckets = {
		"active_funded": 0,
		"active_zero": 0,
		"closed_with_dust": 0,
		"unmatched": 0,
		"migrated": 0,
		"system": 0,
		"non_default_wallet": 0,
	}

	for account in ibex_accounts:
		wallet_id = account.get("id")
		# IBEX account name IS the mongo account _id string — the join key.
		account_id = account.get("name")
		wallet = wallets.get(wallet_id) or {}
		acct_record = accounts.get(account_id)
		acct = acct_record or {}
		# "matched" = this IBEX account has a mongo account record. When the
		# census runs IBEX-only (no customer_mongo_uri), nothing is matched;
		# when mongo is wired, an unmatched account is a genuine anomaly.
		matched = acct_record is not None
		migration = migrations.get(account_id)

		raw_balance = account.get("balance")
		# Round to stored precision BEFORE classifying so "funded" and the
		# displayed balance can never disagree.
		balance = round(float(raw_balance), 8) if raw_balance else 0.0
		funded = balance > FUNDED_EPSILON

		currency = wallet.get("currency") or CURRENCY_BY_ID.get(account.get("currencyId"))
		status = acct.get("status")
		status_active = (status or "").lower() == ACTIVE_STATUS
		role = acct.get("role") or "user"
		is_system = role in SYSTEM_ROLES
		migrated = _is_migrated(migration)
		default_wallet_id = acct.get("default_wallet_id")
		non_default = bool(funded and default_wallet_id and wallet_id != default_wallet_id)

		# Status-based buckets require a known status. An account with no mongo
		# record (unknown status) is "unmatched", NOT "closed" — don't conflate
		# "status not active" with "status unknown".
		row_buckets = []
		if is_system:
			row_buckets.append("system")
			buckets["system"] += 1
		elif not matched:
			row_buckets.append("unmatched")
			buckets["unmatched"] += 1
		elif status_active and funded:
			row_buckets.append("active_funded")
			buckets["active_funded"] += 1
		elif status_active and not funded:
			row_buckets.append("active_zero")
			buckets["active_zero"] += 1
		elif not status_active and funded:
			row_buckets.append("closed_with_dust")
			buckets["closed_with_dust"] += 1
		if migrated:
			row_buckets.append("migrated")
			buckets["migrated"] += 1
		if non_default:
			row_buckets.append("non_default_wallet")
			buckets["non_default_wallet"] += 1

		bucket = totals.get((currency or "").lower())
		if bucket is not None:
			bucket["balance"] += balance
			if funded:
				bucket["funded_count"] += 1
			else:
				bucket["zero_count"] += 1

		rows.append(
			{
				"username": acct.get("username"),
				"account_id": account_id,
				"wallet_id": wallet_id,
				"currency": currency,
				"balance": balance,
				"status": status,
				"level": acct.get("level"),
				"role": role,
				"is_system": is_system,
				"migration_status": migration.get("status") if migration else None,
				"run_id": migration.get("run_id") if migration else None,
				"migrated": migrated,
				"is_default_wallet": (not non_default) if funded else None,
				"npub": acct.get("npub"),
				"created_at": acct.get("created_at"),
				"buckets": row_buckets,
			}
		)

	rows.sort(key=lambda r: r["balance"], reverse=True)
	funded_count = sum(1 for r in rows if r["balance"] > FUNDED_EPSILON)

	# BTC wallets exist in mongo but hold no IBEX balance — report the count so
	# operators know it's intentional, not a gap.
	btc_wallet_count = sum(1 for w in wallets.values() if (w.get("currency") or "").lower() == "btc")

	# Round accumulated float balances once at the end to avoid drift.
	for ccy in ("usd", "usdt"):
		totals[ccy]["balance"] = round(totals[ccy]["balance"], 2)

	return {
		"rows": rows,
		"totals": {
			"usd": totals["usd"],
			"usdt": totals["usdt"],
			"btc": {"wallet_count": btc_wallet_count, "balance": None},
			"accounts": len(rows),
			"funded": funded_count,
			"zero": len(rows) - funded_count,
		},
		"bucket_counts": buckets,
	}

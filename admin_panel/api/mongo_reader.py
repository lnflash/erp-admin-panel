"""Read-only reader for the customer MongoDB (Galoy `galoy` database).

Loads the three collections the wallet census joins against IBEX accounts:
`wallets`, `accounts`, and `cashwalletmigrations`. Everything is bulk-loaded
into plain dicts keyed by the join field so the pure `census.build_census`
function can run without any IO.

Verified join keys (see census.py):
  IBEX account.id   == wallets.id
  IBEX account.name == str(accounts._id) == str(wallets._accountId)
                    == cashwalletmigrations.accountId

Config (site_config.json / frappe.conf):
  customer_mongo_uri   (required) — the MONGODB_CON connection string
  customer_mongo_db    (optional) — database name, defaults to "galoy"
"""

import re

import frappe

_client = None


def _get_db():
	uri = frappe.conf.get("customer_mongo_uri")
	if not uri:
		raise ValueError("customer_mongo_uri is not configured in site_config.json")

	global _client
	if _client is None:
		# Imported lazily so the app loads even where pymongo isn't installed
		# (e.g. contract tests that never touch mongo).
		from pymongo import MongoClient

		_client = MongoClient(uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)

	db_name = frappe.conf.get("customer_mongo_db") or "galoy"
	return _client[db_name]


def _latest_status(status_history):
	"""Account status is the last entry of statusHistory (no flat field)."""
	if not status_history:
		return None
	return status_history[-1].get("status")


def load_wallets() -> dict:
	"""wallet id -> {account_id, currency, type}."""
	db = _get_db()
	out = {}
	cursor = db.wallets.find({}, {"id": 1, "_accountId": 1, "currency": 1, "type": 1})
	for doc in cursor:
		wid = doc.get("id")
		if not wid:
			continue
		out[wid] = {
			"account_id": str(doc["_accountId"]) if doc.get("_accountId") else None,
			"currency": doc.get("currency"),
			"type": doc.get("type"),
		}
	return out


def load_accounts() -> dict:
	"""str(account _id) -> {username, level, status, role, created_at, default_wallet_id, npub}."""
	db = _get_db()
	out = {}
	cursor = db.accounts.find(
		{},
		{
			"_id": 1,
			"username": 1,
			"level": 1,
			"role": 1,
			"statusHistory": 1,
			"defaultWalletId": 1,
			"created_at": 1,
			"npub": 1,
		},
	)
	for doc in cursor:
		out[str(doc["_id"])] = {
			"username": doc.get("username"),
			"level": doc.get("level"),
			"role": doc.get("role") or "user",
			"status": _latest_status(doc.get("statusHistory")),
			"default_wallet_id": doc.get("defaultWalletId"),
			"created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
			"npub": doc.get("npub"),
		}
	return out


def load_migrations() -> dict:
	"""accountId -> {status, run_id, completed_at}. Keeps the most recent run per account."""
	db = _get_db()
	out = {}
	cursor = db.cashwalletmigrations.find(
		{},
		{"accountId": 1, "status": 1, "runId": 1, "completedAt": 1, "updatedAt": 1},
	)
	for doc in cursor:
		account_id = doc.get("accountId")
		if not account_id:
			continue
		stamp = doc.get("completedAt") or doc.get("updatedAt")
		existing = out.get(account_id)
		if existing and existing["_stamp"] and stamp and stamp <= existing["_stamp"]:
			continue
		out[account_id] = {
			"status": doc.get("status"),
			"run_id": doc.get("runId"),
			"completed_at": doc.get("completedAt").isoformat() if doc.get("completedAt") else None,
			"_stamp": stamp,
		}
	# Drop the internal sort key before returning.
	for value in out.values():
		value.pop("_stamp", None)
	return out


def _iso(dt):
	return dt.isoformat() if dt else None


def load_bridge_accounts() -> list:
	"""Accounts with a Bridge customer linked, for the bridge-kyc join.

	Returns [{bridge_customer_id, bridge_kyc_status, username, level, status,
	created_at}] — one entry per account whose bridgeCustomerId is set.
	"""
	db = _get_db()
	out = []
	cursor = db.accounts.find(
		{"bridgeCustomerId": {"$nin": [None, ""]}},
		{
			"bridgeCustomerId": 1,
			"bridgeKycStatus": 1,
			"username": 1,
			"level": 1,
			"statusHistory": 1,
			"created_at": 1,
		},
	)
	for doc in cursor:
		out.append(
			{
				"bridge_customer_id": doc.get("bridgeCustomerId"),
				"bridge_kyc_status": doc.get("bridgeKycStatus"),
				"username": doc.get("username"),
				"level": doc.get("level"),
				"status": _latest_status(doc.get("statusHistory")),
				"created_at": _iso(doc.get("created_at")),
			}
		)
	return out


def find_account(query: str):
	"""Resolve a single account doc by accountId / username / phone / wallet id.

	Resolution order: mongo _id (== IBEX account name) → username → phone
	(via the users collection + kratosUserId) → wallet id. Returns the raw
	account doc or None.
	"""
	from bson import ObjectId

	db = _get_db()
	query = (query or "").strip()
	if not query:
		return None

	if ObjectId.is_valid(query):
		acct = db.accounts.find_one({"_id": ObjectId(query)})
		if acct:
			return acct

	acct = db.accounts.find_one({"username": query})
	if acct:
		return acct

	# GraphQL exposes the account uuid (accounts.id), not the mongo _id —
	# accept it so callers can pass either.
	acct = db.accounts.find_one({"id": query})
	if acct:
		return acct

	# Support pastes of formatted numbers ("876 555-1234", "(876) 5551234"):
	# try the raw query, a compacted form, and a "+"-prefixed compacted form.
	compact = re.sub(r"[\s\-().]", "", query)
	candidates = [query, compact]
	if compact and not compact.startswith("+"):
		candidates.append("+" + compact)
	user = None
	for candidate in dict.fromkeys(c for c in candidates if c):
		user = db.users.find_one({"phone": candidate})
		if user:
			break
	if user and user.get("kratosUserId"):
		acct = db.accounts.find_one({"kratosUserId": user["kratosUserId"]})
		if acct:
			return acct

	wallet = db.wallets.find_one({"id": query})
	if wallet and wallet.get("_accountId"):
		return db.accounts.find_one({"_id": wallet["_accountId"]})

	return None


def customer_bundle(account: dict) -> dict:
	"""Assemble the mongo-side per-customer detail for a resolved account doc.

	Returns identity, wallets, migration history, and device/contact state.
	Live IBEX balances and transactions are layered on by the caller.
	"""
	db = _get_db()
	_id = account["_id"]
	account_id = str(_id)

	wallets = [
		{
			"wallet_id": w.get("id"),
			"currency": w.get("currency"),
			"type": w.get("type"),
			"is_default": w.get("id") == account.get("defaultWalletId"),
		}
		for w in db.wallets.find({"_accountId": _id}, {"id": 1, "currency": 1, "type": 1})
	]

	migrations = [
		{
			"status": m.get("status"),
			"run_id": m.get("runId"),
			"cutover_version": m.get("cutoverVersion"),
			"started_at": _iso(m.get("startedAt")),
			"completed_at": _iso(m.get("completedAt")),
			"last_error": m.get("lastError"),
		}
		for m in db.cashwalletmigrations.find({"accountId": account_id}).sort("updatedAt", -1)
	]

	user = None
	if account.get("kratosUserId"):
		user = db.users.find_one(
			{"kratosUserId": account["kratosUserId"]},
			{"phone": 1, "deviceId": 1, "deviceTokens": 1, "phoneMetadata": 1},
		)
	user = user or {}

	status_history = account.get("statusHistory") or []
	return {
		"identity": {
			"account_id": account_id,
			"uuid": account.get("id"),
			"username": account.get("username"),
			"phone": user.get("phone"),
			"level": account.get("level"),
			"status": _latest_status(status_history),
			"role": account.get("role") or "user",
			"created_at": _iso(account.get("created_at")),
			"npub": account.get("npub"),
			"display_currency": account.get("displayCurrency"),
			"default_wallet_id": account.get("defaultWalletId"),
		},
		"wallets": wallets,
		"migrations": migrations,
		"devices": {
			"device_id": user.get("deviceId"),
			"push_tokens": len(user.get("deviceTokens") or []),
		},
		"contacts": [
			{"handle": c.get("id"), "name": c.get("name"), "tx_count": c.get("transactionsCount")}
			for c in (account.get("contacts") or [])
		],
	}


def load_invites() -> list:
	"""Referral invites with their reward-payout fields.

	ObjectIds are str()'d and datetimes iso'd so the pure aggregation
	(`referral_rewards_core.build_overview`) stays IO-free and the endpoint's
	JSON serialization can't choke on a raw ObjectId/datetime.
	"""
	db = _get_db()
	out = []
	cursor = db.invites.find(
		{},
		{
			"_id": 1,
			"contact": 1,
			"method": 1,
			"inviterId": 1,
			"redeemedById": 1,
			"status": 1,
			"createdAt": 1,
			"expiresAt": 1,
			"redeemedAt": 1,
			"rewardStatus": 1,
			"rewardSeq": 1,
			"rewardAmountCents": 1,
			"rewardedAt": 1,
			"inviterRewardedAt": 1,
			"inviteeRewardedAt": 1,
			"rewardError": 1,
		},
	)
	for doc in cursor:
		out.append(
			{
				"invite_id": str(doc["_id"]),
				"contact": doc.get("contact"),
				"method": doc.get("method"),
				"inviter_id": str(doc["inviterId"]) if doc.get("inviterId") else None,
				"redeemed_by_id": str(doc["redeemedById"]) if doc.get("redeemedById") else None,
				"status": doc.get("status"),
				"created_at": _iso(doc.get("createdAt")),
				"expires_at": _iso(doc.get("expiresAt")),
				"redeemed_at": _iso(doc.get("redeemedAt")),
				"reward_status": doc.get("rewardStatus"),
				"reward_seq": doc.get("rewardSeq"),
				"reward_amount_cents": doc.get("rewardAmountCents"),
				"rewarded_at": _iso(doc.get("rewardedAt")),
				"inviter_rewarded_at": _iso(doc.get("inviterRewardedAt")),
				"invitee_rewarded_at": _iso(doc.get("inviteeRewardedAt")),
				"reward_error": doc.get("rewardError"),
			}
		)
	return out


def load_reward_counter() -> int:
	"""Global referral-reward sequence (0 if no referral has been paid yet)."""
	db = _get_db()
	doc = db.referralrewardcounters.find_one({"_id": "referral_reward"})
	return int(doc.get("seq", 0)) if doc else 0

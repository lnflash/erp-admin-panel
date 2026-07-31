"""Referral reward payout monitoring (live read).

Reads the invite reward fields + the global referral counter from the customer
mongo, joins usernames, optionally layers the funding wallet's live IBEX
balance, and returns tiered-payout totals + a per-referral table. All the
join / bucket / totals logic is the pure `referral_rewards_core.build_overview`.
"""

import frappe

from .auth import require_admin
from .common import handle_api_errors
from .ibex_client import IbexClient
from .mongo_reader import load_accounts, load_invites, load_reward_counter
from .referral_rewards_core import REWARD_TIERS, build_overview

__all__ = ["build_overview", "get_referral_rewards"]

# Currency labels a USD/USDT wallet may carry in mongo (casing varies by era).
_USD_CURRENCIES = ["USD", "Usd", "USDT", "Usdt"]


def _rewards_wallet_balance():
	"""Best-effort live USD balance of the funding ('rewards' role) wallet.

	Resolves the account holding role="rewards", picks a USD/USDT wallet, and
	asks IBEX for the balance. Returns None if anything isn't configured or
	available — the page must never break because of the balance lookup.
	"""
	from .mongo_reader import _get_db

	try:
		db = _get_db()
		account = db.accounts.find_one({"role": "rewards"}, {"_id": 1, "defaultWalletId": 1})
		if not account:
			return None
		wallet = db.wallets.find_one(
			{"_accountId": account["_id"], "currency": {"$in": _USD_CURRENCIES}},
			{"id": 1},
		)
		if not wallet or not wallet.get("id"):
			return None
		details = IbexClient().get_account_details(wallet["id"])
		return details.get("balance")
	except Exception as exc:
		frappe.logger().warning(f"referral rewards: rewards wallet balance unavailable: {exc}")
		return None


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_referral_rewards():
	"""Live referral-reward overview: totals, tier state, funnel, per-referral rows."""
	if not frappe.conf.get("customer_mongo_uri"):
		return {"success": False, "error": "customer_mongo_uri is not configured"}

	invites = load_invites()
	accounts = load_accounts()
	counter_seq = load_reward_counter()
	wallet_balance = _rewards_wallet_balance()

	overview = build_overview(
		invites, accounts, counter_seq, tiers=REWARD_TIERS, wallet_balance=wallet_balance
	)
	overview["success"] = True
	overview["now"] = frappe.utils.now_datetime().isoformat()
	return overview

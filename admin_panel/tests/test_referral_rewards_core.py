"""Unit tests for the pure referral-reward aggregation logic.

Run under plain `pytest` — no Frappe / mongo / IBEX runtime. All the
correctness risk (tier math, disbursement totals, funnel, join) lives in the
pure `referral_rewards_core` module.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.referral_rewards_core import (
	REWARD_TIERS,
	build_overview,
	current_tier,
	referrals_until_next_tier,
)

# ── Tier math ─────────────────────────────────────────────────────────────


def test_current_tier_boundaries():
	# current_tier(seq) = amount for the NEXT referral (seq+1).
	assert current_tier(0) == 500  # referral #1
	assert current_tier(99) == 500  # referral #100
	assert current_tier(100) == 250  # referral #101
	assert current_tier(599) == 250  # referral #600
	assert current_tier(600) == 100  # referral #601
	assert current_tier(5000) == 100  # deep in the final tier


def test_referrals_until_next_tier():
	assert referrals_until_next_tier(0) == 100  # 100 more at $5
	assert referrals_until_next_tier(50) == 50
	assert referrals_until_next_tier(100) == 500  # then 500 at $2.50
	assert referrals_until_next_tier(599) == 1
	assert referrals_until_next_tier(600) is None  # final unbounded tier
	assert referrals_until_next_tier(9999) is None


def test_current_tier_empty_and_single_unbounded():
	assert current_tier(5, []) == 0
	one = [{"upToCount": 0, "amountCents": 100}]
	assert current_tier(0, one) == 100
	assert current_tier(10_000, one) == 100
	assert referrals_until_next_tier(0, one) is None


# ── build_overview ─────────────────────────────────────────────────────────


def _fixture():
	accounts = {
		"acc-alice": {"username": "alice"},
		"acc-bob": {"username": "bob"},
		"acc-carol": {"username": "carol"},
		"acc-dan": {"username": "dan"},
		"acc-erin": {"username": "erin"},
		"acc-frank": {"username": "frank"},
	}
	invites = [
		# fully paid, tier $5 — both parties paid
		{
			"invite_id": "i1",
			"status": "ACCEPTED",
			"inviter_id": "acc-alice",
			"redeemed_by_id": "acc-bob",
			"contact": "bob@x.com",
			"reward_status": "paid",
			"reward_seq": 3,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-30T10:00:00",
			"rewarded_at": "2026-07-30T12:00:00",
			"inviter_rewarded_at": "2026-07-30T12:00:00",
			"invitee_rewarded_at": "2026-07-30T12:00:00",
			"reward_error": None,
		},
		# partial — only invitee paid, tier $2.50
		{
			"invite_id": "i2",
			"status": "ACCEPTED",
			"inviter_id": "acc-carol",
			"redeemed_by_id": "acc-dan",
			"contact": "dan@x.com",
			"reward_status": "partial",
			"reward_seq": 150,
			"reward_amount_cents": 250,
			"redeemed_at": "2026-07-29T10:00:00",
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": "2026-07-29T12:00:00",
			"reward_error": "inviter has no USD wallet",
		},
		# failed — nobody paid
		{
			"invite_id": "i3",
			"status": "ACCEPTED",
			"inviter_id": "acc-erin",
			"redeemed_by_id": "acc-frank",
			"contact": "frank@x.com",
			"reward_status": "failed",
			"reward_seq": 4,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-28T10:00:00",
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": "rewards account has no USD wallet",
		},
		# accepted but not yet rewarded (KYC not approved yet)
		{
			"invite_id": "i4",
			"status": "ACCEPTED",
			"inviter_id": "acc-alice",
			"redeemed_by_id": "acc-erin",
			"contact": "erin@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"redeemed_at": "2026-07-31T10:00:00",
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		# sent but never redeemed — not in the table, counts toward funnel
		{
			"invite_id": "i5",
			"status": "SENT",
			"inviter_id": "acc-alice",
			"redeemed_by_id": None,
			"contact": "someone@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		# pending, never sent
		{
			"invite_id": "i6",
			"status": "PENDING",
			"inviter_id": "acc-bob",
			"redeemed_by_id": None,
			"contact": "pending@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
	]
	return invites, accounts


def test_summary_counts_and_disbursement():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=150, wallet_balance=100.0)
	s = out["summary"]

	assert s["total_invites"] == 6
	assert s["sent"] == 5  # i1..i4 accepted + i5 sent = 5 that were >= SENT
	assert s["accepted"] == 4  # i1..i4
	assert s["rewarded"] == 2  # paid + partial (i1, i2)
	assert s["paid"] == 1
	assert s["partial"] == 1
	assert s["failed"] == 1
	assert s["processing"] == 0
	assert s["needs_reconciliation"] == 2  # partial + failed

	# disbursed: i1 both parties @ $5 = $10; i2 one party @ $2.50 = $2.50; i3 none.
	assert s["total_disbursed_dollars"] == 12.50

	# tier state at seq 150 -> next referral (#151) is in the $2.50 band.
	assert s["counter_seq"] == 150
	assert s["current_tier_dollars"] == 2.5
	assert s["referrals_until_next_tier"] == 450  # 600 - 150
	# runway: balance 100 / ($2.50 * 2 parties) = 20 referrals
	assert s["wallet_balance_dollars"] == 100.0
	assert s["wallet_runway_referrals"] == 20


def test_disbursed_by_tier():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	tiers = {t["amount_dollars"]: t for t in out["summary"]["disbursed_by_tier"]}
	# $5 tier: i1 paid 2 parties = $10
	assert tiers[5.0]["count_parties"] == 2
	assert tiers[5.0]["dollars"] == 10.0
	# $2.50 tier: i2 paid 1 party = $2.50
	assert tiers[2.5]["count_parties"] == 1
	assert tiers[2.5]["dollars"] == 2.5


def test_rows_only_accepted_join_usernames_and_flags():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	rows = out["rows"]

	# Only the 4 ACCEPTED invites appear (SENT/PENDING excluded).
	assert len(rows) == 4
	assert {r["invite_id"] for r in rows} == {"i1", "i2", "i3", "i4"}

	# Newest-redeemed first.
	assert rows[0]["invite_id"] == "i4"

	by_id = {r["invite_id"]: r for r in rows}
	# usernames joined from accounts
	assert by_id["i1"]["invitee"] == "bob"
	assert by_id["i1"]["inviter"] == "alice"
	assert by_id["i1"]["inviter_paid"] is True
	assert by_id["i1"]["invitee_paid"] is True
	# partial: only invitee paid
	assert by_id["i2"]["inviter_paid"] is False
	assert by_id["i2"]["invitee_paid"] is True
	assert by_id["i2"]["reward_error"] == "inviter has no USD wallet"
	# unrewarded-but-accepted surfaces with status "unrewarded"
	assert by_id["i4"]["reward_status"] == "unrewarded"
	assert by_id["i4"]["reward_amount_dollars"] is None


def test_funnel_counts_and_conversion():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	funnel = {f["stage"]: f for f in out["funnel"]}

	assert funnel["Invited"]["count"] == 6
	assert funnel["Sent"]["count"] == 5
	assert funnel["Accepted"]["count"] == 4
	assert funnel["Rewarded"]["count"] == 2
	assert funnel["Invited"]["conversion"] is None
	assert funnel["Sent"]["conversion"] == 83.3  # 5 sent / 6 invited
	assert funnel["Accepted"]["conversion"] == 80.0  # 4 accepted / 5 sent
	assert funnel["Rewarded"]["conversion"] == 50.0  # 2 rewarded / 4 accepted


def test_wallet_balance_none_yields_no_runway():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0, wallet_balance=None)
	assert out["summary"]["wallet_balance_dollars"] is None
	assert out["summary"]["wallet_runway_referrals"] is None


def test_default_tiers_are_the_backend_schedule():
	# Guard against drift from the flash referralReward.tiers config.
	assert REWARD_TIERS == [
		{"upToCount": 100, "amountCents": 500},
		{"upToCount": 600, "amountCents": 250},
		{"upToCount": 0, "amountCents": 100},
	]

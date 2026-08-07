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


def test_bounded_last_tier_pays_zero_past_bound():
	# A misconfigured schedule with no unbounded sentinel must stop paying past
	# its last bound rather than extending the last rate forever. Mirrors the
	# backend referralRewardAmountCents fallthrough.
	bounded = [{"upToCount": 100, "amountCents": 500}]
	assert current_tier(50, bounded) == 500  # referral #51, in-bound
	assert current_tier(99, bounded) == 500  # referral #100, last in-bound
	assert current_tier(100, bounded) == 0  # referral #101, past the bound
	assert current_tier(5000, bounded) == 0


# ── build_overview ─────────────────────────────────────────────────────────


def _fixture():
	accounts = {
		"acc-alice": {"username": "alice"},
		"acc-bob": {"username": "bob"},
		"acc-carol": {"username": "carol"},
		"acc-dan": {"username": "dan"},
		"acc-erin": {"username": "erin"},
		"acc-frank": {"username": "frank"},
		"acc-gina": {"username": "gina"},
		"acc-hugo": {"username": "hugo"},
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
		# sent but never redeemed — a lifecycle table row, counts toward funnel
		{
			"invite_id": "i5",
			"status": "SENT",
			"inviter_id": "acc-alice",
			"redeemed_by_id": None,
			"contact": "someone@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"created_at": "2026-08-01T09:00:00",
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
			"created_at": "2026-07-27T09:00:00",
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		# sent, then expired unredeemed — stays in the "sent" funnel denominator
		{
			"invite_id": "i7",
			"status": "EXPIRED",
			"inviter_id": "acc-bob",
			"redeemed_by_id": None,
			"contact": "expired@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"created_at": "2026-07-26T09:00:00",
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		# pending payout — IBEX accepted both sends, confirmation outstanding.
		# Backend sets per-party timestamps (fail-closed) but rewardStatus stays
		# "pending" until re-checked.
		{
			"invite_id": "i8",
			"status": "ACCEPTED",
			"inviter_id": "acc-gina",
			"redeemed_by_id": "acc-hugo",
			"contact": "hugo@x.com",
			"reward_status": "pending",
			"reward_seq": 5,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-27T10:00:00",
			"rewarded_at": None,
			"inviter_rewarded_at": "2026-07-27T12:00:00",
			"invitee_rewarded_at": "2026-07-27T12:00:00",
			"reward_error": "inviter=pending invitee=pending",
		},
	]
	return invites, accounts


def test_summary_counts_and_disbursement():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=150, wallet_balance=100.0)
	s = out["summary"]

	assert s["total_invites"] == 8
	assert s["sent"] == 7  # everything except the never-sent PENDING i6
	assert s["accepted"] == 5  # i1..i4 + i8
	assert s["rewarded"] == 3  # paid + partial + pending (i1, i2, i8)
	assert s["paid"] == 1
	assert s["partial"] == 1
	assert s["failed"] == 1
	assert s["processing"] == 0
	assert s["pending"] == 1
	assert s["unknown"] == 0
	assert s["unrewarded"] == 1  # i4: accepted, KYC not approved yet
	assert s["invites_sent_open"] == 1  # i5: delivered, awaiting redemption
	assert s["invites_expired"] == 1  # i7
	assert s["needs_reconciliation"] == 3  # partial + failed + pending + unknown

	# disbursed: i1 both @ $5 = $10; i2 one @ $2.50 = $2.50; i8 both @ $5 = $10.
	assert s["total_disbursed_dollars"] == 22.50

	# tier state at seq 150 -> next referral (#151) is in the $2.50 band.
	assert s["counter_seq"] == 150
	assert s["current_tier_dollars"] == 2.5
	assert s["referrals_until_next_tier"] == 450  # 600 - 150
	# runway: balance 100 / ($2.50 * 2 parties) = 20 referrals
	assert s["wallet_balance_dollars"] == 100.0
	assert s["wallet_runway_referrals"] == 20


def test_expired_counts_as_sent_not_accepted():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	funnel = {f["stage"]: f for f in out["funnel"]}

	# i7 (EXPIRED) stays in the Sent denominator so Accepted% isn't inflated,
	# and never counts as Accepted. It DOES appear in the table — as a
	# lifecycle row, not a reward row.
	assert funnel["Sent"]["count"] == 7
	assert funnel["Accepted"]["count"] == 5
	i7 = next(r for r in out["rows"] if r["invite_id"] == "i7")
	assert i7["reward_status"] == "expired"


def test_disbursed_by_tier():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	tiers = {t["amount_dollars"]: t for t in out["summary"]["disbursed_by_tier"]}
	# $5 tier: i1 (2 parties) + i8 pending (2 parties, timestamps set) = $20
	assert tiers[5.0]["count_parties"] == 4
	assert tiers[5.0]["dollars"] == 20.0
	# $2.50 tier: i2 paid 1 party = $2.50
	assert tiers[2.5]["count_parties"] == 1
	assert tiers[2.5]["dollars"] == 2.5


def test_rows_include_all_invites_join_usernames_and_flags():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	rows = out["rows"]

	# EVERY invite is a row — redeemed ones carry the reward lifecycle,
	# un-redeemed ones (SENT/PENDING/EXPIRED) the invite lifecycle.
	assert len(rows) == 8
	assert {r["invite_id"] for r in rows} == {f"i{n}" for n in range(1, 9)}

	# Newest-first by redeemed_at, falling back to created_at for
	# un-redeemed rows (i5 was created after every redemption).
	assert [r["invite_id"] for r in rows] == ["i5", "i4", "i1", "i2", "i3", "i8", "i6", "i7"]

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
	# pending: both party timestamps set, status stays "pending"
	assert by_id["i8"]["reward_status"] == "pending"
	assert by_id["i8"]["inviter_paid"] is True
	assert by_id["i8"]["invitee_paid"] is True
	# lifecycle rows: reward column mirrors the invite status; the invitee cell
	# falls back to the contact; the inviter username still joins.
	assert by_id["i5"]["reward_status"] == "sent"
	assert by_id["i5"]["invitee"] == "someone@x.com"
	assert by_id["i5"]["inviter"] == "alice"
	assert by_id["i5"]["reward_amount_dollars"] is None
	assert by_id["i5"]["created_at"] == "2026-08-01T09:00:00"
	# PENDING maps to "unsent" — NEVER "pending", which the IBEX reward bucket owns.
	assert by_id["i6"]["reward_status"] == "unsent"
	assert by_id["i7"]["reward_status"] == "expired"


def test_row_cap_truncates_rows_but_not_summary():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0, max_rows=2)

	# Actionable rows (partial i2, failed i3, pending i8) always survive the
	# cap; paid/unrewarded AND un-redeemed lifecycle rows consume the budget
	# (here: none, since the 3 actionable rows already exceed max_rows=2).
	# Summary covers everything.
	assert [r["invite_id"] for r in out["rows"]] == ["i2", "i3", "i8"]
	assert out["summary"]["rows_total"] == 8
	assert out["summary"]["rows_shown"] == 3
	assert out["summary"]["accepted"] == 5
	assert out["summary"]["total_disbursed_dollars"] == 22.50

	# Uncapped run reports full counts.
	full = build_overview(invites, accounts, counter_seq=0)
	assert full["summary"]["rows_total"] == 8
	assert full["summary"]["rows_shown"] == 8


def test_row_cap_never_hides_actionable_rows():
	# An OLD failed row must survive a cap that newer paid rows would otherwise
	# fill; newest-first order is preserved; the budget goes to paid rows.
	accounts = {}
	invites = []
	for i in range(5):
		invites.append(
			{
				"invite_id": f"paid-{i}",
				"status": "ACCEPTED",
				"inviter_id": None,
				"redeemed_by_id": None,
				"contact": f"p{i}@x.com",
				"reward_status": "paid",
				"reward_seq": i + 1,
				"reward_amount_cents": 500,
				"redeemed_at": f"2026-07-2{i + 3}T10:00:00",  # 23..27, all newer
				"rewarded_at": f"2026-07-2{i + 3}T11:00:00",
				"inviter_rewarded_at": f"2026-07-2{i + 3}T11:00:00",
				"invitee_rewarded_at": f"2026-07-2{i + 3}T11:00:00",
				"reward_error": None,
			}
		)
	invites.append(
		{
			"invite_id": "old-failed",
			"status": "ACCEPTED",
			"inviter_id": None,
			"redeemed_by_id": None,
			"contact": "old@x.com",
			"reward_status": "failed",
			"reward_seq": 99,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-01T10:00:00",  # oldest of all
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": "rewards account not configured",
		}
	)

	out = build_overview(invites, accounts, counter_seq=0, max_rows=3)
	ids = [r["invite_id"] for r in out["rows"]]

	# The oldest row survives because it is actionable; two newest paid rows
	# fill the remaining budget; overall order stays newest-first.
	assert ids == ["paid-4", "paid-3", "old-failed"]
	assert out["summary"]["rows_total"] == 6
	assert out["summary"]["rows_shown"] == 3


def test_unknown_reward_status_is_fail_visible():
	# A rewardStatus this page doesn't know (backend drift) must land in
	# needs_reconciliation + an explicit unknown count, and survive the row cap.
	accounts = {}
	invites = [
		{
			"invite_id": "drift-1",
			"status": "ACCEPTED",
			"inviter_id": None,
			"redeemed_by_id": None,
			"contact": "drift@x.com",
			"reward_status": "refunded",  # not a status this page knows
			"reward_seq": 7,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-01T10:00:00",
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		{
			"invite_id": "ok-1",
			"status": "ACCEPTED",
			"inviter_id": None,
			"redeemed_by_id": None,
			"contact": "ok@x.com",
			"reward_status": "paid",
			"reward_seq": 8,
			"reward_amount_cents": 500,
			"redeemed_at": "2026-07-02T10:00:00",
			"rewarded_at": "2026-07-02T11:00:00",
			"inviter_rewarded_at": "2026-07-02T11:00:00",
			"invitee_rewarded_at": "2026-07-02T11:00:00",
			"reward_error": None,
		},
	]

	out = build_overview(invites, accounts, counter_seq=0, max_rows=1)
	s = out["summary"]

	assert s["unknown"] == 1
	assert s["needs_reconciliation"] == 1  # the drifted row, nothing else
	# The drifted row is actionable: it survives a cap of 1 alongside no paid
	# budget (actionable_total=1 -> budget=0 -> paid row truncated).
	assert [r["invite_id"] for r in out["rows"]] == ["drift-1"]
	# The row carries the raw drifted status for the UI to render (warn tone).
	assert out["rows"][0]["reward_status"] == "refunded"


def test_funnel_counts_and_conversion():
	invites, accounts = _fixture()
	out = build_overview(invites, accounts, counter_seq=0)
	funnel = {f["stage"]: f for f in out["funnel"]}

	assert funnel["Invited"]["count"] == 8
	assert funnel["Sent"]["count"] == 7
	assert funnel["Accepted"]["count"] == 5
	assert funnel["Rewarded"]["count"] == 3
	assert funnel["Invited"]["conversion"] is None
	assert funnel["Sent"]["conversion"] == 87.5  # 7 sent / 8 invited
	assert funnel["Accepted"]["conversion"] == 71.4  # 5 accepted / 7 sent
	assert funnel["Rewarded"]["conversion"] == 60.0  # 3 rewarded / 5 accepted


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


def test_unredeemed_lifecycle_rows_consume_cap_budget():
	# Lifecycle rows (sent/unsent/expired) are informational — they must consume
	# the cap budget like paid rows, never bypass it like actionable rows do.
	accounts = {}
	invites = [
		{
			"invite_id": "sent-new",
			"status": "SENT",
			"inviter_id": None,
			"redeemed_by_id": None,
			"contact": "new@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"created_at": "2026-08-02T09:00:00",
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
		{
			"invite_id": "revoked-1",  # a lifecycle status this page doesn't know
			"status": "REVOKED",
			"inviter_id": None,
			"redeemed_by_id": None,
			"contact": "rev@x.com",
			"reward_status": None,
			"reward_seq": None,
			"reward_amount_cents": None,
			"created_at": "2026-08-01T09:00:00",
			"redeemed_at": None,
			"rewarded_at": None,
			"inviter_rewarded_at": None,
			"invitee_rewarded_at": None,
			"reward_error": None,
		},
	]

	out = build_overview(invites, accounts, counter_seq=0, max_rows=1)
	# Neither row is actionable, so the cap truncates to exactly 1 (the newest).
	assert [r["invite_id"] for r in out["rows"]] == ["sent-new"]
	assert out["summary"]["rows_total"] == 2
	assert out["summary"]["rows_shown"] == 1

	# Unknown lifecycle statuses lowercase into the reward column (fail-visible
	# via the page's unknown-tone fallback), and never collide with "pending".
	full = build_overview(invites, accounts, counter_seq=0)
	by_id = {r["invite_id"]: r for r in full["rows"]}
	assert by_id["revoked-1"]["reward_status"] == "revoked"
	assert by_id["sent-new"]["reward_status"] == "sent"

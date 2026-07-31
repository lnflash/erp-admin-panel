# Referral Rewards page

A live ops view of the invite/refer-a-friend reward payouts.

## What it shows

- **Summary tiles** — total disbursed (USD), referrals paid (the global tier
  counter), current tier amount + how many referrals until the rate drops, the
  funding wallet's live balance + estimated runway, a "needs reconciliation"
  count, and per-tier disbursement totals.
- **Funnel** — Invited → Sent → Accepted (redeemed) → Rewarded, with
  stage-over-stage conversion.
- **Per-referral table** — every redeemed (`ACCEPTED`) invite: invitee, inviter,
  amount, tier sequence, reward status (paid / partial / failed / processing /
  unrewarded), per-party paid ✓/✗, any error, and when. Filterable by status;
  the "Needs Reconciliation" tile and the Partial/Failed chips surface the
  actionable rows.

## Data sources (Flash `galoy` mongo, read-only)

- `invites` — reward fields written by the backend payout
  (`rewardStatus`, `rewardSeq`, `rewardAmountCents`, `rewardedAt`,
  `inviterRewardedAt`, `inviteeRewardedAt`, `rewardError`).
- `referralrewardcounters` — the global `seq` that drives the tier.
- `accounts` — joined by `inviterId` / `redeemedById` for usernames.
- IBEX (best-effort) — the `rewards`-role account's USD wallet balance. The page
  degrades gracefully (balance shows "—") when IBEX/mongo isn't configured.

Loaders: `admin_panel/api/mongo_reader.py` (`load_invites`, `load_reward_counter`).
Endpoint: `admin_panel.api.referral_rewards.get_referral_rewards`.
Pure logic: `admin_panel/api/referral_rewards_core.py` (`build_overview`).

## Tier schedule

`REWARD_TIERS` in `referral_rewards_core.py` mirrors the backend default:
referrals 1–100 → **$5.00** each party, 101–600 → **$2.50**, 601+ → **$1.00**.
**Keep it in sync** with the flash backend `referralReward.tiers` config
(`flash/src/config/schema.ts`) if the schedule is retuned there.

## Tests

```bash
cd ~/Repos/frappe-flash-admin
pytest admin_panel/tests/test_referral_rewards_core.py admin_panel/tests/test_referral_rewards_page_contract.py -q
```

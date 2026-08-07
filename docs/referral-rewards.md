# Referral Rewards page

A live ops view of the invite/refer-a-friend reward payouts.

## What it shows

- **Summary tiles** — total disbursed (USD), referrals counted (the global tier
  counter — it counts tier-consuming payout *attempts*, including failed ones,
  not successful payouts), current tier amount + how many referrals until the
  rate drops, the funding wallet's live balance + estimated runway, a "needs
  reconciliation" count, and per-tier disbursement totals.
- **Funnel** — Invited → Sent → Accepted (redeemed) → Rewarded, with
  stage-over-stage conversion. "Sent" includes sent-then-**EXPIRED** invites so
  the Accepted% denominator is honest (the invite model has no `sentAt`, so the
  rare admin-revoked PENDING→EXPIRED invite is also counted as sent).
- **Per-invite table** — every invite: redeemed (`ACCEPTED`) rows carry the
  reward lifecycle; un-redeemed rows show the invite lifecycle (`sent` /
  `unsent` / `expired`) in the reward column with the contact as the invitee.
  Redeemed rows: invitee, inviter,
  amount, tier sequence, reward status (paid / pending / partial / failed /
  processing / unrewarded), per-party paid ✓/✗, any error, and when. Filterable
  by status; the "Needs Reconciliation" tile and the Pending/Partial/Failed
  chips surface the actionable rows. The row list is capped server-side at the
  **latest 200**, but actionable rows (failed / partial / pending / processing /
  unknown) always bypass the cap — only paid/unrewarded rows are truncated — so
  every row ops must reconcile is reachable (the status line shows "showing
  latest N of M" when truncated); summary aggregates always cover every invite.
  An unknown (drifted) `rewardStatus` from a newer backend is counted in an
  explicit `unknown` bucket, added to Needs Reconciliation, and rendered with a
  warning tone — backend drift is fail-visible, never fail-quiet.

## Reward statuses

| status | meaning |
|---|---|
| `paid` | both parties confirmed paid |
| `pending` | IBEX accepted ≥1 payment but hasn't confirmed it — per-party timestamps are set (fail-closed, no double-pay); **needs ops re-check** |
| `partial` | exactly one party paid, the other failed |
| `failed` | no party paid |
| `processing` | payout claimed but not finished (crash-recovery marker) |
| `unrewarded` | redeemed, invitee's Bridge KYC not approved yet |

`needs_reconciliation` = partial + failed + pending.

## Data sources (Flash `galoy` mongo, read-only)

- `invites` — reward fields written by the backend payout
  (`rewardStatus`, `rewardSeq`, `rewardAmountCents`, `rewardedAt`,
  `inviterRewardedAt`, `inviteeRewardedAt`, `rewardError`).
- `referralrewardcounters` — the global `seq` that drives the tier.
- `accounts` — joined by `inviterId` / `redeemedById` for usernames.
- IBEX (best-effort) — the `rewards`-role account's funding-wallet balance,
  resolved with the **same USDT-then-USD preference the backend payout uses**,
  so the balance shown is the wallet payouts actually draw from. The page
  degrades gracefully (balance shows "—") when IBEX/mongo isn't configured.

Loaders: `admin_panel/api/mongo_reader.py` (`load_invites`, `load_reward_counter`).
Endpoint: `admin_panel.api.referral_rewards.get_referral_rewards`.
Pure logic: `admin_panel/api/referral_rewards_core.py` (`build_overview`).

## Tier schedule

`REWARD_TIERS` in `referral_rewards_core.py` mirrors the backend default:
referrals 1–100 → **$5.00** each party, 101–600 → **$2.50**, 601+ → **$1.00**.
Past every bounded tier, the amount is the last tier's **only if that tier is
unbounded** (`upToCount <= 0`); a schedule missing the unbounded sentinel pays
0 rather than silently extending the last bounded rate forever — this matches
the backend `referralRewardAmountCents` fallthrough. **Keep both the schedule
and the fallthrough rule in sync** with the flash backend
(`flash/src/config/schema.ts` + `flash/src/domain/invite/referral-reward.ts`)
if either is retuned there.

## Tests

```bash
cd ~/Repos/frappe-flash-admin
pytest admin_panel/tests/test_referral_rewards_core.py admin_panel/tests/test_referral_rewards_page_contract.py -q
```

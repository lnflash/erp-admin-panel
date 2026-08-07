"""Pure aggregation logic for the Referral Rewards page.

Imports NOTHING from frappe, the mongo driver, or the network layer, so it can
be unit-tested against fixtures with plain `pytest`. All IO (mongo + IBEX) lives
in `referral_rewards.py` and `mongo_reader.py`.

Data comes from the Flash `invites` collection (reward-payout fields) joined to
`accounts` (usernames) plus the global `referralrewardcounters` sequence.
"""

# Tiered per-party reward schedule, in USD cents, by cumulative referral count.
# KEEP IN SYNC with the flash backend `referralReward.tiers` config
# (flash/src/config/schema.ts) AND `referralRewardAmountCents`
# (flash/src/domain/invite/referral-reward.ts): `upToCount <= 0` marks the
# final unbounded tier; past every bounded tier the amount is the last tier's
# only when that tier is unbounded, else 0 (a schedule missing the sentinel
# stops paying rather than silently extending the last bounded rate forever).
REWARD_TIERS = [
	{"upToCount": 100, "amountCents": 500},
	{"upToCount": 600, "amountCents": 250},
	{"upToCount": 0, "amountCents": 100},
]

# rewardStatus values where money (at least partly) went out the door.
# "pending" = an IBEX payment accepted but not yet confirmed — the backend sets
# the per-party timestamps for pending parties (fail-closed, no double-pay) and
# the status needs ops re-checking, so it counts as rewarded AND as
# needs-reconciliation.
REWARDED_STATUSES = {"paid", "partial", "pending"}

# Statuses the known-bucket counters track. Anything else non-null is backend
# drift (a new status this page doesn't know) — counted as "unknown" and routed
# into needs_reconciliation so drift is fail-visible, never fail-quiet.
KNOWN_REWARD_STATUSES = ("paid", "partial", "failed", "processing", "pending")


def _is_actionable(row):
	"""Rows ops must be able to reach: redeemed rows in any state except clean
	'paid' and not-yet-rewarded. Unknown (drifted) reward statuses are actionable
	by definition. Un-redeemed rows (sent/expired/...) are lifecycle info, never
	actionable — they must not bypass the row cap."""
	if row.get("status") != "ACCEPTED":
		return False
	return row.get("reward_status") not in ("paid", "unrewarded")


def _tier_amount_cents(tiers, seq):
	"""Per-party amount (cents) for the 1-based referral sequence number `seq`."""
	for tier in tiers:
		up_to = tier.get("upToCount", 0)
		if up_to > 0 and seq <= up_to:
			return tier.get("amountCents", 0)
	if not tiers:
		return 0
	last = tiers[-1]
	# Past every bounded tier: pay the final tier only if it is explicitly
	# unbounded. Mirrors the backend's referralRewardAmountCents fallthrough.
	return last.get("amountCents", 0) if last.get("upToCount", 0) <= 0 else 0


def current_tier(seq, tiers=REWARD_TIERS):
	"""Amount (cents) the NEXT referral (seq+1) will pay EACH party."""
	return _tier_amount_cents(tiers, (seq or 0) + 1)


def referrals_until_next_tier(seq, tiers=REWARD_TIERS):
	"""How many more referrals before the per-party amount drops (None if final)."""
	seq = seq or 0
	for tier in tiers:
		up_to = tier.get("upToCount", 0)
		if up_to > 0 and up_to > seq:
			return up_to - seq
	return None


def _pct(n, d):
	return round(100.0 * n / d, 1) if d else None


def build_overview(invites, accounts, counter_seq, tiers=REWARD_TIERS, wallet_balance=None, max_rows=200):
	"""Join invites to accounts and roll up the referral-reward picture.

	Args:
	    invites: list of invite dicts (see mongo_reader.load_invites) — snake_case.
	    accounts: str(account _id) -> {username, ...} (mongo_reader.load_accounts).
	    counter_seq: int, the global referral sequence so far.
	    tiers: the reward schedule.
	    wallet_balance: live USD balance of the funding wallet, or None.
	    max_rows: cap on the returned row list (newest first). Actionable rows
	        (anything except clean "paid" / "unrewarded") ALWAYS survive the cap —
	        only paid/unrewarded rows are truncated — so every row ops must act on
	        is reachable. The summary aggregates still cover every invite.
	        None = no cap.

	Returns {rows, summary, funnel}, all JSON-serializable.
	"""
	rows = []
	status_counts = {status: 0 for status in KNOWN_REWARD_STATUSES}
	unknown = 0
	unrewarded = 0
	invites_sent_open = 0  # SENT: delivered, awaiting redemption
	invites_expired = 0  # EXPIRED: never redeemed (or revoked)
	total_invites = len(invites)
	sent = 0
	accepted = 0
	rewarded = 0
	total_disbursed_cents = 0
	by_tier = {}  # amount_cents -> {amount_dollars, count_parties, dollars}

	for inv in invites:
		status = inv.get("status")
		reward_status = inv.get("reward_status")

		# EXPIRED invites were (almost always) sent first — the backend flips
		# SENT -> EXPIRED on a post-expiry redemption attempt or admin revoke —
		# so they stay in the "sent" denominator to keep Accepted% honest. The
		# rare PENDING -> EXPIRED admin-revoke slightly overcounts "sent".
		if status in ("SENT", "ACCEPTED", "EXPIRED"):
			sent += 1
		if status == "ACCEPTED":
			accepted += 1
		if reward_status in REWARDED_STATUSES:
			rewarded += 1
		if reward_status in status_counts:
			status_counts[reward_status] += 1
		elif reward_status:
			# A status this page doesn't know — backend drift. Fail-visible.
			unknown += 1

		amount_cents = inv.get("reward_amount_cents") or 0
		inviter_paid = bool(inv.get("inviter_rewarded_at"))
		invitee_paid = bool(inv.get("invitee_rewarded_at"))
		parties_paid = (1 if inviter_paid else 0) + (1 if invitee_paid else 0)
		if parties_paid and amount_cents:
			disbursed = amount_cents * parties_paid
			total_disbursed_cents += disbursed
			bucket = by_tier.setdefault(
				amount_cents,
				{"amount_dollars": amount_cents / 100.0, "count_parties": 0, "dollars": 0.0},
			)
			bucket["count_parties"] += parties_paid
			bucket["dollars"] += disbursed / 100.0

		# Every invite is a table row. ACCEPTED (redeemed) rows carry the reward
		# lifecycle; un-redeemed rows (SENT/EXPIRED/anything else) surface the
		# invite lifecycle in the reward column instead — lowercased, so an
		# unknown backend status renders fail-visible (the page tones unlisted
		# values as warnings), matching the reward-status drift philosophy.
		inviter = accounts.get(inv.get("inviter_id")) or {}
		if status == "ACCEPTED":
			if not reward_status:
				unrewarded += 1
			invitee = accounts.get(inv.get("redeemed_by_id")) or {}
			row_invitee = invitee.get("username") or inv.get("contact") or "—"
			row_reward_status = reward_status or "unrewarded"
		else:
			row_invitee = inv.get("contact") or "—"
			if status == "SENT":
				invites_sent_open += 1
				row_reward_status = "sent"
			elif status == "EXPIRED":
				invites_expired += 1
				row_reward_status = "expired"
			elif status == "PENDING":
				# "unsent", NOT "pending": the IBEX reward-status bucket already
				# owns "pending" — a lifecycle collision would leak these rows
				# into the money-moved reconciliation filter.
				row_reward_status = "unsent"
			else:
				row_reward_status = (status or "unknown").lower()
		rows.append(
			{
				"invite_id": inv.get("invite_id"),
				"invitee": row_invitee,
				"inviter": inviter.get("username") or "—",
				"status": status,
				"reward_status": row_reward_status,
				"reward_amount_dollars": (amount_cents / 100.0) if amount_cents else None,
				"reward_seq": inv.get("reward_seq"),
				"created_at": inv.get("created_at"),
				"redeemed_at": inv.get("redeemed_at"),
				"rewarded_at": inv.get("rewarded_at"),
				"inviter_paid": inviter_paid,
				"invitee_paid": invitee_paid,
				"reward_error": inv.get("reward_error"),
			}
		)

	rows.sort(key=lambda r: (r.get("redeemed_at") or r.get("created_at") or ""), reverse=True)
	rows_total = len(rows)
	if max_rows is not None and rows_total > max_rows:
		# Actionable rows (failed/partial/pending/processing/unknown) must never
		# be hidden by the cap — they are the rare rows ops has to reconcile.
		# Only paid/unrewarded rows consume the cap budget; overall newest-first
		# order is preserved by the single pass over the sorted list.
		actionable_total = sum(1 for r in rows if _is_actionable(r))
		budget = max(0, max_rows - actionable_total)
		kept = []
		for r in rows:
			if _is_actionable(r):
				kept.append(r)
			elif budget > 0:
				kept.append(r)
				budget -= 1
		rows = kept

	current_tier_cents = current_tier(counter_seq, tiers)
	current_tier_dollars = current_tier_cents / 100.0
	runway = None
	if wallet_balance is not None and current_tier_dollars > 0:
		# Two parties per referral, so each qualified referral costs 2x the tier.
		runway = int(wallet_balance // (current_tier_dollars * 2))

	tier_breakdown = [
		{
			"amount_dollars": v["amount_dollars"],
			"count_parties": v["count_parties"],
			"dollars": round(v["dollars"], 2),
		}
		for _cents, v in sorted(by_tier.items(), key=lambda kv: -kv[0])
	]

	summary = {
		"total_invites": total_invites,
		"sent": sent,
		"accepted": accepted,
		"rewarded": rewarded,
		"paid": status_counts["paid"],
		"partial": status_counts["partial"],
		"failed": status_counts["failed"],
		"processing": status_counts["processing"],
		"pending": status_counts["pending"],
		"unknown": unknown,
		"unrewarded": unrewarded,
		"invites_sent_open": invites_sent_open,
		"invites_expired": invites_expired,
		"needs_reconciliation": (
			status_counts["partial"] + status_counts["failed"] + status_counts["pending"] + unknown
		),
		"total_disbursed_dollars": round(total_disbursed_cents / 100.0, 2),
		"disbursed_by_tier": tier_breakdown,
		"counter_seq": counter_seq or 0,
		"current_tier_dollars": current_tier_dollars,
		"referrals_until_next_tier": referrals_until_next_tier(counter_seq, tiers),
		"wallet_balance_dollars": wallet_balance,
		"wallet_runway_referrals": runway,
		"rows_total": rows_total,
		"rows_shown": len(rows),
	}

	funnel = [
		{"stage": "Invited", "count": total_invites, "conversion": None},
		{"stage": "Sent", "count": sent, "conversion": _pct(sent, total_invites)},
		{"stage": "Accepted", "count": accepted, "conversion": _pct(accepted, sent)},
		{"stage": "Rewarded", "count": rewarded, "conversion": _pct(rewarded, accepted)},
	]

	return {"rows": rows, "summary": summary, "funnel": funnel}

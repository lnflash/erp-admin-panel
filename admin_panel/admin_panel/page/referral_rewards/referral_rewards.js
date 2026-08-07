const RR_ALLOWED_ROLES = ["Accounts Manager", "Flash Admin", "System Manager"];

// Reward-status buckets (clickable filters). Keys match the invite rewardStatus
// (plus "unrewarded" for accepted-but-not-yet-paid, "sent"/"expired" for
// un-redeemed invite lifecycle rows, and "all").
const RR_BUCKETS = [
	{ key: "all", label: "All" },
	{ key: "paid", label: "Paid" },
	{ key: "pending", label: "Pending" },
	{ key: "partial", label: "Partial" },
	{ key: "failed", label: "Failed" },
	{ key: "processing", label: "Processing" },
	{ key: "unrewarded", label: "Unrewarded" },
	{ key: "sent", label: "Sent" },
	{ key: "expired", label: "Expired" },
];

const RR_STATUS_TONE = {
	paid: "ok",
	// "pending" = IBEX accepted the payment but hasn't confirmed it — money
	// probably moved; ops must re-check, so it tones as a warning.
	pending: "warn",
	partial: "warn",
	failed: "bad",
	processing: "warn",
	unrewarded: "",
	// Un-redeemed invite lifecycle rows — informational, not actionable.
	sent: "",
	expired: "",
	// PENDING invite (created, delivery unconfirmed) — mapped server-side to
	// "unsent" so it can't collide with the IBEX reward "pending" bucket. A
	// stuck-unsent invite is worth a second look, so it tones as a warning.
	unsent: "warn",
};

const RR_CSS = `
    .referral-rewards-page { --rr-surface: var(--card-bg, #ffffff); --rr-ink: var(--text-color, #1a2420);
          --rr-ink2: var(--text-muted, #5c6b65); --rr-ink3: var(--text-light, #8fa098);
          --rr-line: var(--border-color, #e2e8e5); --rr-line-soft: var(--subtle-fg, #ecf1ee);
          --rr-accent: #007856; --rr-accent-ink: #007856; --rr-accent-soft: #e6f3ee;
          --rr-good: #0ca30c; --rr-warn: #b87d00; --rr-warn-bg: #fff3d6;
          --rr-serious: #c05a32; --rr-serious-bg: #fdeae2;
          --rr-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
          max-width: 1240px; margin: 0 auto; }
    [data-theme="dark"] .referral-rewards-page, .dark .referral-rewards-page {
          --rr-accent: #1e9e75; --rr-accent-ink: #4cc29e; --rr-accent-soft: #12352a;
          --rr-good: #35c135; --rr-warn: #fab219; --rr-warn-bg: #33290d;
          --rr-serious: #ec835a; --rr-serious-bg: #38211a;
          --rr-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25); }
    .referral-rewards-page .rr-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .referral-rewards-page .rr-input { border: 1px solid var(--rr-line); border-radius: 9px; padding: 7px 12px;
          font-size: 13px; background: var(--rr-surface); color: var(--rr-ink); }
    .referral-rewards-page .rr-input:focus { outline: 2px solid var(--rr-accent); outline-offset: 1px; border-color: var(--rr-accent); }
    .referral-rewards-page .rr-btn { border: 1px solid var(--rr-line); background: var(--rr-surface); color: var(--rr-ink);
          border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 600; cursor: pointer; transition: border-color 0.15s; }
    .referral-rewards-page .rr-btn:hover { border-color: var(--rr-accent); }
    .referral-rewards-page .rr-btn.primary { background: var(--rr-accent); border-color: var(--rr-accent); color: #fff; }
    .referral-rewards-page .rr-meta { color: var(--rr-ink2); font-size: 12.5px; margin: 0 0 14px; }
    .referral-rewards-page .rr-meta .err { color: var(--rr-serious); font-weight: 600; }
    .referral-rewards-page .rr-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-bottom: 16px; }
    .referral-rewards-page .rr-tile { background: var(--rr-surface); border: 1px solid var(--rr-line); border-radius: 14px;
          padding: 15px 17px 12px; box-shadow: var(--rr-shadow); display: flex; flex-direction: column; gap: 5px; min-height: 100px; }
    .referral-rewards-page .rr-tile.alert-tile { border-color: var(--rr-serious); }
    .referral-rewards-page .rr-tile-label { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--rr-ink2); font-weight: 600; }
    .referral-rewards-page .rr-tile-value { font-size: 26px; font-weight: 650; letter-spacing: -0.015em; line-height: 1.1; color: var(--rr-ink); }
    .referral-rewards-page .rr-tile-value.bad { color: var(--rr-serious); }
    .referral-rewards-page .rr-tile-sub { color: var(--rr-ink3); font-size: 12px; margin-top: auto; }
    .referral-rewards-page .rr-funnel { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
    .referral-rewards-page .rr-funnel-step { background: var(--rr-surface); border: 1px solid var(--rr-line); border-radius: 12px;
          padding: 10px 16px; box-shadow: var(--rr-shadow); min-width: 130px; }
    .referral-rewards-page .rr-funnel-step .n { font-size: 21px; font-weight: 650; color: var(--rr-ink); }
    .referral-rewards-page .rr-funnel-step .l { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--rr-ink2); font-weight: 600; }
    .referral-rewards-page .rr-funnel-step .c { font-size: 11.5px; color: var(--rr-accent-ink); font-weight: 600; }
    .referral-rewards-page .rr-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .referral-rewards-page .rr-bucket { border: 1px solid var(--rr-line); background: var(--rr-surface); color: var(--rr-ink2);
          border-radius: 999px; padding: 5px 13px; font-size: 12.5px; font-weight: 600; cursor: pointer; transition: all 0.12s; }
    .referral-rewards-page .rr-bucket:hover { border-color: var(--rr-accent); color: var(--rr-ink); }
    .referral-rewards-page .rr-bucket.active { background: var(--rr-accent); border-color: var(--rr-accent); color: #fff; }
    .referral-rewards-page .rr-bucket .badge { font-weight: 650; margin-left: 5px; opacity: 0.75; }
    .referral-rewards-page .rr-card { background: var(--rr-surface); border: 1px solid var(--rr-line); border-radius: 14px;
          box-shadow: var(--rr-shadow); overflow: hidden; }
    .referral-rewards-page .rr-count { color: var(--rr-ink3); font-size: 12px; padding: 12px 18px 0; }
    .referral-rewards-page table.rr-table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 8px 0 0; }
    .referral-rewards-page table.rr-table th { text-align: left; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase;
          color: var(--rr-ink2); font-weight: 650; padding: 10px 18px; border-bottom: 1px solid var(--rr-line); white-space: nowrap; }
    .referral-rewards-page table.rr-table td { padding: 9px 18px; border-bottom: 1px solid var(--rr-line-soft); color: var(--rr-ink);
          font-variant-numeric: tabular-nums; }
    .referral-rewards-page table.rr-table tr:last-child td { border-bottom: none; }
    .referral-rewards-page table.rr-table code { background: transparent; color: var(--rr-ink3); font-size: 12px; }
    .referral-rewards-page .rr-chip-st { display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 11px;
          font-size: 12px; font-weight: 600; background: var(--rr-line-soft); color: var(--rr-ink2); }
    .referral-rewards-page .rr-chip-st.ok { background: var(--rr-accent-soft); color: var(--rr-accent-ink); }
    .referral-rewards-page .rr-chip-st.warn { background: var(--rr-warn-bg); color: var(--rr-warn); }
    .referral-rewards-page .rr-chip-st.bad { background: var(--rr-serious-bg); color: var(--rr-serious); }
    .referral-rewards-page .rr-yes { color: var(--rr-good); font-weight: 650; }
    .referral-rewards-page .rr-no { color: var(--rr-ink3); }
    .referral-rewards-page .rr-err { color: var(--rr-serious); font-size: 11.5px; }
    .referral-rewards-page .alert { border-radius: 12px; border: 1px solid var(--rr-line); padding: 12px 16px; font-size: 13px; }
    .referral-rewards-page .alert-warning { background: var(--rr-warn-bg); color: var(--rr-warn); border-color: transparent; }
    .referral-rewards-page .alert-danger { background: var(--rr-serious-bg); color: var(--rr-serious); border-color: transparent; }
`;

// Relative time from an ISO timestamp against the SERVER clock (`nowIso` from
// the payload). Uses Date.parse only — never the viewer's local wall clock — so
// the label reflects server time even if the browser clock is skewed.
function rr_ago(iso, nowIso) {
	if (!iso) return "—";
	const then = Date.parse(iso);
	const now = Date.parse(nowIso || "");
	if (isNaN(then) || isNaN(now)) return (iso || "").slice(0, 10);
	let s = Math.max(0, Math.floor((now - then) / 1000));
	if (s < 60) return "just now";
	const m = Math.floor(s / 60);
	if (m < 60) return `${m}m ago`;
	const h = Math.floor(m / 60);
	if (h < 24) return `${h}h ago`;
	const d = Math.floor(h / 24);
	return `${d}d ago`;
}

function rr_money(v) {
	if (v === null || v === undefined) return "—";
	return `$${Number(v).toLocaleString(undefined, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	})}`;
}

frappe.pages["referral-rewards"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Referral Rewards",
		single_column: true,
	});

	const allowed =
		frappe.session.user === "Administrator" ||
		RR_ALLOWED_ROLES.some((r) => frappe.user_roles.includes(r));
	if (!allowed) {
		page.main.html(`
            <div class="text-center mt-5">
                <div class="alert alert-warning">
                    <h4>Access Denied</h4>
                    <p>You do not have permission to access this page. Please contact your administrator to get one of the "Accounts Manager", "Flash Admin", or "System Manager" roles.</p>
                </div>
            </div>
        `);
		return;
	}

	wrapper.referral_rewards = new ReferralRewards(page);
};

frappe.pages["referral-rewards"].on_page_show = function (wrapper) {
	if (wrapper.referral_rewards) wrapper.referral_rewards.maybe_reload();
};

// Skip the on_page_show reload when data is fresher than this (ms). on_page_show
// fires immediately after on_page_load, which already kicked off a load.
const RR_RELOAD_AFTER_MS = 15000;

class ReferralRewards {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.summary = {};
		this.funnel = [];
		this.now = null;
		this.active_bucket = "all";
		this._loading = false;
		this._loaded_at = null; // performance.now() timestamp (monotonic, not wall clock)
		this.page.set_primary_action("Refresh", () => this.load(), "refresh");
		this.render_shell();
		this.load();
	}

	maybe_reload() {
		// Tab revisits: don't stack a second full scan (+IBEX call) on top of an
		// in-flight or seconds-old load; the Refresh button still forces one.
		if (this._loading) return;
		if (this._loaded_at !== null && performance.now() - this._loaded_at < RR_RELOAD_AFTER_MS)
			return;
		this.load();
	}

	render_shell() {
		this.page.main.html(`
            <style>${RR_CSS}</style>
            <div class="referral-rewards-page">
                <div id="rr-status" class="rr-meta"></div>
                <div id="rr-summary" class="rr-tiles"></div>
                <div id="rr-funnel" class="rr-funnel"></div>
                <div id="rr-buckets" class="rr-chips"></div>
                <div id="rr-table"></div>
            </div>
        `);
	}

	set_status(text) {
		this.page.main.find("#rr-status").html(text);
	}

	load() {
		if (this._loading) return; // dedupe double-clicks / stacked triggers
		this._loading = true;
		this.set_status("Loading referral rewards…");
		frappe.call({
			method: "admin_panel.api.referral_rewards.get_referral_rewards",
			callback: (res) => {
				this._loading = false;
				this._loaded_at = performance.now();
				const d = res.message || {};
				if (d.success === false) {
					this.set_status(
						`<span class="err">${frappe.utils.escape_html(
							d.error || "Failed to load"
						)}</span>`
					);
					return;
				}
				this.rows = d.rows || [];
				this.summary = d.summary || {};
				this.funnel = d.funnel || [];
				this.now = d.now || null;
				const rowsTotal =
					this.summary.rows_total === undefined
						? this.rows.length
						: this.summary.rows_total;
				const rowsShown =
					this.summary.rows_shown === undefined
						? this.rows.length
						: this.summary.rows_shown;
				const capNote =
					rowsShown < rowsTotal ? ` (showing latest ${rowsShown} of ${rowsTotal})` : "";
				this.set_status(
					`Live view — ${rowsTotal} invites${capNote}. Updated ${rr_ago(
						this.now,
						this.now
					)}.`
				);
				this.render_summary();
				this.render_funnel();
				this.render_buckets();
				this.render_table();
			},
			error: () => {
				this._loading = false;
				this._loaded_at = null; // failed loads shouldn't suppress a retry on revisit
				this.set_status(`<span class="err">Failed to load referral rewards.</span>`);
			},
		});
	}

	render_summary() {
		const s = this.summary;
		const tile = (label, value, sub, cls) => `
            <div class="rr-tile${cls && cls.tile ? " " + cls.tile : ""}">
                <div class="rr-tile-label">${label}</div>
                <div class="rr-tile-value${cls && cls.value ? " " + cls.value : ""}">${value}</div>
                <div class="rr-tile-sub">${sub || ""}</div>
            </div>`;

		const untilNext = s.referrals_until_next_tier;
		const nextSub =
			untilNext === null || untilNext === undefined
				? "final tier"
				: `${untilNext} more at this rate`;
		const walletVal =
			s.wallet_balance_dollars === null || s.wallet_balance_dollars === undefined
				? "—"
				: rr_money(s.wallet_balance_dollars);
		const walletSub =
			s.wallet_runway_referrals === null || s.wallet_runway_referrals === undefined
				? "funding wallet"
				: `~${s.wallet_runway_referrals} more referrals`;

		this.page.main
			.find("#rr-summary")
			.html(
				tile(
					"Total Disbursed",
					rr_money(s.total_disbursed_dollars),
					`${s.rewarded || 0} referrals rewarded`
				) +
					tile(
						"Referrals Counted",
						`${s.counter_seq || 0}`,
						"tier-consuming attempts (incl. failed)"
					) +
					tile("Current Tier", rr_money(s.current_tier_dollars), nextSub) +
					tile("Rewards Wallet", walletVal, walletSub) +
					tile(
						"Needs Reconciliation",
						`${s.needs_reconciliation || 0}`,
						`${s.partial || 0} partial / ${s.failed || 0} failed / ${
							s.pending || 0
						} pending / ${s.unknown || 0} unknown`,
						(s.needs_reconciliation || 0) > 0
							? { tile: "alert-tile", value: "bad" }
							: null
					) +
					(s.disbursed_by_tier || [])
						.map((t) =>
							tile(
								`Tier ${rr_money(t.amount_dollars)}`,
								rr_money(t.dollars),
								`${t.count_parties} payouts`
							)
						)
						.join("")
			);
	}

	render_funnel() {
		this.page.main.find("#rr-funnel").html(
			(this.funnel || [])
				.map(
					(f) => `
            <div class="rr-funnel-step">
                <div class="l">${frappe.utils.escape_html(f.stage)}</div>
                <div class="n">${f.count || 0}</div>
                <div class="c">${
					f.conversion === null || f.conversion === undefined
						? "&nbsp;"
						: f.conversion + "% of prev"
				}</div>
            </div>`
				)
				.join("")
		);
	}

	render_buckets() {
		// All chip counts come from the SUMMARY (full dataset) so every badge
		// shares one basis; the row list is capped for paid/unrewarded but always
		// contains every actionable row, so actionable filters show all of them.
		const s = this.summary;
		const counts = {
			all: s.rows_total === undefined ? this.rows.length : s.rows_total,
			paid: s.paid || 0,
			pending: s.pending || 0,
			partial: s.partial || 0,
			failed: s.failed || 0,
			processing: s.processing || 0,
			unrewarded:
				s.unrewarded === undefined
					? this.rows.filter((r) => r.reward_status === "unrewarded").length
					: s.unrewarded,
			sent:
				s.invites_sent_open === undefined
					? this.rows.filter((r) => r.reward_status === "sent").length
					: s.invites_sent_open,
			expired:
				s.invites_expired === undefined
					? this.rows.filter((r) => r.reward_status === "expired").length
					: s.invites_expired,
		};
		const html = RR_BUCKETS.map((b) => {
			const active = b.key === this.active_bucket ? " active" : "";
			return `<button class="rr-bucket${active}" data-bucket="${b.key}">${
				b.label
			} <span class="badge">${counts[b.key] || 0}</span></button>`;
		}).join("");
		const el = this.page.main.find("#rr-buckets");
		el.html(html);
		el.find(".rr-bucket").on("click", (e) => {
			this.active_bucket = e.currentTarget.dataset.bucket;
			this.render_buckets();
			this.render_table();
		});
	}

	filtered_rows() {
		if (this.active_bucket === "all") return this.rows;
		return this.rows.filter((r) => r.reward_status === this.active_bucket);
	}

	render_table() {
		const rows = this.filtered_rows();
		const esc = (v) =>
			frappe.utils.escape_html(String(v === null || v === undefined || v === "" ? "—" : v));
		const paidMark = (b) =>
			b ? '<span class="rr-yes">✓</span>' : '<span class="rr-no">✗</span>';
		const body = rows
			.map((r) => {
				// Unknown (drifted) statuses tone as warnings — never render silent.
				const tone = RR_STATUS_TONE[r.reward_status] ?? "warn";
				const err = r.reward_error
					? `<div class="rr-err">${esc(r.reward_error)}</div>`
					: "";
				return `
            <tr>
                <td>${esc(r.invitee)}</td>
                <td>${esc(r.inviter)}</td>
                <td style="text-align:right">${
					r.reward_amount_dollars === null || r.reward_amount_dollars === undefined
						? "—"
						: rr_money(r.reward_amount_dollars)
				}</td>
                <td>${
					r.reward_seq === null || r.reward_seq === undefined
						? "—"
						: "#" + esc(r.reward_seq)
				}</td>
                <td><span class="rr-chip-st ${tone}">${esc(r.reward_status)}</span>${err}</td>
                <td style="text-align:center">${paidMark(r.inviter_paid)}</td>
                <td style="text-align:center">${paidMark(r.invitee_paid)}</td>
                <td>${esc(rr_ago(r.rewarded_at || r.redeemed_at || r.created_at, this.now))}</td>
            </tr>`;
			})
			.join("");
		this.page.main.find("#rr-table").html(`
            <div class="rr-card">
                <div class="rr-count">Showing ${rows.length} invite${
			rows.length === 1 ? "" : "s"
		}</div>
                <div style="overflow-x:auto">
                    <table class="rr-table">
                        <thead><tr>
                            <th>Invitee</th><th>Inviter</th><th style="text-align:right">Amount</th>
                            <th>Seq</th><th>Reward</th><th style="text-align:center">Inviter&nbsp;paid</th>
                            <th style="text-align:center">Invitee&nbsp;paid</th><th>When</th>
                        </tr></thead>
                        <tbody>${
							body ||
							'<tr><td colspan="8" style="text-align:center;color:var(--rr-ink3)">No referrals</td></tr>'
						}</tbody>
                    </table>
                </div>
            </div>`);
	}
}

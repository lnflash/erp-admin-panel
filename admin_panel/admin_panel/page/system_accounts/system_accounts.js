// System Accounts — treasury view + gated fund movement.
// Viewing matches require_financial (System Manager + Accounts Manager);
// the Move Funds control is System Manager only (mirrors the backend gate).
const SA_VIEW_ROLES = ["System Manager", "Accounts Manager"];

const SA_TX_TYPES = {
	1: { label: "Credit", dir: "in" },
	2: { label: "Send", dir: "out" },
	3: { label: "Credit", dir: "in" },
	4: { label: "Withdrawal", dir: "out" },
};

const SA_ROLE_LABELS = {
	bankowner: "BankOwner",
	funder: "Funder",
	dealer: "Dealer",
	watchlist: "Watchlist",
};

function saEsc(v) {
	return frappe.utils.escape_html(String(v == null ? "" : v));
}

function saMoney(v) {
	return (
		"$" +
		Number(v || 0).toLocaleString(undefined, {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		})
	);
}

function saBalance(w) {
	if (w.currency === "BTC") {
		return Number(w.balance || 0).toLocaleString() + " sats";
	}
	return saMoney(w.balance);
}

const SA_CSS = `
    .system-accounts {
        --sa-surface: var(--card-bg, #ffffff); --sa-ink: var(--text-color, #1a2420);
        --sa-ink2: var(--text-muted, #5c6b65); --sa-ink3: var(--text-light, #8fa098);
        --sa-line: var(--border-color, #e2e8e5); --sa-line-soft: var(--subtle-fg, #ecf1ee);
        --sa-accent: #007856; --sa-accent-ink: #007856; --sa-accent-soft: #e6f3ee;
        --sa-good: #0ca30c; --sa-warn: #b87d00; --sa-warn-bg: #fff3d6;
        --sa-serious: #c05a32; --sa-serious-bg: #fdeae2;
        --sa-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
        max-width: 1180px; margin: 0 auto; padding: 8px 12px 40px;
    }
    [data-theme="dark"] .system-accounts, .dark .system-accounts {
        --sa-accent: #1e9e75; --sa-accent-ink: #4cc29e; --sa-accent-soft: #12352a;
        --sa-good: #35c135; --sa-warn: #fab219; --sa-warn-bg: #33290d;
        --sa-serious: #ec835a; --sa-serious-bg: #38211a;
        --sa-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25);
    }

    .system-accounts .sa-toolbar { display: flex; align-items: center; gap: 10px;
        margin-bottom: 14px; flex-wrap: wrap; }
    .system-accounts .sa-meta { color: var(--sa-ink3); font-size: 12px; }
    .system-accounts .sa-meta.err { color: var(--sa-serious); font-weight: 600; }
    .system-accounts .sa-btn { display: inline-flex; align-items: center; gap: 6px;
        border: 1px solid var(--sa-line); background: var(--sa-surface); color: var(--sa-ink);
        border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer; transition: all 0.13s; }
    .system-accounts .sa-btn:hover { border-color: var(--sa-accent); }
    .system-accounts .sa-btn:focus-visible { outline: 2px solid var(--sa-accent); outline-offset: 1px; }
    .system-accounts .sa-btn.primary { background: var(--sa-accent); border-color: var(--sa-accent);
        color: #fff; }
    .system-accounts .sa-btn.primary:hover { filter: brightness(1.07); }
    .system-accounts .sa-btn:disabled { opacity: 0.55; cursor: not-allowed; }
    .system-accounts .sa-spacer { margin-left: auto; }

    .system-accounts .sa-tiles { display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;
        margin-bottom: 14px; }
    .system-accounts .sa-tile { background: var(--sa-surface); border: 1px solid var(--sa-line);
        border-radius: 14px; box-shadow: var(--sa-shadow); padding: 12px 16px; }
    .system-accounts .sa-tile-label { font-size: 11px; letter-spacing: 0.06em;
        text-transform: uppercase; color: var(--sa-ink2); font-weight: 650; }
    .system-accounts .sa-tile-value { font-size: 22px; font-weight: 650; color: var(--sa-ink);
        font-variant-numeric: tabular-nums; margin-top: 2px; }
    .system-accounts .sa-tile-value.warn { color: var(--sa-warn); }
    .system-accounts .sa-tile-value.bad { color: var(--sa-serious); }
    .system-accounts .sa-tile-sub { font-size: 11.5px; color: var(--sa-ink3); margin-top: 2px; }

    .system-accounts .sa-card { background: var(--sa-surface); border: 1px solid var(--sa-line);
        border-radius: 14px; box-shadow: var(--sa-shadow); overflow: hidden; margin-bottom: 14px; }
    .system-accounts .sa-card-head { display: flex; align-items: center; gap: 10px;
        padding: 13px 18px; border-bottom: 1px solid var(--sa-line); flex-wrap: wrap; }
    .system-accounts .sa-card-title { font-size: 14px; font-weight: 650; color: var(--sa-ink); }
    .system-accounts .sa-card-sub { color: var(--sa-ink3); font-size: 12px; }

    .system-accounts .sa-chip { display: inline-flex; align-items: center; border-radius: 999px;
        padding: 3px 11px; font-size: 11.5px; font-weight: 650; letter-spacing: 0.02em;
        background: var(--sa-line-soft); color: var(--sa-ink2); }
    .system-accounts .sa-chip.role-bankowner { background: var(--sa-accent); color: #fff; }
    .system-accounts .sa-chip.role-funder { background: var(--sa-accent-soft); color: var(--sa-accent-ink); }
    .system-accounts .sa-chip.role-dealer { background: var(--sa-accent-soft); color: var(--sa-accent-ink);
        opacity: 0.85; }
    .system-accounts .sa-chip.st-ok { background: var(--sa-accent-soft); color: var(--sa-accent-ink); }
    .system-accounts .sa-chip.st-bad { background: var(--sa-serious-bg); color: var(--sa-serious); }
    .system-accounts .sa-chip.cur { background: var(--sa-line-soft); color: var(--sa-ink2); }

    .system-accounts .sa-wallet-row { display: flex; align-items: center; gap: 12px;
        padding: 11px 18px; border-bottom: 1px solid var(--sa-line-soft); flex-wrap: wrap; }
    .system-accounts .sa-wallet-row:last-child { border-bottom: none; }
    .system-accounts .sa-wallet-balance { font-size: 16px; font-weight: 650; color: var(--sa-ink);
        font-variant-numeric: tabular-nums; min-width: 110px; }
    .system-accounts .sa-wallet-id { font-family: var(--font-mono, monospace); font-size: 11.5px;
        color: var(--sa-ink3); overflow: hidden; text-overflow: ellipsis; max-width: 320px;
        white-space: nowrap; }
    .system-accounts .sa-activity { display: none; padding: 4px 18px 14px; }
    .system-accounts .sa-activity table { width: 100%; border-collapse: collapse; font-size: 12.5px;
        background: var(--sa-surface); border: 1px solid var(--sa-line); border-radius: 12px;
        overflow: hidden; }
    .system-accounts .sa-activity th { text-align: left; font-size: 11px; letter-spacing: 0.05em;
        text-transform: uppercase; color: var(--sa-ink2); font-weight: 650; padding: 8px 12px;
        border-bottom: 1px solid var(--sa-line); background: var(--sa-line-soft); }
    .system-accounts .sa-activity td { padding: 7px 12px; border-bottom: 1px solid var(--sa-line-soft);
        color: var(--sa-ink); font-variant-numeric: tabular-nums; }
    .system-accounts .sa-activity tr:last-child td { border-bottom: none; }
    .system-accounts .sa-amt.in { color: var(--sa-good); font-weight: 650; }
    .system-accounts .sa-amt.out { color: var(--sa-ink); font-weight: 650; }
    .system-accounts .sa-fee { color: var(--sa-ink3); font-size: 11px; margin-left: 6px; }
    .system-accounts .sa-empty { color: var(--sa-ink3); font-size: 12.5px; padding: 12px 0; }

    @media (prefers-reduced-motion: no-preference) {
        .system-accounts .sa-card, .system-accounts .sa-tile { animation: sa-rise 0.3s ease; }
        @keyframes sa-rise { from { opacity: 0; transform: translateY(5px); } }
    }
`;

frappe.pages["system-accounts"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "System Accounts",
		single_column: true,
	});

	const allowed =
		frappe.session.user === "Administrator" ||
		SA_VIEW_ROLES.some((r) => frappe.user_roles.includes(r));
	if (!allowed) {
		page.main.html(`
            <div class="text-center mt-5">
                <div class="alert alert-warning">
                    <h4>Access Denied</h4>
                    <p>This page requires the "Accounts Manager" or "System Manager" role.</p>
                </div>
            </div>
        `);
		return;
	}

	wrapper.system_accounts = new SystemAccounts(page);
};

class SystemAccounts {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.can_transfer =
			frappe.session.user === "Administrator" ||
			frappe.user_roles.includes("System Manager");
		this.render_shell();
		this.load();
	}

	render_shell() {
		this.page.main.html(`
            <style>${SA_CSS}</style>
            <div class="system-accounts">
                <div class="sa-toolbar">
                    <button class="sa-btn" data-act="refresh">Refresh</button>
                    <span class="sa-meta" id="sa-meta">Loading live balances…</span>
                    <span class="sa-spacer"></span>
                    ${
						this.can_transfer
							? '<button class="sa-btn" data-act="watch">Watch Account</button>' +
							  '<button class="sa-btn primary" data-act="transfer">Move Funds</button>'
							: ""
					}
                </div>
                <div class="sa-tiles" id="sa-tiles" style="display:none;"></div>
                <div id="sa-accounts"></div>
            </div>
        `);
		this.page.main.find('[data-act="refresh"]').on("click", () => this.load());
		this.page.main
			.find('[data-act="transfer"]')
			.on("click", () => this.open_transfer_dialog());
		this.page.main.find('[data-act="watch"]').on("click", () => this.open_watch_dialog());
	}

	load() {
		const meta = this.page.main.find("#sa-meta");
		meta.removeClass("err").text("Loading live balances…");
		frappe.call({
			method: "admin_panel.api.system_accounts.get_system_accounts",
			callback: (res) => {
				this.data = res.message;
				meta.text(`Live from IBEX · ${this.data.now}`);
				this.render();
			},
			error: () => meta.addClass("err").text("Could not load system accounts."),
		});
	}

	render() {
		const d = this.data;
		if (!d) return;
		const freeTone = d.totals.free_float < 0 ? "bad" : "";
		const tiles = [
			{ label: "BankOwner Float", value: saMoney(d.totals.bankowner_float) },
			{
				label: "Outstanding Payables",
				value: saMoney(d.payables.usd),
				sub: `${d.payables.count} unpaid cashout${d.payables.count === 1 ? "" : "s"}`,
			},
			{
				label: "Free Float",
				value: saMoney(d.totals.free_float),
				tone: freeTone,
				sub: "float − payables",
			},
			{ label: "Funder Float", value: saMoney(d.totals.funder_float) },
		];
		this.page.main
			.find("#sa-tiles")
			.html(
				tiles
					.map(
						(t) => `
                <div class="sa-tile">
                    <div class="sa-tile-label">${saEsc(t.label)}</div>
                    <div class="sa-tile-value ${t.tone || ""}">${saEsc(t.value)}</div>
                    ${t.sub ? `<div class="sa-tile-sub">${saEsc(t.sub)}</div>` : ""}
                </div>`
					)
					.join("")
			)
			.show();

		const cards = d.accounts
			.map((acc) => {
				const statusTone = acc.status === "active" ? "st-ok" : "st-bad";
				const wallets = acc.wallets.length
					? acc.wallets
							.map(
								(w) => `
                    <div class="sa-wallet-row" data-wallet="${saEsc(w.wallet_id)}">
                        <span class="sa-chip cur">${saEsc(w.currency)}</span>
                        <span class="sa-wallet-balance">${
							w.not_found ? "—" : saEsc(saBalance(w))
						}</span>
                        <span class="sa-wallet-id" title="${saEsc(w.wallet_id)}">${saEsc(
									w.wallet_id
								)}</span>
                        <span class="sa-spacer"></span>
                        ${
							(w.currency === "USD" || w.currency === "USDT") && !w.not_found
								? `<button class="sa-btn sa-fund-btn" data-wallet="${saEsc(
										w.wallet_id
								  )}">Fund</button>`
								: ""
						}
                        <button class="sa-btn sa-activity-btn" data-wallet="${saEsc(
							w.wallet_id
						)}">Activity</button>
                    </div>
                    <div class="sa-activity" data-activity="${saEsc(w.wallet_id)}"></div>`
							)
							.join("")
					: '<div class="sa-wallet-row sa-empty">No wallets found in mongo for this account.</div>';
				const isWatch = acc.role === "watchlist";
				const xferChip = isWatch
					? acc.allow_transfers
						? '<span class="sa-chip st-ok">transfers on</span>'
						: '<span class="sa-chip">view-only</span>'
					: "";
				// watch_ref is the exact ref stored on the doctype row, so the
				// toggle/remove buttons hit the right record whether the entry
				// was added by username or by mongo id.
				const watchRef = acc.watch_ref || acc.username || acc.account_id;
				const watchControls =
					isWatch && acc.watch_managed && this.can_transfer
						? `<span class="sa-spacer"></span>
                        <button class="sa-btn sa-toggle-btn" data-account="${saEsc(
							watchRef
						)}" data-allow="${acc.allow_transfers ? 1 : 0}">${
								acc.allow_transfers ? "Disable transfers" : "Enable transfers"
						  }</button>
                        <button class="sa-btn sa-remove-btn" data-account="${saEsc(
							watchRef
						)}" title="Remove from watchlist">✕</button>`
						: "";
				return `
                <div class="sa-card">
                    <div class="sa-card-head">
                        <span class="sa-chip role-${saEsc(acc.role)}">${saEsc(
					SA_ROLE_LABELS[acc.role] || acc.role
				)}</span>
                        <span class="sa-card-title">${saEsc(acc.username || acc.account_id)}</span>
                        ${
							acc.status
								? `<span class="sa-chip ${statusTone}">${saEsc(acc.status)}</span>`
								: ""
						}
                        ${xferChip}
                        <span class="sa-card-sub">${saEsc(acc.account_id)}</span>
                        ${watchControls}
                    </div>
                    ${wallets}
                </div>`;
			})
			.join("");
		this.page.main
			.find("#sa-accounts")
			.html(
				cards ||
					'<div class="sa-card"><div class="sa-wallet-row sa-empty">No system accounts found — check mongo roles and the system_watchlist site_config.</div></div>'
			);

		this.page.main.find(".sa-activity-btn").on("click", (e) => {
			this.toggle_activity($(e.currentTarget).data("wallet"));
		});
		this.page.main.find(".sa-fund-btn").on("click", (e) => {
			this.open_fund_dialog($(e.currentTarget).data("wallet"));
		});
		this.page.main.find(".sa-toggle-btn").on("click", (e) => {
			const btn = $(e.currentTarget);
			this.toggle_transfers(btn.data("account"), !Number(btn.data("allow")));
		});
		this.page.main.find(".sa-remove-btn").on("click", (e) => {
			this.remove_watch($(e.currentTarget).data("account"));
		});
	}

	open_watch_dialog() {
		const d = new frappe.ui.Dialog({
			title: "Watch an Ops Account",
			fields: [
				{
					fieldname: "account_ref",
					fieldtype: "Data",
					label: "Username or mongo account id",
					reqd: 1,
				},
				{ fieldname: "label", fieldtype: "Data", label: "Label (optional)" },
				{
					fieldname: "help",
					fieldtype: "HTML",
					options: `<div style="font-size:12px;color:var(--text-muted);">
                        Added accounts are <strong>view-only</strong> until you enable transfers on the card.
                    </div>`,
				},
			],
			primary_action_label: "Add to Watchlist",
			primary_action: (values) => {
				frappe.call({
					method: "admin_panel.api.system_accounts.add_watchlist_entry",
					args: { account_ref: values.account_ref, label: values.label },
					freeze: true,
					callback: () => {
						d.hide();
						frappe.show_alert(
							{ message: "Added to watchlist.", indicator: "green" },
							5
						);
						this.load();
					},
				});
			},
		});
		d.show();
	}

	remove_watch(accountRef) {
		frappe.confirm(
			`Remove <strong>${saEsc(accountRef)}</strong> from the watchlist? ` +
				"This does not touch the account or its funds.",
			() => {
				frappe.call({
					method: "admin_panel.api.system_accounts.remove_watchlist_entry",
					args: { account_ref: accountRef },
					callback: () => {
						frappe.show_alert({ message: "Removed.", indicator: "green" }, 4);
						this.load();
					},
				});
			}
		);
	}

	toggle_transfers(accountRef, allow) {
		const act = () =>
			frappe.call({
				method: "admin_panel.api.system_accounts.set_watchlist_transfers",
				args: { account_ref: accountRef, allow: allow ? 1 : 0 },
				callback: () => {
					frappe.show_alert(
						{
							message: allow ? "Transfers enabled." : "Transfers disabled.",
							indicator: allow ? "orange" : "green",
						},
						4
					);
					this.load();
				},
			});
		if (allow) {
			frappe.confirm(
				`Enable transfers for <strong>${saEsc(accountRef)}</strong>?<br><br>` +
					"This makes it a valid endpoint for moving funds in and out (still capped and logged).",
				act
			);
		} else {
			act();
		}
	}

	toggle_activity(walletId) {
		const box = this.page.main.find(`[data-activity="${walletId}"]`);
		if (box.is(":visible")) {
			box.hide();
			return;
		}
		box.html('<div class="sa-empty">Loading activity…</div>').show();
		frappe.call({
			method: "admin_panel.api.system_accounts.get_system_account_activity",
			args: { wallet_id: walletId, page: 0, limit: 20 },
			callback: (res) => box.html(this.activity_table(res.message)),
			error: () => box.html('<div class="sa-empty">Could not load activity.</div>'),
		});
	}

	activity_table(data) {
		const txs = (data && data.transactions) || [];
		if (!txs.length) return '<div class="sa-empty">No transactions.</div>';
		const rows = txs
			.map((t) => {
				const ty = SA_TX_TYPES[t.type_id] || null;
				const amt =
					t.amount != null && Number.isFinite(Number(t.amount))
						? Number(t.amount).toLocaleString(undefined, { maximumFractionDigits: 8 })
						: "—";
				const sign = ty ? (ty.dir === "in" ? "+" : "−") : "";
				const fee =
					t.network_fee && Number(t.network_fee) > 0
						? `<span class="sa-fee">fee ${Number(t.network_fee).toLocaleString(
								undefined,
								{
									maximumFractionDigits: 8,
								}
						  )}</span>`
						: "";
				return `<tr>
                    <td>${saEsc((t.created_at || "").replace("T", " ").slice(0, 19))}</td>
                    <td style="text-align:right"><span class="sa-amt ${
						ty ? ty.dir : "out"
					}">${sign}${amt}</span>${fee}</td>
                    <td>${saEsc(t.currency || "")}</td>
                    <td>${ty ? saEsc(ty.label) : saEsc(t.type_id)}</td>
                </tr>`;
			})
			.join("");
		return `<table>
            <thead><tr><th>When</th><th style="text-align:right">Amount</th><th>Currency</th><th>Type</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
	}

	transferable_wallets() {
		const out = [];
		(this.data?.accounts || []).forEach((acc) => {
			if (!acc.transferable) return;
			acc.wallets.forEach((w) => {
				if (w.currency === "BTC") return; // USD/USDT rails only
				out.push({
					value: w.wallet_id,
					label: `${SA_ROLE_LABELS[acc.role] || acc.role} · ${w.currency} · ${saBalance(
						w
					)} · ${w.wallet_id.slice(0, 8)}…`,
				});
			});
		});
		return out;
	}

	open_transfer_dialog() {
		if (!this.data) return;
		const options = this.transferable_wallets();
		if (options.length < 2) {
			frappe.msgprint("Need at least two role-account wallets to move funds.");
			return;
		}
		const cap = this.data.transfer_cap_usd;
		const d = new frappe.ui.Dialog({
			title: "Move Funds Between System Wallets",
			fields: [
				{
					fieldname: "from_wallet",
					fieldtype: "Select",
					label: "From",
					options: options.map((o) => o.value).join("\n"),
					reqd: 1,
				},
				{
					fieldname: "to_wallet",
					fieldtype: "Select",
					label: "To",
					options: options.map((o) => o.value).join("\n"),
					reqd: 1,
				},
				{
					fieldname: "amount_usd",
					fieldtype: "Float",
					label: `Amount (USD) — per-transfer cap ${saMoney(cap)}`,
					reqd: 1,
				},
				{ fieldname: "memo", fieldtype: "Data", label: "Memo" },
				{
					fieldname: "help",
					fieldtype: "HTML",
					options: `<div style="font-size:12px;color:var(--text-muted);">
                        ${options
							.map(
								(o) =>
									`<div><code>${saEsc(o.value)}</code> — ${saEsc(o.label)}</div>`
							)
							.join("")}
                    </div>`,
				},
			],
			primary_action_label: "Review Transfer",
			primary_action: (values) => {
				if (values.from_wallet === values.to_wallet) {
					frappe.msgprint("Sender and receiver are the same wallet.");
					return;
				}
				d.hide();
				const fromLabel = options.find((o) => o.value === values.from_wallet)?.label;
				const toLabel = options.find((o) => o.value === values.to_wallet)?.label;
				frappe.confirm(
					`Move <strong>${saMoney(values.amount_usd)}</strong><br>
                    from <strong>${saEsc(fromLabel)}</strong><br>
                    to <strong>${saEsc(toLabel)}</strong>?<br><br>
                    This pays a real invoice between IBEX accounts and is logged.`,
					() => this.execute_transfer(values)
				);
			},
		});
		d.show();
	}

	execute_transfer(values) {
		frappe.call({
			method: "admin_panel.api.system_accounts.transfer_between_system_wallets",
			args: {
				from_wallet_id: values.from_wallet,
				to_wallet_id: values.to_wallet,
				amount_usd: values.amount_usd,
				memo: values.memo,
			},
			freeze: true,
			freeze_message: "Moving funds…",
			callback: (res) => {
				const log = res.message?.log;
				frappe.show_alert(
					{ message: `Transfer complete${log ? ` (${log})` : ""}.`, indicator: "green" },
					6
				);
				this.load();
			},
		});
	}

	wallet_meta(walletId) {
		for (const acc of this.data?.accounts || []) {
			for (const w of acc.wallets) {
				if (w.wallet_id === walletId) return { w, role: acc.role, username: acc.username };
			}
		}
		return null;
	}

	// Fund a system wallet: generate a Lightning receive invoice the operator
	// pays from any wallet. No treasury funds move here — money comes IN.
	open_fund_dialog(walletId) {
		const meta = this.wallet_meta(walletId);
		if (!meta) return;
		const { w, role, username } = meta;
		const roleLabel = SA_ROLE_LABELS[role] || role;
		const d = new frappe.ui.Dialog({
			title: `Fund ${roleLabel} · ${w.currency}`,
			fields: [
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: `Amount (${w.currency})`,
					reqd: 1,
					description: `Into ${saEsc(username || w.wallet_id)} · ${saEsc(
						w.wallet_id.slice(0, 8)
					)}…`,
				},
				{ fieldname: "out", fieldtype: "HTML", options: "" },
			],
			primary_action_label: "Generate invoice",
			primary_action: () => {
				const amount = Number(d.get_value("amount"));
				if (!amount || !isFinite(amount) || amount <= 0) {
					frappe.msgprint("Enter a positive amount.");
					return;
				}
				this.generate_funding_invoice(d, w, amount);
			},
		});
		// Baseline is the page-load balance — captured BEFORE any payment, so a
		// full-amount rise is unambiguous receipt. Timers cleared on close.
		d._baseline = Number(w.balance || 0);
		d._timers = [];
		d._regens = 0;
		d.onhide = () => (d._timers || []).forEach((t) => clearInterval(t));
		d.show();
	}

	generate_funding_invoice(d, w, amount) {
		const out = d.fields_dict.out.$wrapper;
		(d._timers || []).forEach((t) => clearInterval(t));
		d._timers = [];
		out.html('<div style="padding:8px 0;color:var(--text-muted);">Generating invoice…</div>');
		frappe.call({
			method: "admin_panel.api.system_accounts.create_funding_invoice",
			args: { wallet_id: w.wallet_id, amount_usd: amount, memo: "Treasury funding" },
			error: () =>
				out.html(
					'<div style="padding:8px 0;color:var(--red,#c0392b);">Could not generate an invoice — try again.</div>'
				),
			callback: (res) => {
				const inv = res.message;
				if (!inv || !inv.bolt11) {
					out.html(
						'<div style="padding:8px 0;color:var(--red,#c0392b);">No invoice returned.</div>'
					);
					return;
				}
				this.render_funding_invoice(d, w, amount, inv);
			},
		});
	}

	render_funding_invoice(d, w, amount, inv) {
		const out = d.fields_dict.out.$wrapper;
		const bolt11 = inv.bolt11;
		const fmt = (n) =>
			Number(n).toLocaleString(undefined, {
				minimumFractionDigits: 2,
				maximumFractionDigits: 2,
			});
		out.html(`
			<div style="border:1px solid var(--border-color);border-radius:10px;padding:12px;margin-top:4px;">
				<div style="font-size:13px;color:var(--text-muted);margin-bottom:6px;">
					Pay <strong>$${fmt(inv.amount_usd || amount)} ${saEsc(
			inv.currency || w.currency
		)}</strong> from any Lightning wallet. Scanning from a phone pays atomically and beats the 60s expiry.
				</div>
				<textarea readonly style="width:100%;height:64px;font-family:var(--font-mono,monospace);font-size:11px;resize:none;padding:6px;border:1px solid var(--border-color);border-radius:8px;background:var(--control-bg,#f7f7f7);">${saEsc(
					bolt11
				)}</textarea>
				<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">
					<button class="btn btn-xs btn-default sa-copy">Copy invoice</button>
					<a class="btn btn-xs btn-default" href="lightning:${saEsc(bolt11)}">Open in wallet</a>
					<button class="btn btn-xs btn-default sa-regen">Regenerate</button>
					<span class="sa-countdown" style="font-size:12px;color:var(--text-muted);"></span>
				</div>
				<div class="sa-fund-status" style="margin-top:10px;font-size:13px;font-weight:600;color:var(--text-muted);">
					Waiting for payment…
				</div>
			</div>
		`);
		out.find(".sa-copy").on("click", () => {
			navigator.clipboard?.writeText(bolt11).then(
				() => frappe.show_alert({ message: "Invoice copied.", indicator: "green" }, 3),
				() => frappe.msgprint("Copy failed — select and copy manually.")
			);
		});
		out.find(".sa-regen").on("click", () => this.generate_funding_invoice(d, w, amount));

		// Countdown to expiry, auto-regenerating a bounded number of times so a
		// slow scan isn't stranded; after that the manual Regenerate stays.
		const expiryMs = inv.expiry_utc ? Date.parse(inv.expiry_utc) : Date.now() + 60000;
		const cd = out.find(".sa-countdown");
		const tick = setInterval(() => {
			const left = Math.round((expiryMs - Date.now()) / 1000);
			if (left > 0) {
				cd.text(`expires in ${left}s`);
			} else {
				clearInterval(tick);
				if ((d._regens || 0) < 15) {
					d._regens = (d._regens || 0) + 1;
					this.generate_funding_invoice(d, w, amount);
				} else {
					cd.text("expired — click Regenerate to keep funding");
				}
			}
		}, 1000);
		d._timers.push(tick);

		// Receipt poll: a fixed-amount LN invoice settles in full, so the wallet
		// balance rises by `amount`. Require the full rise to avoid false hits.
		const poll = setInterval(() => {
			frappe.call({
				method: "admin_panel.api.system_accounts.get_system_wallet_balance",
				args: { wallet_id: w.wallet_id },
				callback: (res) => {
					const bal = Number(res.message?.balance);
					if (!isFinite(bal)) return;
					if (bal - (d._baseline || 0) >= amount - 0.01) {
						(d._timers || []).forEach((t) => clearInterval(t));
						d._timers = [];
						out.find(".sa-fund-status")
							.css("color", "var(--green,#0ca30c)")
							.html(`✓ Received — balance is now $${fmt(bal)}`);
						frappe.show_alert({ message: "Funding received.", indicator: "green" }, 6);
						this.load();
					}
				},
			});
		}, 6000);
		d._timers.push(poll);
	}
}

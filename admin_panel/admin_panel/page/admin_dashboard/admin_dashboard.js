frappe.pages["admin-dashboard"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Dashboard",
		single_column: true,
	});

	if (!frappe.user_roles.includes("Accounts Manager")) {
		page.main.html(`
            <div class="text-center mt-5">
                <div class="alert alert-warning">
                    <h4>Access Denied</h4>
                    <p>You do not have permission to access this page. Please contact your administrator to get the "Accounts Manager" role.</p>
                </div>
            </div>
        `);
		return;
	}

	wrapper.ops_dashboard = new OpsDashboard(page);
};

frappe.pages["admin-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.ops_dashboard) {
		wrapper.ops_dashboard.refresh();
	}
};

/* ─────────────────────────────────────────────
   Ops Pulse dashboard
   Design: single validated accent (#007856 light / #1E9E75 dark), desk theme
   tokens for surfaces/ink, status colors only for queue urgency (icon+label,
   never color alone). Pulse tiles answer "how's the money?"; the queue
   answers "who needs me?"; tools + upgrade table keep their existing flows.
   ───────────────────────────────────────────── */

const FP_CSS = `
    .fp { --fp-surface: var(--card-bg, #ffffff); --fp-ink: var(--text-color, #1a2420);
          --fp-ink2: var(--text-muted, #5c6b65); --fp-ink3: var(--text-light, #8fa098);
          --fp-line: var(--border-color, #e2e8e5); --fp-line-soft: var(--subtle-fg, #ecf1ee);
          --fp-accent: #007856; --fp-accent-ink: #007856; --fp-accent-soft: #e6f3ee;
          --fp-spark: #c3cfc9; --fp-good: #0ca30c;
          --fp-warn: #b87d00; --fp-warn-bg: #fff3d6;
          --fp-serious: #c05a32; --fp-serious-bg: #fdeae2;
          --fp-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
          max-width: 1240px; margin: 0 auto; }
    [data-theme="dark"] .fp, .dark .fp {
          --fp-accent: #1e9e75; --fp-accent-ink: #4cc29e; --fp-accent-soft: #12352a;
          --fp-spark: #3a4a42; --fp-good: #35c135;
          --fp-warn: #fab219; --fp-warn-bg: #33290d;
          --fp-serious: #ec835a; --fp-serious-bg: #38211a;
          --fp-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25); }

    .fp * { box-sizing: border-box; }
    .fp .fp-meta { display: flex; align-items: center; justify-content: flex-end; gap: 14px;
          color: var(--fp-ink2); font-size: 12.5px; margin: -4px 0 14px; flex-wrap: wrap; }
    .fp .fp-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--fp-good);
          display: inline-block; margin-right: 6px; }
    .fp .fp-refresh { cursor: pointer; color: var(--fp-accent-ink); font-weight: 600; }
    .fp .fp-refresh:hover { text-decoration: underline; }

    /* pulse tiles */
    .fp .fp-pulse { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
          gap: 14px; margin-bottom: 14px; }
    .fp .fp-tile { background: var(--fp-surface); border: 1px solid var(--fp-line);
          border-radius: 14px; padding: 16px 18px 13px; box-shadow: var(--fp-shadow);
          display: flex; flex-direction: column; gap: 6px; min-height: 116px;
          text-decoration: none; color: inherit; cursor: pointer; transition: border-color 0.15s; }
    .fp .fp-tile:hover { border-color: var(--fp-accent); text-decoration: none; }
    .fp .fp-tile:focus-visible { outline: 2px solid var(--fp-accent); outline-offset: 2px; }
    .fp .fp-label { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--fp-ink2); font-weight: 600; }
    .fp .fp-value { font-size: 30px; font-weight: 650; letter-spacing: -0.015em;
          line-height: 1.05; color: var(--fp-ink); }
    .fp .fp-value .fp-unit { font-size: 14px; font-weight: 600; color: var(--fp-ink2); margin-left: 3px; }
    .fp .fp-foot { display: flex; align-items: center; justify-content: space-between;
          gap: 8px; margin-top: auto; min-height: 28px; }
    .fp .fp-delta { font-size: 12.5px; font-weight: 600; color: var(--fp-ink3); }
    .fp .fp-delta.up { color: var(--fp-good); }
    .fp .fp-delta small { color: var(--fp-ink3); font-weight: 500; margin-left: 3px; }
    .fp .fp-spark { width: 92px; height: 28px; flex: none; }
    .fp .fp-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px;
          font-weight: 600; border-radius: 999px; padding: 3px 9px; }
    .fp .fp-chip.warn { color: var(--fp-warn); background: var(--fp-warn-bg); }
    .fp .fp-chip.serious { color: var(--fp-serious); background: var(--fp-serious-bg); }
    .fp .fp-chip.ok { color: var(--fp-good); background: var(--fp-accent-soft); }

    /* trend + queue grid */
    .fp .fp-grid { display: grid; grid-template-columns: 1.9fr 1fr; gap: 14px; margin-bottom: 22px; }
    @media (max-width: 900px) { .fp .fp-grid { grid-template-columns: 1fr; } }
    .fp .fp-card { background: var(--fp-surface); border: 1px solid var(--fp-line);
          border-radius: 14px; box-shadow: var(--fp-shadow); padding: 18px 20px; }
    .fp .fp-card h2 { font-size: 13.5px; font-weight: 650; margin: 0 0 2px; color: var(--fp-ink); }
    .fp .fp-sub { color: var(--fp-ink2); font-size: 12px; margin: 0 0 12px; }
    .fp .fp-chart-box { position: relative; }
    .fp .fp-chart-box svg { display: block; width: 100%; height: 216px; }
    .fp .fp-tt { position: absolute; pointer-events: none; background: var(--fp-surface);
          border: 1px solid var(--fp-line); border-radius: 8px; box-shadow: var(--fp-shadow);
          padding: 7px 10px; font-size: 12px; display: none; z-index: 3; white-space: nowrap; }
    .fp .fp-tt b { font-size: 13px; display: block; color: var(--fp-ink); }
    .fp .fp-tt span { color: var(--fp-ink2); }
    .fp .fp-empty { color: var(--fp-ink3); font-size: 12.5px; padding: 26px 0; text-align: center; }

    /* queue */
    .fp .fp-qhead { display: flex; justify-content: space-between; align-items: baseline; margin: 14px 0 6px; }
    .fp .fp-qhead:first-of-type { margin-top: 0; }
    .fp .fp-qhead h3 { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--fp-ink2); margin: 0; font-weight: 650; }
    .fp .fp-qhead a { font-size: 12px; color: var(--fp-accent-ink); text-decoration: none; font-weight: 600; }
    .fp .fp-qhead a:hover { text-decoration: underline; }
    .fp .fp-qrow { display: flex; align-items: center; gap: 10px; padding: 9px 10px 9px 12px;
          border-radius: 10px; border-left: 3px solid var(--fp-line); cursor: pointer;
          transition: background 0.12s; }
    .fp .fp-qrow:hover { background: var(--fp-line-soft); }
    .fp .fp-qrow + .fp-qrow { margin-top: 2px; }
    .fp .fp-qrow.warn { border-left-color: var(--fp-warn); }
    .fp .fp-qrow.serious { border-left-color: var(--fp-serious); }
    .fp .fp-qmain { min-width: 0; flex: 1; }
    .fp .fp-qtitle { font-weight: 600; font-size: 13px; color: var(--fp-ink);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fp .fp-qsub { color: var(--fp-ink2); font-size: 12px; }
    .fp .fp-qamt { font-weight: 650; font-size: 13px; color: var(--fp-ink); font-variant-numeric: tabular-nums; }
    .fp .fp-qage { color: var(--fp-ink3); font-size: 11.5px; flex: none; min-width: 34px; text-align: right; }

    /* tools (class names kept for contract tests) */
    .fp .ad-section-title { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--fp-ink2); font-weight: 650; margin: 0 0 10px; }
    .fp .ad-tools { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
          gap: 12px; margin-bottom: 22px; }
    .fp .ad-tool-card { display: flex; align-items: center; gap: 12px; background: var(--fp-surface);
          border: 1px solid var(--fp-line); border-radius: 12px; padding: 12px 14px;
          box-shadow: var(--fp-shadow); cursor: pointer; transition: border-color 0.15s; }
    .fp .ad-tool-card:hover { border-color: var(--fp-accent); }
    .fp .ad-tool-icon { width: 34px; height: 34px; border-radius: 9px; background: var(--fp-accent-soft);
          color: var(--fp-accent-ink); display: grid; place-items: center; flex: none;
          font-size: 11px; font-weight: 700; letter-spacing: 0.02em; }
    .fp .ad-tool-title { font-weight: 600; font-size: 13px; color: var(--fp-ink); }
    .fp .ad-tool-desc { color: var(--fp-ink2); font-size: 11.5px; margin-top: 1px; }

    /* upgrade requests table (existing flow, restyled) */
    .fp .fp-tablecard { padding: 0; overflow: hidden; margin-bottom: 40px; }
    .fp .fp-tablehead { display: flex; justify-content: space-between; align-items: center;
          gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--fp-line); flex-wrap: wrap; }
    .fp .fp-tablehead h2 { margin: 0; }
    .fp .ad-smart-search { border: 1px solid var(--fp-line); border-radius: 8px; padding: 6px 10px;
          font-size: 13px; background: transparent; color: var(--fp-ink); min-width: 240px; }
    .fp .ad-smart-search:focus { outline: 2px solid var(--fp-accent); outline-offset: 1px; }
    .fp table.fp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .fp table.fp-table th { text-align: left; font-size: 11px; letter-spacing: 0.05em;
          text-transform: uppercase; color: var(--fp-ink2); font-weight: 650;
          padding: 10px 18px; border-bottom: 1px solid var(--fp-line); }
    .fp table.fp-table td { padding: 10px 18px; border-bottom: 1px solid var(--fp-line-soft);
          color: var(--fp-ink); font-variant-numeric: tabular-nums; }
    .fp .ad-req-row { cursor: pointer; }
    .fp .ad-req-row:hover { background: var(--fp-line-soft); }
    .fp .ad-badge { display: inline-block; border-radius: 999px; padding: 2px 9px;
          font-size: 11.5px; font-weight: 600; }
    .fp .ad-badge-pending { color: var(--fp-warn); background: var(--fp-warn-bg); }
    .fp .ad-badge-approved { color: var(--fp-good); background: var(--fp-accent-soft); }
    .fp .ad-badge-rejected { color: var(--fp-serious); background: var(--fp-serious-bg); }
    .fp .ad-badge-default { color: var(--fp-ink2); background: var(--fp-line-soft); }

    @media (prefers-reduced-motion: no-preference) {
        .fp .fp-rise { opacity: 0; transform: translateY(6px); animation: fp-rise 0.35s ease forwards; }
        @keyframes fp-rise { to { opacity: 1; transform: none; } }
    }
`;

class OpsDashboard {
	constructor(page) {
		this.page = page;
		this.stats = null;
		this.pulse = null;
		this.render_shell();
		this.load();
	}

	/* ── data ─────────────────────────────────── */
	load() {
		frappe.call({
			method: "admin_panel.api.pulse.get_dashboard_pulse",
			callback: (r) => {
				this.pulse = r.message || null;
				this.render_pulse();
			},
			error: () => this.render_pulse_error(),
		});
		frappe.call({
			method: "admin_panel.api.admin_api.get_dashboard_stats",
			callback: (r) => {
				this.stats = r.message || null;
				this.render_requests();
			},
		});
	}

	refresh() {
		this.load();
	}

	/* ── shell ────────────────────────────────── */
	render_shell() {
		this.page.main.html(`
            <style>${FP_CSS}</style>
            <div class="fp">
                <div class="fp-meta">
                    <span id="fp-census-age"><span class="fp-dot"></span>Loading pulse…</span>
                    <span class="fp-refresh" id="fp-refresh" role="button" tabindex="0">Refresh</span>
                </div>
                <div class="fp-pulse" id="fp-pulse"></div>
                <div class="fp-grid">
                    <div class="fp-card fp-rise">
                        <h2>USDT float</h2>
                        <p class="fp-sub" id="fp-chart-sub">Live IBEX totals from each census run · hover for detail</p>
                        <div class="fp-chart-box">
                            <svg id="fp-trend" role="img" aria-label="USDT float trend across recent census runs"></svg>
                            <div class="fp-tt" id="fp-tt"></div>
                        </div>
                    </div>
                    <div class="fp-card fp-rise" id="fp-queue"></div>
                </div>
                <p class="ad-section-title">Tools</p>
                <div class="ad-tools">
                    <div class="ad-tool-card" data-route="/app/account-hub">
                        <div class="ad-tool-icon">AH</div>
                        <div><div class="ad-tool-title">Account Hub</div>
                        <div class="ad-tool-desc">Search, inspect and manage any account</div></div>
                    </div>
                    <div class="ad-tool-card" data-route="/app/wallet-census">
                        <div class="ad-tool-icon">WC</div>
                        <div><div class="ad-tool-title">Wallet Census</div>
                        <div class="ad-tool-desc">Live IBEX balances, buckets and CSV export</div></div>
                    </div>
                    <div class="ad-tool-card" data-route="/app/transfer-requests">
                        <div class="ad-tool-icon">TR</div>
                        <div><div class="ad-tool-title">Transfer Requests</div>
                        <div class="ad-tool-desc">Cashout and Bridge settlement queue</div></div>
                    </div>
                    <div class="ad-tool-card" data-route="/app/bridge-kyc">
                        <div class="ad-tool-icon">BK</div>
                        <div><div class="ad-tool-title">Bridge KYC</div>
                        <div class="ad-tool-desc">Live Bridge KYC status for every customer</div></div>
                    </div>
                    <div class="ad-tool-card" data-route="/app/account-management">
                        <div class="ad-tool-icon">AM</div>
                        <div><div class="ad-tool-title">Account Management</div>
                        <div class="ad-tool-desc">Levels, locks and merchant validation</div></div>
                    </div>
                    <div class="ad-tool-card" data-route="/app/alert-users">
                        <div class="ad-tool-icon">AL</div>
                        <div><div class="ad-tool-title">Alert Users</div>
                        <div class="ad-tool-desc">Broadcast email or in-app announcements</div></div>
                    </div>
                </div>
                <div class="fp-card fp-tablecard fp-rise">
                    <div class="fp-tablehead">
                        <h2>Upgrade requests</h2>
                        <input type="text" class="ad-smart-search" placeholder="Filter by username, phone, email…">
                    </div>
                    <div id="fp-requests"><div class="fp-empty">Loading…</div></div>
                </div>
            </div>
        `);

		const $m = this.page.main;
		$m.find(".ad-tool-card").on("click", function () {
			frappe.set_route($(this).data("route").replace("/app/", ""));
		});
		$m.find("#fp-refresh").on("click", () => this.refresh());
		$m.find("#fp-refresh").on("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") this.refresh();
		});
		$m.on("input", ".ad-smart-search", () => this.render_requests());
		$m.on("click", ".ad-req-row", function () {
			const query = $(this).data("query");
			if (query) {
				frappe.route_options = { account_hub_query: query };
				frappe.set_route("account-hub");
			}
		});
	}

	/* ── helpers ──────────────────────────────── */
	tok(name) {
		return getComputedStyle(this.page.main.find(".fp")[0]).getPropertyValue(name).trim();
	}

	esc(v) {
		return frappe.utils.escape_html(String(v == null ? "" : v));
	}

	money(v) {
		if (v == null) return "—";
		return (
			"$" +
			Number(v).toLocaleString(undefined, {
				minimumFractionDigits: 2,
				maximumFractionDigits: 2,
			})
		);
	}

	age_hours(iso, now) {
		const ms = new Date(now.replace(" ", "T")) - new Date(iso.replace(" ", "T"));
		return Math.max(0, ms / 36e5);
	}

	age_label(h) {
		if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
		if (h < 48) return `${Math.round(h)}h`;
		return `${Math.round(h / 24)}d`;
	}

	/* ── pulse tiles ──────────────────────────── */
	render_pulse_error() {
		this.page.main
			.find("#fp-pulse")
			.html(
				'<div class="fp-card fp-empty">Could not load the ops pulse — check the server logs and refresh.</div>'
			);
		this.page.main.find("#fp-census-age").html("Pulse unavailable");
	}

	render_pulse() {
		const p = this.pulse || {};
		const c = p.census;
		const now = p.now || "";
		const $m = this.page.main;

		if (c) {
			const h = this.age_hours(c.completed_at, now);
			$m.find("#fp-census-age").html(
				`<span class="fp-dot"></span>Census ${this.age_label(h)} ago · ${this.esc(
					c.accounts
				)} accounts`
			);
		} else {
			$m.find("#fp-census-age").html("No census yet");
		}

		const delta = (val, fmt) => {
			if (val == null) return `<span class="fp-delta">—</span>`;
			const up = val > 0;
			const sign = up ? "▲" : val < 0 ? "▼" : "•";
			const cls = up ? "fp-delta up" : "fp-delta";
			return `<span class="${cls}">${sign} ${fmt(
				Math.abs(val)
			)} <small>vs last census</small></span>`;
		};

		const co = p.cashouts || { count: 0, rows: [] };
		const oldestH = co.oldest_at ? this.age_hours(co.oldest_at, now) : null;
		const coChip =
			co.count === 0
				? '<span class="fp-chip ok">● All clear</span>'
				: oldestH >= 24
				? `<span class="fp-chip serious">⚠ Oldest ${this.age_label(oldestH)}</span>`
				: oldestH >= 6
				? `<span class="fp-chip warn">● Oldest ${this.age_label(oldestH)}</span>`
				: '<span class="fp-chip ok">● Fresh</span>';

		const up = p.upgrades || { count: 0, rows: [] };
		const upOldest = up.rows.length ? this.age_hours(up.rows[0].creation, now) : null;
		const upChip =
			up.count === 0
				? '<span class="fp-chip ok">● All clear</span>'
				: upOldest >= 24
				? `<span class="fp-chip warn">● Oldest ${this.age_label(upOldest)}</span>`
				: '<span class="fp-chip ok">● All &lt; 24h</span>';

		const usdt = c ? this.money(c.usdt_total) : "—";
		const [usdtWhole, usdtCents] = usdt === "—" ? ["—", ""] : usdt.split(".");

		$m.find("#fp-pulse").html(`
            <a class="fp-tile fp-rise" href="/app/wallet-census">
                <div class="fp-label">USDT float</div>
                <div class="fp-value">${usdtWhole}${
			usdtCents ? `<span class="fp-unit">.${usdtCents}</span>` : ""
		}</div>
                <div class="fp-foot">
                    ${delta(c && c.usdt_delta, (v) => this.money(v))}
                    <svg class="fp-spark" id="fp-spark" viewBox="0 0 92 28" aria-hidden="true"></svg>
                </div>
            </a>
            <a class="fp-tile fp-rise" href="/app/wallet-census">
                <div class="fp-label">Funded accounts</div>
                <div class="fp-value">${c ? this.esc(c.funded) : "—"}</div>
                <div class="fp-foot">${delta(c && c.funded_delta, (v) => v)}</div>
            </a>
            <a class="fp-tile fp-rise" href="/app/transfer-requests">
                <div class="fp-label">Cashouts needing action</div>
                <div class="fp-value">${this.esc(co.count)}</div>
                <div class="fp-foot">${coChip}</div>
            </a>
            <a class="fp-tile fp-rise" href="#" data-scroll="#fp-requests">
                <div class="fp-label">Upgrade requests pending</div>
                <div class="fp-value">${this.esc(up.count)}</div>
                <div class="fp-foot">${upChip}</div>
            </a>
        `);

		// desk router for the tile links (keep SPA navigation)
		$m.find(".fp-tile").on("click", function (e) {
			e.preventDefault();
			const scroll = $(this).data("scroll");
			if (scroll) {
				const el = document.querySelector(scroll);
				if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
				return;
			}
			const href = $(this).attr("href");
			if (href && href.startsWith("/app/")) {
				frappe.set_route(href.replace("/app/", ""));
			}
		});

		this.render_chart();
		this.render_queue();
	}

	/* ── charts ───────────────────────────────── */
	render_chart() {
		const c = this.pulse && this.pulse.census;
		const history = (c && c.history) || [];
		const svg = this.page.main.find("#fp-trend")[0];
		const tt = this.page.main.find("#fp-tt")[0];
		if (!svg) return;

		if (history.length >= 2) {
			const spark = this.page.main.find("#fp-spark")[0];
			if (spark)
				this.draw_spark(
					spark,
					history.map((d) => d.usdt)
				);
		}

		if (history.length < 2) {
			svg.innerHTML = "";
			this.page.main
				.find(".fp-chart-box")
				.html(
					'<div class="fp-empty">Run a couple of censuses and the float trend will chart here.</div>'
				);
			return;
		}

		const W = 720,
			H = 216,
			padL = 48,
			padR = 14,
			padT = 12,
			padB = 22;
		svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
		const data = history.map((d) => d.usdt);
		const span = Math.max(...data) - Math.min(...data) || 1;
		const min = Math.min(...data) - span * 0.15;
		const max = Math.max(...data) + span * 0.15;
		const x = (i) => padL + (i * (W - padL - padR)) / (data.length - 1);
		const y = (v) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
		const accent = this.tok("--fp-accent");
		const surface = this.tok("--fp-surface");

		let grid = "";
		for (let s = 0; s <= 4; s++) {
			const v = min + ((max - min) * s) / 4;
			grid +=
				`<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" stroke="${this.tok(
					"--fp-line-soft"
				)}" stroke-width="1"/>` +
				`<text x="${padL - 8}" y="${
					y(v) + 4
				}" text-anchor="end" font-size="10.5" fill="${this.tok(
					"--fp-ink3"
				)}" style="font-variant-numeric:tabular-nums">$${(v / 1000).toFixed(1)}k</text>`;
		}
		const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
		const area = `${padL},${y(min)} ${line} ${x(data.length - 1)},${y(min)}`;
		const endX = x(data.length - 1),
			endY = y(data[data.length - 1]);

		svg.innerHTML = `
            <defs><linearGradient id="fp-g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="${accent}" stop-opacity="0.16"/>
                <stop offset="1" stop-color="${accent}" stop-opacity="0"/>
            </linearGradient></defs>
            ${grid}
            <polygon points="${area}" fill="url(#fp-g)"/>
            <polyline points="${line}" fill="none" stroke="${accent}" stroke-width="2" stroke-linejoin="round"/>
            <circle cx="${endX}" cy="${endY}" r="3.5" fill="${accent}" stroke="${surface}" stroke-width="2"/>
            <text x="${endX - 6}" y="${
			endY - 10
		}" text-anchor="end" font-size="11" font-weight="600" fill="${this.tok(
			"--fp-ink"
		)}">${this.money(data[data.length - 1])}</text>
            <line id="fp-xh" y1="${padT}" y2="${H - padB}" stroke="${this.tok(
			"--fp-ink3"
		)}" stroke-width="1" stroke-dasharray="2 3" visibility="hidden"/>
            <circle id="fp-hd" r="3.5" fill="${accent}" stroke="${surface}" stroke-width="2" visibility="hidden"/>
            <rect x="${padL}" y="${padT}" width="${W - padL - padR}" height="${
			H - padT - padB
		}" fill="transparent" id="fp-hit"/>
        `;

		const hit = svg.querySelector("#fp-hit"),
			xh = svg.querySelector("#fp-xh"),
			hd = svg.querySelector("#fp-hd");
		hit.addEventListener("mousemove", (e) => {
			const r = svg.getBoundingClientRect();
			const px = ((e.clientX - r.left) / r.width) * W;
			const i = Math.round(((px - padL) / (W - padL - padR)) * (data.length - 1));
			const ci = Math.max(0, Math.min(data.length - 1, i));
			xh.setAttribute("x1", x(ci));
			xh.setAttribute("x2", x(ci));
			xh.setAttribute("visibility", "visible");
			hd.setAttribute("cx", x(ci));
			hd.setAttribute("cy", y(data[ci]));
			hd.setAttribute("visibility", "visible");
			tt.style.display = "block";
			const leftPct = (x(ci) / W) * 100;
			tt.style.left = `calc(${leftPct}% + ${leftPct > 70 ? -140 : 14}px)`;
			tt.style.top = `${(y(data[ci]) / H) * 100}%`;
			const d = history[ci];
			tt.innerHTML = `<b>${this.money(d.usdt)}</b><span>${this.esc(d.snapshot)} · ${this.esc(
				d.funded
			)} funded</span>`;
		});
		hit.addEventListener("mouseleave", () => {
			xh.setAttribute("visibility", "hidden");
			hd.setAttribute("visibility", "hidden");
			tt.style.display = "none";
		});
	}

	draw_spark(svg, data) {
		const w = 92,
			h = 28,
			pad = 3;
		const min = Math.min(...data),
			max = Math.max(...data);
		const x = (i) => pad + (i * (w - 2 * pad)) / (data.length - 1);
		const y = (v) => h - pad - ((v - min) / (max - min || 1)) * (h - 2 * pad);
		const pts = data.map((v, i) => `${x(i)},${y(v)}`);
		const cut = Math.max(1, data.length - 4);
		svg.innerHTML =
			`<polyline points="${pts.slice(0, cut + 1).join(" ")}" fill="none" stroke="${this.tok(
				"--fp-spark"
			)}" stroke-width="1.5"/>` +
			`<polyline points="${pts.slice(cut).join(" ")}" fill="none" stroke="${this.tok(
				"--fp-accent"
			)}" stroke-width="1.5"/>` +
			`<circle cx="${x(data.length - 1)}" cy="${y(
				data[data.length - 1]
			)}" r="2.5" fill="${this.tok("--fp-accent")}"/>`;
	}

	/* ── needs-action queue ───────────────────── */
	render_queue() {
		const p = this.pulse || {};
		const now = p.now || "";
		const co = p.cashouts || { rows: [] };
		const up = p.upgrades || { rows: [] };

		const coRows = co.rows.length
			? co.rows
					.map((r) => {
						const h = this.age_hours(r.creation, now);
						const sev = h >= 24 ? "serious" : h >= 6 ? "warn" : "";
						return `<div class="fp-qrow ${sev}" data-route="transfer-requests" role="link" tabindex="0">
                          <div class="fp-qmain">
                              <div class="fp-qtitle">Cashout · ${this.esc(
									r.customer || r.name
								)}</div>
                              <div class="fp-qsub">${this.esc(r.status)}</div>
                          </div>
                          <div class="fp-qamt">${this.esc(r.currency || "")} ${
							r.user_receives != null ? Number(r.user_receives).toLocaleString() : ""
						}</div>
                          <div class="fp-qage">${this.age_label(h)}</div>
                      </div>`;
					})
					.join("")
			: '<div class="fp-empty" style="padding:10px 0">No cashouts waiting — all clear.</div>';

		const upRows = up.rows.length
			? up.rows
					.map((r) => {
						const h = this.age_hours(r.creation, now);
						return `<div class="fp-qrow" data-hub="${this.esc(
							r.username || ""
						)}" role="link" tabindex="0">
                          <div class="fp-qmain">
                              <div class="fp-qtitle">${this.esc(
									r.username || r.name
								)} → ${this.esc(r.requested_level || "")}</div>
                              <div class="fp-qsub">Awaiting review</div>
                          </div>
                          <div class="fp-qage">${this.age_label(h)}</div>
                      </div>`;
					})
					.join("")
			: '<div class="fp-empty" style="padding:10px 0">No pending upgrade requests.</div>';

		const $q = this.page.main.find("#fp-queue");
		$q.html(`
            <div class="fp-qhead"><h3>Needs action</h3><a href="#" data-route="transfer-requests">Transfer requests →</a></div>
            ${coRows}
            <div class="fp-qhead"><h3>Upgrade requests</h3><a href="#" data-route="account-hub">Account Hub →</a></div>
            ${upRows}
        `);

		$q.find("[data-route]").on("click", function (e) {
			e.preventDefault();
			frappe.set_route($(this).data("route"));
		});
		$q.find("[data-hub]").on("click", function () {
			const q = $(this).data("hub");
			if (q) {
				frappe.route_options = { account_hub_query: q };
				frappe.set_route("account-hub");
			}
		});
	}

	/* ── upgrade requests table (existing flow) ── */
	render_requests() {
		const data = this.stats;
		const $out = this.page.main.find("#fp-requests");
		if (!data) {
			$out.html('<div class="fp-empty">Could not load upgrade requests.</div>');
			return;
		}
		const requests = data.all_requests || data.recent_requests || [];
		const q = (this.page.main.find(".ad-smart-search").val() || "").toLowerCase().trim();

		const badge = (s) => {
			const cls = {
				Pending: "ad-badge-pending",
				Approved: "ad-badge-approved",
				Rejected: "ad-badge-rejected",
			};
			return `<span class="ad-badge ${cls[s] || "ad-badge-default"}">${this.esc(
				s || "—"
			)}</span>`;
		};

		const filtered = q
			? requests.filter((r) =>
					[r.username, r.full_name, r.phone_number, r.email]
						.filter(Boolean)
						.some((v) => String(v).toLowerCase().includes(q))
			  )
			: requests;

		if (!filtered.length) {
			$out.html('<div class="fp-empty">No upgrade requests match that search.</div>');
			return;
		}

		const rows = filtered
			.slice(0, 50)
			.map(
				(r) => `
            <tr class="ad-req-row" data-query="${this.esc(
				r.username || r.phone_number || r.email || r.name || ""
			)}">
                <td><strong>${this.esc(r.username || "—")}</strong></td>
                <td>${this.esc(r.full_name || "—")}</td>
                <td>${this.esc(r.current_level || "—")} → ${this.esc(
					r.requested_level || "—"
				)}</td>
                <td>${badge(r.status)}</td>
                <td>${this.esc((r.modified || "").split(".")[0])}</td>
            </tr>`
			)
			.join("");

		$out.html(`
            <div style="overflow-x:auto" id="fp-requests-anchor">
                <table class="fp-table">
                    <thead><tr><th>Username</th><th>Name</th><th>Level</th><th>Status</th><th>Updated</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `);
	}
}

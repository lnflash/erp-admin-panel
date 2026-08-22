frappe.pages["admin-dashboard"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Dashboard",
		single_column: true,
	});

	// Mirrors admin_panel.api.auth.ADMIN_ROLES — the gate on every endpoint
	// this page calls. Gating on "Accounts Manager" alone locked Flash Admins
	// out of a page whose data those same APIs were already serving them, and
	// this page is now the desk landing page, so the mismatch was the first
	// thing a Flash Admin would hit on login.
	const ADMIN_ROLES = ["System Manager", "Accounts Manager", "Flash Admin"];
	if (!ADMIN_ROLES.some((role) => frappe.user_roles.includes(role))) {
		page.main.html(`
            <div class="text-center mt-5">
                <div class="alert alert-warning">
                    <h4>Access Denied</h4>
                    <p>You do not have permission to access this page. Please contact your administrator to get one of these roles: ${ADMIN_ROLES.join(
						", "
					)}.</p>
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
   Ops Pulse dashboard — above-the-fold edition
   Design: single validated accent (#007856 light / #1E9E75 dark), desk theme
   tokens for surfaces/ink, status colors only for queue urgency (icon+label,
   never color alone). The whole default state fits a 1440×900 fold: revenue
   and pulse compress to slim stat rails, the directory collapses to group
   pills, and the jump field is a command palette (/, ↑↓, ⏎). Expanding a
   pill or the palette is user-initiated and may scroll; the DEFAULT state is
   the fold contract.
   ───────────────────────────────────────────── */

const FP_CSS = `
    .fp { --fp-surface: var(--card-bg, #ffffff); --fp-ink: var(--text-color, #1a2420);
          --fp-ink2: var(--text-muted, #5c6b65); --fp-ink3: var(--text-light, #8fa098);
          --fp-line: var(--border-color, #e2e8e5); --fp-line-soft: var(--subtle-fg, #ecf1ee);
          --fp-accent: #007856; --fp-accent-ink: #007856; --fp-accent-soft: #e6f3ee;
          --fp-good: #0ca30c; --fp-mark: #fdf1c7;
          --fp-warn: #b87d00; --fp-warn-bg: #fff3d6;
          --fp-serious: #c05a32; --fp-serious-bg: #fdeae2;
          --fp-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
          max-width: 1240px; margin: 0 auto; }
    [data-theme="dark"] .fp, .dark .fp {
          --fp-accent: #1e9e75; --fp-accent-ink: #4cc29e; --fp-accent-soft: #12352a;
          --fp-good: #35c135; --fp-mark: #4a3f15;
          --fp-warn: #fab219; --fp-warn-bg: #33290d;
          --fp-serious: #ec835a; --fp-serious-bg: #38211a;
          --fp-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25); }

    .fp * { box-sizing: border-box; }
    .fp .fp-meta { display: flex; align-items: center; justify-content: flex-end; gap: 14px;
          color: var(--fp-ink2); font-size: 12px; margin: -4px 0 8px; flex-wrap: wrap; }
    .fp .fp-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--fp-good);
          display: inline-block; margin-right: 6px; }
    .fp .fp-refresh { cursor: pointer; color: var(--fp-accent-ink); font-weight: 600; }
    .fp .fp-refresh:hover { text-decoration: underline; }
    .fp .fp-empty { color: var(--fp-ink3); font-size: 12.5px; padding: 14px 0; text-align: center; }
    .fp .fp-delta { font-size: 11.5px; font-weight: 600; color: var(--fp-ink3); }
    .fp .fp-delta.up { color: var(--fp-good); }
    .fp .fp-delta small { color: var(--fp-ink3); font-weight: 500; margin-left: 3px; }
    .fp .fp-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px;
          font-weight: 650; border-radius: 999px; padding: 1px 8px; }
    .fp .fp-chip.warn { color: var(--fp-warn); background: var(--fp-warn-bg); }
    .fp .fp-chip.serious { color: var(--fp-serious); background: var(--fp-serious-bg); }
    .fp .fp-chip.ok { color: var(--fp-good); background: var(--fp-accent-soft); }
    .fp .ad-section-title { font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--fp-ink2); font-weight: 650; margin: 0 0 7px; display: flex;
          align-items: baseline; gap: 10px; }
    .fp .ad-section-title small { text-transform: none; letter-spacing: 0; font-weight: 500;
          color: var(--fp-ink3); font-size: 11px; }
    .fp .ad-kbd { font-family: var(--font-family-monospace, monospace); font-size: 10.5px;
          color: var(--fp-ink2); background: var(--fp-line-soft); border: 1px solid var(--fp-line);
          border-bottom-width: 2px; border-radius: 5px; padding: 0 5px; white-space: nowrap; }

    /* slim stat rail (revenue) */
    .fp .ad-rev { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 10px; margin-bottom: 4px; }
    .fp .ad-stat { background: var(--fp-surface); border: 1px solid var(--fp-line);
          border-radius: 10px; padding: 9px 13px 8px; box-shadow: var(--fp-shadow); min-width: 0; }
    .fp .ad-stat.lead { border-color: var(--fp-accent); }
    .fp .ad-stat-l { font-size: 10.5px; letter-spacing: 0.05em; text-transform: uppercase;
          color: var(--fp-ink2); font-weight: 600; }
    .fp .ad-stat-v { font-size: 20px; font-weight: 650; letter-spacing: -0.01em; line-height: 1.15;
          color: var(--fp-ink); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .fp .ad-stat-s { font-size: 11px; color: var(--fp-ink3); font-variant-numeric: tabular-nums;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fp .ad-revnote { color: var(--fp-ink3); font-size: 11px; margin: 0 0 12px; }
    .fp .ad-revnote strong { color: var(--fp-warn); font-weight: 600; }

    /* chart + queue duo */
    .fp .fp-grid { display: grid; grid-template-columns: 1.8fr 1fr; gap: 10px; margin-bottom: 14px; }
    @media (max-width: 900px) { .fp .fp-grid { grid-template-columns: 1fr; } }
    .fp .fp-card { background: var(--fp-surface); border: 1px solid var(--fp-line);
          border-radius: 10px; box-shadow: var(--fp-shadow); padding: 11px 14px; min-width: 0; }
    .fp .fp-card h2 { font-size: 12px; font-weight: 650; margin: 0 0 6px; color: var(--fp-ink);
          display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .fp .fp-chart-box { position: relative; }
    .fp .fp-chart-box svg { display: block; width: 100%; height: 120px; }
    .fp .fp-tt { position: absolute; pointer-events: none; background: var(--fp-surface);
          border: 1px solid var(--fp-line); border-radius: 8px; box-shadow: var(--fp-shadow);
          padding: 7px 10px; font-size: 12px; display: none; z-index: 3; white-space: nowrap; }
    .fp .fp-tt b { font-size: 13px; display: block; color: var(--fp-ink); }
    .fp .fp-tt span { color: var(--fp-ink2); }
    .fp .fp-qrow { display: flex; align-items: center; gap: 8px; padding: 4px 8px;
          border-radius: 6px; border-left: 3px solid var(--fp-line); cursor: pointer;
          font-size: 12px; color: var(--fp-ink); transition: background 0.12s; }
    .fp .fp-qrow:hover { background: var(--fp-line-soft); }
    .fp .fp-qrow:focus-visible { outline: 2px solid var(--fp-accent); outline-offset: -2px; }
    .fp .fp-qrow + .fp-qrow { margin-top: 3px; }
    .fp .fp-qrow.warn { border-left-color: var(--fp-warn); }
    .fp .fp-qrow.serious { border-left-color: var(--fp-serious); }
    .fp .fp-qtitle { font-weight: 600; white-space: nowrap; overflow: hidden;
          text-overflow: ellipsis; min-width: 0; }
    .fp .fp-qamt { margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 650;
          flex: none; }
    .fp .fp-qage { color: var(--fp-ink3); font-size: 11px; flex: none; min-width: 26px;
          text-align: right; }

    /* go to: jump palette */
    .fp .ad-jumpwrap { position: relative; margin-bottom: 10px; }
    .fp .ad-jump { display: flex; align-items: center; gap: 10px; background: var(--fp-surface);
          border: 1.5px solid var(--fp-line); border-radius: 10px; padding: 8px 13px;
          cursor: text; transition: border-color 0.12s; }
    .fp .ad-jump:focus-within { border-color: var(--fp-accent); }
    .fp .ad-jump svg { flex: none; color: var(--fp-ink3); }
    .fp .ad-jump input { flex: 1; border: 0; outline: 0; background: transparent; font: inherit;
          font-size: 14px; color: var(--fp-ink); min-width: 0; }
    .fp .ad-jump input::placeholder { color: var(--fp-ink3); }
    .fp .ad-pal { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 5;
          background: var(--fp-surface); border: 1px solid var(--fp-line); border-radius: 12px;
          box-shadow: var(--fp-shadow); padding: 6px; display: none; max-height: 320px;
          overflow-y: auto; }
    .fp .ad-pal.on { display: block; }
    .fp .ad-pal-g { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--fp-ink3); font-weight: 650; padding: 6px 10px 2px; }
    .fp .ad-prow { display: flex; align-items: center; gap: 9px; width: 100%; text-align: left;
          border: 0; background: transparent; font: inherit; color: var(--fp-ink);
          padding: 6px 10px; border-radius: 8px; cursor: pointer; font-weight: 500;
          font-size: 13px; }
    .fp .ad-prow:hover { background: var(--fp-line-soft); }
    .fp .ad-prow.sel { background: var(--fp-accent-soft); color: var(--fp-accent-ink); }
    .fp .ad-prow mark { background: var(--fp-mark); color: inherit; border-radius: 3px;
          padding: 0 1px; }
    .fp .ad-prow .ad-prow-d { margin-left: auto; color: var(--fp-ink3); font-size: 11.5px;
          font-weight: 400; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          max-width: 45%; }
    .fp .ad-pal-none { color: var(--fp-ink3); font-size: 12.5px; padding: 10px 12px; }
    .fp .ad-tool-icon { width: 20px; height: 20px; flex: none; border-radius: 6px;
          background: var(--fp-accent-soft); color: var(--fp-accent-ink); display: grid;
          place-items: center; font-size: 8.5px; font-weight: 700; letter-spacing: 0.02em; }
    .fp .ad-prow.sel .ad-tool-icon { background: var(--fp-accent); color: #fff; }

    /* frequent chips */
    .fp .ad-freqrow { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }
    .fp .ad-freqchip { display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
          background: var(--fp-surface); border: 1px solid var(--fp-line); border-radius: 999px;
          padding: 4px 11px 4px 5px; font-size: 12px; font-weight: 600; color: var(--fp-ink);
          transition: border-color 0.15s; }
    .fp .ad-freqchip:hover, .fp .ad-freqchip:focus-visible { border-color: var(--fp-accent);
          outline: none; }

    /* collapsed directory: group pills + expand panels */
    .fp .ad-pills { display: flex; flex-wrap: wrap; gap: 7px; align-items: center;
          margin-bottom: 12px; }
    .fp .ad-pill { display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
          border: 1px solid var(--fp-line); background: var(--fp-surface); border-radius: 9px;
          padding: 6px 12px; font-size: 12.5px; font-weight: 600; color: var(--fp-ink);
          font-family: inherit; transition: border-color 0.12s; }
    .fp .ad-pill:hover, .fp .ad-pill:focus-visible { border-color: var(--fp-accent);
          outline: none; }
    .fp .ad-pill .ad-pill-n { color: var(--fp-ink2); font-weight: 500;
          font-variant-numeric: tabular-nums; }
    .fp .ad-pill .ad-pill-c { transition: transform 0.15s; color: var(--fp-ink3);
          display: inline-flex; }
    .fp .ad-pill[aria-expanded="true"] { border-color: var(--fp-accent);
          color: var(--fp-accent-ink); }
    .fp .ad-pill[aria-expanded="true"] .ad-pill-c { transform: rotate(90deg); }
    .fp .ad-panel { display: none; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 2px 20px; background: var(--fp-surface); border: 1px solid var(--fp-line);
          border-radius: 10px; padding: 10px 12px; margin: -4px 0 12px;
          box-shadow: var(--fp-shadow); }
    .fp .ad-panel.on { display: grid; }
    .fp .ad-row { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
          border: 0; background: transparent; font: inherit; color: var(--fp-ink);
          padding: 4px 8px; border-radius: 7px; cursor: pointer; font-weight: 500;
          font-size: 13px; }
    .fp .ad-row:hover { background: var(--fp-line-soft); }
    .fp .ad-row:focus-visible { outline: 2px solid var(--fp-accent); outline-offset: -2px; }
    .fp .ad-row span { min-width: 0; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; }

    /* upgrade requests table (top 3 + view all) */
    .fp .fp-tablecard { padding: 0; overflow: hidden; margin-bottom: 30px; }
    .fp .fp-tablehead { display: flex; align-items: center; gap: 10px; padding: 9px 14px;
          border-bottom: 1px solid var(--fp-line); flex-wrap: wrap; }
    .fp .fp-tablehead h2 { margin: 0; font-size: 12px; border: 0; padding: 0; }
    .fp .ad-view-all { margin-left: auto; font-size: 12px; color: var(--fp-accent-ink);
          font-weight: 600; cursor: pointer; }
    .fp .ad-view-all:hover { text-decoration: underline; }
    .fp table.fp-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    .fp table.fp-table td { padding: 6px 14px; border-bottom: 1px solid var(--fp-line-soft);
          color: var(--fp-ink); font-variant-numeric: tabular-nums; }
    .fp table.fp-table tr:last-child td { border-bottom: 0; }
    .fp .ad-req-row { cursor: pointer; }
    .fp .ad-req-row:hover { background: var(--fp-line-soft); }
    .fp .ad-badge { display: inline-block; border-radius: 999px; padding: 1px 8px;
          font-size: 11px; font-weight: 600; }
    .fp .ad-badge-pending { color: var(--fp-warn); background: var(--fp-warn-bg); }
    .fp .ad-badge-approved { color: var(--fp-good); background: var(--fp-accent-soft); }
    .fp .ad-badge-rejected { color: var(--fp-serious); background: var(--fp-serious-bg); }
    .fp .ad-badge-default { color: var(--fp-ink2); background: var(--fp-line-soft); }

    @media (prefers-reduced-motion: no-preference) {
        .fp .fp-rise { opacity: 0; transform: translateY(6px); animation: fp-rise 0.35s ease forwards; }
        @keyframes fp-rise { to { opacity: 1; transform: none; } }
    }
    @media (prefers-reduced-motion: reduce) {
        .fp .ad-pill .ad-pill-c { transition: none; }
    }
`;

class OpsDashboard {
	constructor(page) {
		this.page = page;
		this.stats = null;
		this.pulse = null;
		this.revenue = null;
		this.nav = null;
		this.pal_sel = 0;
		this.open_group = null;
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
			error: () => {
				this.stats = null;
				this.render_requests();
			},
		});
		frappe.call({
			method: "admin_panel.api.revenue.get_revenue_summary",
			callback: (r) => {
				this.revenue = r.message || null;
				this.render_revenue();
			},
			error: () => this.render_revenue_error(),
		});
		frappe.call({
			method: "admin_panel.api.nav.get_nav",
			callback: (r) => {
				this.nav = r.message || null;
				this.render_nav();
			},
			error: () => this.render_nav_error(),
		});
	}

	open_tile(el) {
		const route = $(el).data("route");
		if (!route) return;
		// Desk keeps this wrapper alive across navigation — without closing
		// here, returning to the dashboard would show the palette still open
		// on the stale query.
		this.page.main.find("#ad-jump-input").val("");
		this.close_palette();
		this.record_visit(route);
		frappe.set_route(route);
	}

	/* Tile clicks feed the frequently-used ranking. Frappe's own recorder
	   (router_history.js) drops single-segment routes, so every custom Page
	   here would otherwise never register a single visit. Fire-and-forget:
	   navigation must not wait on, or be blocked by, bookkeeping. */
	record_visit(route) {
		frappe.call({
			method: "admin_panel.api.nav.record_visit",
			args: { route: route },
			callback: () => {},
			error: () => {},
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
                <p class="ad-section-title">Revenue · Flash fees <small>USD · cashout + card</small></p>
                <div class="ad-rev" id="ad-revenue">
                    <div class="fp-empty">Loading revenue…</div>
                </div>
                <p class="ad-revnote" id="ad-revnote"></p>
                <p class="ad-section-title">Operations</p>
                <div class="fp-grid">
                    <div class="fp-card fp-rise">
                        <h2>USDT float <span id="fp-float-head"></span></h2>
                        <div class="fp-chart-box">
                            <svg id="fp-trend" role="img" aria-label="USDT float trend across recent census runs"></svg>
                            <div class="fp-tt" id="fp-tt"></div>
                        </div>
                    </div>
                    <div class="fp-card fp-rise" id="fp-queue"></div>
                </div>
                <p class="ad-section-title">Go to <small>press <span class="ad-kbd">/</span> anywhere on this page</small></p>
                <div class="ad-jumpwrap">
                    <div class="ad-jump" id="ad-jumpbox">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.4-3.4"/></svg>
                        <input id="ad-jump-input" type="text" placeholder="Jump to anything… cashout, kyc, fees" autocomplete="off" aria-label="Jump to a destination">
                        <span class="ad-kbd">/</span>
                    </div>
                    <div class="ad-pal" id="ad-pal" role="listbox" aria-label="Matching destinations"></div>
                </div>
                <div class="ad-freqrow" id="ad-frequent" aria-label="Frequently used"></div>
                <div id="ad-directory">
                    <div class="ad-pills" id="ad-pills"></div>
                    <div id="ad-panels"></div>
                </div>
                <div class="fp-card fp-tablecard fp-rise">
                    <div class="fp-tablehead">
                        <h2>Upgrade requests</h2>
                        <span id="ad-req-chip"></span>
                        <span class="ad-view-all" id="ad-req-all" role="link" tabindex="0"></span>
                    </div>
                    <div id="fp-requests"><div class="fp-empty">Loading…</div></div>
                </div>
            </div>
        `);

		const $m = this.page.main;
		// Delegated: rows, palette rows and chips render from the nav registry
		// after the shell, so direct .find() bindings at shell time would
		// catch none of them.
		$m.on("click", ".ad-row, .ad-prow, .ad-freqchip", (e) => this.open_tile(e.currentTarget));
		$m.on("keydown", ".ad-row, .ad-freqchip", (e) => {
			if (e.key !== "Enter" && e.key !== " ") return;
			e.preventDefault();
			this.open_tile(e.currentTarget);
		});
		$m.find("#fp-refresh").on("click", () => this.refresh());
		$m.find("#fp-refresh").on("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") this.refresh();
		});
		$m.on("click", ".ad-req-row", function () {
			const query = $(this).data("query");
			if (query) {
				frappe.route_options = { account_hub_query: query };
				frappe.set_route("account-hub");
			}
		});
		$m.find("#ad-req-all").on("click keydown", (e) => {
			if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
			e.preventDefault();
			this.record_visit("account-management");
			frappe.set_route("account-management");
		});

		// Jump palette wiring.
		const $input = $m.find("#ad-jump-input");
		$m.find("#ad-jumpbox").on("click", () => $input.trigger("focus"));
		$input.on("input", () => this.render_palette());
		$input.on("keydown", (e) => this.palette_keydown(e));
		// Click-away closes the palette (mousedown so it wins over focus loss).
		$m.on("mousedown", (e) => {
			if (!$(e.target).closest(".ad-jumpwrap").length) this.close_palette();
		});

		// "/" focuses the jump field from anywhere on this page. Namespaced +
		// double-guarded: desk keeps page wrappers alive after navigation, so
		// an unguarded document handler would steal "/" on every OTHER desk
		// page too (same trap as the drawer Escape handlers, see
		// test_drawer_escape_handlers_guard_dialog_and_page_visibility).
		$(document).off("keydown.ad_dashboard");
		$(document).on("keydown.ad_dashboard", (e) => {
			if (e.key !== "/") return;
			if (window.cur_dialog) return;
			if (!this.page.wrapper.is(":visible")) return;
			const t = e.target;
			if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
			e.preventDefault();
			$input.trigger("focus").trigger("select");
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

	/* ── revenue rail ─────────────────────────── */
	render_revenue() {
		const r = this.revenue;
		const $m = this.page.main;
		if (!r || !r.windows) return this.render_revenue_error();

		const w = r.windows;
		const change = r.d30_change_pct;
		const changeChip =
			change == null
				? ""
				: `<span class="${change >= 0 ? "fp-delta up" : "fp-delta"}">${
						change >= 0 ? "▲" : "▼"
				  } ${Math.abs(change).toFixed(1)}% <small>vs prior 30d</small></span>`;

		const stat = (label, win, sub, lead) => `
            <div class="ad-stat${lead ? " lead" : ""}">
                <span class="ad-stat-l">${label}</span>
                <div class="ad-stat-v">${this.money(win.total)}</div>
                <div class="ad-stat-s">${sub}</div>
            </div>`;
		const split = (win) =>
			`${this.money(win.cashout)} cashout · ${this.money(win.topup)} card`;

		$m.find("#ad-revenue").html(
			[
				stat("Today", w.today, split(w.today)),
				stat("Month to date", w.mtd, split(w.mtd), true),
				stat("Last 30 days", w.d30, changeChip || split(w.d30)),
				stat("All time", w.all, split(w.all)),
			].join("")
		);

		// Everything the totals could NOT account for, stated rather than
		// buried — a Data-typed fee that never got computed reads as absent,
		// not as zero, and a non-USD fee is never folded into a USD total.
		const notes = [];
		const pending = w.all.fee_pending || 0;
		if (pending) {
			notes.push(
				`<strong>${pending} card top-up${
					pending === 1 ? "" : "s"
				} with no computed fee</strong> — excluded, not counted as zero`
			);
		}
		const other = w.all.other_currency || {};
		Object.keys(other).forEach((cur) => {
			notes.push(
				`${this.esc(cur)} ${Number(other[cur]).toLocaleString()} in ${this.esc(
					cur
				)} fees, reported separately`
			);
		});
		notes.push("Windows run on record creation date; all-time is exact");
		$m.find("#ad-revnote").html(notes.join(" · "));
	}

	render_revenue_error() {
		this.page.main
			.find("#ad-revenue")
			.html(
				'<div class="fp-empty">Could not load revenue — check the server logs and refresh.</div>'
			);
		this.page.main.find("#ad-revnote").html("");
	}

	/* ── pulse: chart headline + needs-you queue ── */
	render_pulse_error() {
		this.page.main
			.find("#fp-queue")
			.html(
				'<div class="fp-empty">Could not load the ops pulse — check the server logs and refresh.</div>'
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
				)} accounts · ${this.esc(c.funded)} funded`
			);
		} else {
			$m.find("#fp-census-age").html("No census yet");
		}

		const delta =
			c && c.usdt_delta != null
				? `<span class="fp-delta${c.usdt_delta > 0 ? " up" : ""}">${
						c.usdt_delta > 0 ? "▲" : c.usdt_delta < 0 ? "▼" : "•"
				  } ${this.money(Math.abs(c.usdt_delta))} <small>vs last census</small></span>`
				: "";
		$m.find("#fp-float-head").html(c ? `— ${this.money(c.usdt_total)} ${delta}` : "");

		this.render_chart();
		this.render_queue();
	}

	/* ── chart ────────────────────────────────── */
	render_chart() {
		const c = this.pulse && this.pulse.census;
		const history = (c && c.history) || [];
		// The <2-history branch below replaces .fp-chart-box's contents, so
		// rebuild the svg/tooltip scaffolding first — otherwise a refresh after
		// the second census finds no #fp-trend and the chart never appears.
		this.page.main
			.find(".fp-chart-box")
			.html(
				'<svg id="fp-trend" role="img" aria-label="USDT float trend across recent census runs"></svg><div class="fp-tt" id="fp-tt"></div>'
			);
		const svg = this.page.main.find("#fp-trend")[0];
		const tt = this.page.main.find("#fp-tt")[0];
		if (!svg) return;

		if (history.length < 2) {
			this.page.main
				.find(".fp-chart-box")
				.html(
					'<div class="fp-empty">Run a couple of censuses and the float trend will chart here.</div>'
				);
			return;
		}

		const W = 720,
			H = 120,
			padL = 46,
			padR = 12,
			padT = 10,
			padB = 16;
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
		for (let s = 0; s <= 3; s++) {
			const v = min + ((max - min) * s) / 3;
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

	/* ── needs-you queue ──────────────────────── */
	render_queue() {
		const p = this.pulse || {};
		const now = p.now || "";
		const co = p.cashouts || { count: 0, rows: [] };
		const up = p.upgrades || { count: 0, rows: [] };

		const oldestH = co.oldest_at ? this.age_hours(co.oldest_at, now) : null;
		const coChip = co.count
			? `<span class="fp-chip ${
					oldestH >= 24 ? "serious" : oldestH >= 6 ? "warn" : "ok"
			  }">${this.esc(co.count)} cashout${co.count === 1 ? "" : "s"}</span>`
			: "";
		const upChip = up.count
			? `<span class="fp-chip warn">${this.esc(up.count)} upgrade${
					up.count === 1 ? "" : "s"
			  }</span>`
			: "";
		const chips =
			coChip || upChip
				? `${coChip} ${upChip}`
				: '<span class="fp-chip ok">● All clear</span>';

		const coRows = co.rows
			.slice(0, 3)
			.map((r) => {
				const h = this.age_hours(r.creation, now);
				const sev = h >= 24 ? "serious" : h >= 6 ? "warn" : "";
				return `<div class="fp-qrow ${sev}" data-route="transfer-requests" role="link" tabindex="0">
                      <div class="fp-qtitle">${this.esc(r.customer || r.name)} · cashout</div>
                      <div class="fp-qamt">${this.esc(r.currency || "")} ${
					r.user_receives != null ? Number(r.user_receives).toLocaleString() : ""
				}</div>
                      <div class="fp-qage">${this.age_label(h)}</div>
                  </div>`;
			})
			.join("");
		const upRows = up.rows
			.slice(0, 2)
			.map((r) => {
				const h = this.age_hours(r.creation, now);
				return `<div class="fp-qrow" data-hub="${this.esc(
					r.username || ""
				)}" role="link" tabindex="0">
                      <div class="fp-qtitle">${this.esc(r.username || r.name)} → ${this.esc(
					r.requested_level || ""
				)}</div>
                      <div class="fp-qage">${this.age_label(h)}</div>
                  </div>`;
			})
			.join("");

		const $q = this.page.main.find("#fp-queue");
		$q.html(`
            <h2>Needs you ${chips}</h2>
            ${
				coRows + upRows ||
				'<div class="fp-empty" style="padding:8px 0">Nothing waiting — all clear.</div>'
			}
        `);

		$q.find("[data-route]").on("click keydown", function (e) {
			if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
			e.preventDefault();
			frappe.set_route($(this).data("route"));
		});
		$q.find("[data-hub]").on("click keydown", function (e) {
			if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
			e.preventDefault();
			const q = $(this).data("hub");
			if (q) {
				frappe.route_options = { account_hub_query: q };
				frappe.set_route("account-hub");
			}
		});
	}

	/* ── go to: palette, chips, collapsed pills ── */
	render_nav() {
		const nav = this.nav;
		const $m = this.page.main;
		if (!nav || !nav.groups) return this.render_nav_error();

		// render_nav_error replaces #ad-directory's contents wholesale, so a
		// successful refresh must re-create the pills/panels scaffolding the
		// shell shipped — otherwise the .find() fills below match nothing and
		// the directory stays dead until a full page reload.
		$m.find("#ad-directory").html(
			'<div class="ad-pills" id="ad-pills"></div><div id="ad-panels"></div>'
		);

		$m.find("#ad-frequent").html(
			(nav.frequent || [])
				.map(
					(link) => `
            <span class="ad-freqchip" data-route="${this.esc(
				link.route
			)}" role="link" tabindex="0" title="${this.esc(link.desc)}">
                <span class="ad-tool-icon">${this.esc(link.badge)}</span>${this.esc(link.label)}
            </span>`
				)
				.join("")
		);

		// Collapsed by default: one pill per group, rows appear on demand.
		// This is what keeps the whole default state above a 1440×900 fold.
		$m.find("#ad-pills").html(
			nav.groups
				.map(
					(g, gi) => `
            <button class="ad-pill" data-group="${gi}" aria-expanded="${
						this.open_group === gi ? "true" : "false"
					}" aria-controls="ad-panel-${gi}">
                <span class="ad-pill-c"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg></span>
                ${this.esc(g.title)} <span class="ad-pill-n">${g.links.length}</span>
            </button>`
				)
				.join("")
		);
		$m.find("#ad-panels").html(
			nav.groups
				.map(
					(g, gi) => `
            <div class="ad-panel${
				this.open_group === gi ? " on" : ""
			}" id="ad-panel-${gi}">${g.links
						.map(
							(link) => `
                <button class="ad-row" data-route="${this.esc(link.route)}" title="${this.esc(
								link.desc
							)}">
                    <span class="ad-tool-icon">${this.esc(link.badge)}</span>
                    <span>${this.esc(link.label)}</span>
                </button>`
						)
						.join("")}</div>`
				)
				.join("")
		);

		$m.find(".ad-pill")
			.off("click")
			.on("click", (e) => {
				const gi = Number($(e.currentTarget).data("group"));
				this.open_group = this.open_group === gi ? null : gi;
				// Compare against the post-toggle state, not the clicked index:
				// collapsing by re-click sets open_group to null, and the pill
				// just closed must not keep claiming aria-expanded="true".
				const open = this.open_group;
				$m.find(".ad-pill").each(function () {
					$(this).attr("aria-expanded", String(Number($(this).data("group")) === open));
				});
				$m.find(".ad-panel").removeClass("on");
				if (open !== null) $m.find(`#ad-panel-${gi}`).addClass("on");
			});
	}

	render_nav_error() {
		this.page.main
			.find("#ad-directory")
			.html(
				'<div class="fp-empty">Could not load the link directory — check the server logs and refresh.</div>'
			);
	}

	/* The palette searches label AND group title, so "money" lists the whole
	   Money movement column. First hit pre-selected: "/ tr ⏎" opens Transfer
	   Requests in three keystrokes. */
	palette_matches(q) {
		const out = [];
		for (const g of (this.nav && this.nav.groups) || []) {
			const links = g.links.filter(
				(x) => x.label.toLowerCase().includes(q) || g.title.toLowerCase().includes(q)
			);
			if (links.length) out.push({ title: g.title, links });
		}
		return out;
	}

	render_palette() {
		const $m = this.page.main;
		const $pal = $m.find("#ad-pal");
		const q = ($m.find("#ad-jump-input").val() || "").trim().toLowerCase();
		if (!q) return this.close_palette();

		const hi = (label) => {
			const i = label.toLowerCase().indexOf(q);
			if (i < 0) return this.esc(label);
			return (
				this.esc(label.slice(0, i)) +
				"<mark>" +
				this.esc(label.slice(i, i + q.length)) +
				"</mark>" +
				this.esc(label.slice(i + q.length))
			);
		};

		let n = 0;
		const groups = this.palette_matches(q);
		const html = groups
			.map(
				(g) =>
					`<div class="ad-pal-g">${this.esc(g.title)}</div>` +
					g.links
						.map(
							(x) => `
                <button class="ad-prow" role="option" data-route="${this.esc(
					x.route
				)}" data-i="${n++}">
                    <span class="ad-tool-icon">${this.esc(x.badge)}</span>
                    <span>${hi(x.label)}</span>
                    <span class="ad-prow-d">${this.esc(x.desc)}</span>
                </button>`
						)
						.join("")
			)
			.join("");
		$pal.html(
			html ||
				'<div class="ad-pal-none">No match — <span class="ad-kbd">Esc</span> to close.</div>'
		).addClass("on");
		this.pal_sel = 0;
		this.paint_palette();
	}

	paint_palette() {
		const sel = this.pal_sel;
		this.page.main.find("#ad-pal .ad-prow").each(function () {
			$(this).toggleClass("sel", Number($(this).data("i")) === sel);
		});
	}

	close_palette() {
		this.page.main.find("#ad-pal").removeClass("on").empty();
		this.pal_sel = 0;
	}

	palette_keydown(e) {
		const rows = this.page.main.find("#ad-pal .ad-prow");
		if (e.key === "Escape") {
			this.page.main.find("#ad-jump-input").val("").trigger("blur");
			this.close_palette();
		} else if (e.key === "ArrowDown") {
			e.preventDefault();
			this.pal_sel = Math.min(this.pal_sel + 1, rows.length - 1);
			this.paint_palette();
			if (rows[this.pal_sel]) rows[this.pal_sel].scrollIntoView({ block: "nearest" });
		} else if (e.key === "ArrowUp") {
			e.preventDefault();
			this.pal_sel = Math.max(this.pal_sel - 1, 0);
			this.paint_palette();
			if (rows[this.pal_sel]) rows[this.pal_sel].scrollIntoView({ block: "nearest" });
		} else if (e.key === "Enter" && rows[this.pal_sel]) {
			e.preventDefault();
			this.open_tile(rows[this.pal_sel]);
		}
	}

	/* ── upgrade requests: top 3 + view all ───── */
	render_requests() {
		const data = this.stats;
		const $m = this.page.main;
		const $out = $m.find("#fp-requests");
		if (!data) {
			$out.html('<div class="fp-empty">Could not load upgrade requests.</div>');
			return;
		}

		const pending = (data.upgrade_requests && data.upgrade_requests.pending) || 0;
		const total = data.total_requests || 0;
		$m.find("#ad-req-chip").html(
			pending
				? `<span class="fp-chip warn">${pending} pending</span>`
				: '<span class="fp-chip ok">● None pending</span>'
		);
		$m.find("#ad-req-all").text(total ? `View all ${total} →` : "Open Account Management →");

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

		// Top 3, pending first — the full queue lives in Account Management,
		// which "View all" opens. The dashboard's job is the glance.
		const requests = (data.all_requests || data.recent_requests || [])
			.slice()
			.sort((a, b) => (a.status === "Pending" ? 0 : 1) - (b.status === "Pending" ? 0 : 1))
			.slice(0, 3);

		if (!requests.length) {
			$out.html('<div class="fp-empty">No upgrade requests yet.</div>');
			return;
		}

		const rows = requests
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
                <td>${this.esc((r.creation || "").split(".")[0])}</td>
            </tr>`
			)
			.join("");

		$out.html(`
            <div style="overflow-x:auto">
                <table class="fp-table"><tbody>${rows}</tbody></table>
            </div>
        `);
	}
}

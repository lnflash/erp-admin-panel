// Bridge KYC — live Bridge.xyz customer status for every client, joined to
// Flash accounts. Read-only observability: the KYC state itself is owned by
// the flash backend + the Bridge dashboard.
const BK_VIEW_ROLES = ["System Manager", "Accounts Manager", "Flash Admin"];

const BK_BUCKET_LABELS = {
	all: "All",
	approved: "Approved",
	in_progress: "In progress",
	not_started: "Not started",
	attention: "Needs attention",
};

const BK_STATUS_TONES = {
	approved: "ok",
	in_progress: "warn",
	not_started: "muted",
	attention: "bad",
};

function bkEsc(v) {
	return frappe.utils.escape_html(String(v == null ? "" : v));
}

function bkLabel(status) {
	return String(status || "").replace(/_/g, " ");
}

// Relative age from the SERVER clock (both stamps are UTC ISO with T/Z) —
// never the browser clock, which skews and breaks on non-ISO parsing.
function bkAgo(iso, nowIso) {
	if (!iso) return "—";
	const then = Date.parse(iso);
	const now = Date.parse(nowIso);
	if (!Number.isFinite(then) || !Number.isFinite(now)) return String(iso).slice(0, 10);
	const mins = Math.floor((now - then) / 60000);
	if (mins < 1) return "just now";
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 48) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 90) return `${days}d ago`;
	return String(iso).slice(0, 10);
}

const BK_CSS = `
    .bridge-kyc-page {
        --bk-surface: var(--card-bg, #ffffff); --bk-ink: var(--text-color, #1a2420);
        --bk-ink2: var(--text-muted, #5c6b65); --bk-ink3: var(--text-light, #8fa098);
        --bk-line: var(--border-color, #e2e8e5); --bk-line-soft: var(--subtle-fg, #ecf1ee);
        --bk-accent: #007856; --bk-accent-ink: #007856; --bk-accent-soft: #e6f3ee;
        --bk-warn: #b87d00; --bk-warn-bg: #fff3d6;
        --bk-bad: #c05a32; --bk-bad-bg: #fdeae2;
        --bk-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
        max-width: 1180px; margin: 0 auto; padding: 8px 12px 40px;
    }
    [data-theme="dark"] .bridge-kyc-page, .dark .bridge-kyc-page {
        --bk-accent: #1e9e75; --bk-accent-ink: #4cc29e; --bk-accent-soft: #12352a;
        --bk-warn: #fab219; --bk-warn-bg: #33290d;
        --bk-bad: #ec835a; --bk-bad-bg: #38211a;
        --bk-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25);
    }

    .bridge-kyc-page .bk-toolbar { display: flex; align-items: center; gap: 10px;
        margin-bottom: 14px; flex-wrap: wrap; }
    .bridge-kyc-page .bk-meta { color: var(--bk-ink3); font-size: 12px; }
    .bridge-kyc-page .bk-meta.err { color: var(--bk-bad); font-weight: 600; }
    .bridge-kyc-page .bk-btn { display: inline-flex; align-items: center; gap: 6px;
        border: 1px solid var(--bk-line); background: var(--bk-surface); color: var(--bk-ink);
        border-radius: 9px; padding: 7px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer; transition: all 0.13s; }
    .bridge-kyc-page .bk-btn:hover { border-color: var(--bk-accent); }
    .bridge-kyc-page .bk-btn:focus-visible { outline: 2px solid var(--bk-accent); outline-offset: 1px; }
    .bridge-kyc-page .bk-btn:disabled { opacity: 0.55; cursor: not-allowed; }
    .bridge-kyc-page .bk-spacer { margin-left: auto; }
    .bridge-kyc-page .bk-search { border: 1px solid var(--bk-line); background: var(--bk-surface);
        color: var(--bk-ink); border-radius: 9px; padding: 7px 12px; font-size: 13px;
        min-width: 220px; }
    .bridge-kyc-page .bk-search:focus { outline: 2px solid var(--bk-accent); outline-offset: 1px; }

    .bridge-kyc-page .bk-tiles { display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px;
        margin-bottom: 14px; }
    .bridge-kyc-page .bk-tile { background: var(--bk-surface); border: 1px solid var(--bk-line);
        border-radius: 14px; box-shadow: var(--bk-shadow); padding: 12px 16px;
        cursor: pointer; transition: border-color 0.13s; }
    .bridge-kyc-page .bk-tile:hover { border-color: var(--bk-accent); }
    .bridge-kyc-page .bk-tile[aria-pressed="true"] { border-color: var(--bk-accent);
        outline: 1px solid var(--bk-accent); }
    .bridge-kyc-page .bk-tile-label { font-size: 11px; letter-spacing: 0.06em;
        text-transform: uppercase; color: var(--bk-ink2); font-weight: 650; }
    .bridge-kyc-page .bk-tile-value { font-size: 22px; font-weight: 650; color: var(--bk-ink);
        font-variant-numeric: tabular-nums; margin-top: 2px; }
    .bridge-kyc-page .bk-tile-value.ok { color: var(--bk-accent-ink); }
    .bridge-kyc-page .bk-tile-value.warn { color: var(--bk-warn); }
    .bridge-kyc-page .bk-tile-value.bad { color: var(--bk-bad); }
    .bridge-kyc-page .bk-tile-sub { font-size: 11.5px; color: var(--bk-ink3); margin-top: 2px; }

    .bridge-kyc-page .bk-card { background: var(--bk-surface); border: 1px solid var(--bk-line);
        border-radius: 14px; box-shadow: var(--bk-shadow); overflow: hidden; }
    .bridge-kyc-page .bk-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    .bridge-kyc-page .bk-table th { text-align: left; font-size: 11px; letter-spacing: 0.05em;
        text-transform: uppercase; color: var(--bk-ink2); font-weight: 650; padding: 10px 14px;
        border-bottom: 1px solid var(--bk-line); background: var(--bk-line-soft); }
    .bridge-kyc-page .bk-table td { padding: 9px 14px; border-bottom: 1px solid var(--bk-line-soft);
        color: var(--bk-ink); vertical-align: middle; }
    .bridge-kyc-page .bk-row { cursor: pointer; }
    .bridge-kyc-page .bk-row:hover td { background: var(--bk-line-soft); }
    .bridge-kyc-page .bk-row-name { font-weight: 650; }
    .bridge-kyc-page .bk-row-email { color: var(--bk-ink3); font-size: 11.5px; }
    .bridge-kyc-page .bk-empty { color: var(--bk-ink3); font-size: 12.5px; padding: 16px; }

    .bridge-kyc-page .bk-chip { display: inline-flex; align-items: center; border-radius: 999px;
        padding: 3px 11px; font-size: 11.5px; font-weight: 650; letter-spacing: 0.02em;
        background: var(--bk-line-soft); color: var(--bk-ink2); white-space: nowrap; }
    .bridge-kyc-page .bk-chip.ok { background: var(--bk-accent-soft); color: var(--bk-accent-ink); }
    .bridge-kyc-page .bk-chip.warn { background: var(--bk-warn-bg); color: var(--bk-warn); }
    .bridge-kyc-page .bk-chip.bad { background: var(--bk-bad-bg); color: var(--bk-bad); }
    .bridge-kyc-page .bk-chip.muted { background: var(--bk-line-soft); color: var(--bk-ink3); }
    .bridge-kyc-page .bk-chip.user { background: var(--bk-accent-soft); color: var(--bk-accent-ink);
        font-family: var(--font-mono, monospace); font-weight: 600; }

    .bridge-kyc-page .bk-detail td { background: var(--bk-line-soft); padding: 12px 18px; }
    .bridge-kyc-page .bk-detail-grid { display: grid; gap: 12px;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    .bridge-kyc-page .bk-detail-block { background: var(--bk-surface); border: 1px solid var(--bk-line);
        border-radius: 10px; padding: 10px 14px; }
    .bridge-kyc-page .bk-detail-title { font-size: 11px; letter-spacing: 0.05em;
        text-transform: uppercase; color: var(--bk-ink2); font-weight: 650; margin-bottom: 6px; }
    .bridge-kyc-page .bk-detail-block ul { margin: 0; padding-left: 18px; }
    .bridge-kyc-page .bk-detail-block li { margin: 2px 0; }
    .bridge-kyc-page .bk-detail-block li.bk-issue { color: var(--bk-warn); }
    .bridge-kyc-page .bk-detail-block li.bk-reject { color: var(--bk-bad); }
    .bridge-kyc-page .bk-detail-empty { color: var(--bk-ink3); font-size: 12px; }
    .bridge-kyc-page .bk-detail-id { font-family: var(--font-mono, monospace); font-size: 11px;
        color: var(--bk-ink3); word-break: break-all; }

    @media (prefers-reduced-motion: no-preference) {
        .bridge-kyc-page .bk-card, .bridge-kyc-page .bk-tile { animation: bk-rise 0.3s ease; }
        @keyframes bk-rise { from { opacity: 0; transform: translateY(5px); } }
    }
`;

frappe.pages["bridge-kyc"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Bridge KYC",
		single_column: true,
	});

	const allowed =
		frappe.session.user === "Administrator" ||
		BK_VIEW_ROLES.some((r) => frappe.user_roles.includes(r));
	if (!allowed) {
		page.main.html(`
            <div class="text-center mt-5">
                <div class="alert alert-warning">
                    <h4>Access Denied</h4>
                    <p>This page requires an admin role (Accounts Manager, Flash Admin or System Manager).</p>
                </div>
            </div>
        `);
		return;
	}

	wrapper.bridge_kyc = new BridgeKyc(page);
};

class BridgeKyc {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.filter = "all";
		this.query = "";
		this.render_shell();
		this.load();
	}

	render_shell() {
		this.page.main.html(`
            <style>${BK_CSS}</style>
            <div class="bridge-kyc-page">
                <div class="bk-toolbar">
                    <button class="bk-btn" data-act="refresh">Refresh</button>
                    <span class="bk-meta" id="bk-meta">Loading live status from Bridge…</span>
                    <span class="bk-spacer"></span>
                    <input class="bk-search" id="bk-search" type="search"
                        placeholder="Filter by name, email, username…" />
                </div>
                <div class="bk-tiles" id="bk-tiles" style="display:none;"></div>
                <div class="bk-card"><div id="bk-table"></div></div>
            </div>
        `);
		this.page.main.find('[data-act="refresh"]').on("click", () => this.load());
		this.page.main.find("#bk-search").on("input", (e) => {
			this.query = String(e.currentTarget.value || "")
				.trim()
				.toLowerCase();
			this.render_table();
		});
	}

	load() {
		const meta = this.page.main.find("#bk-meta");
		const btn = this.page.main.find('[data-act="refresh"]');
		meta.removeClass("err").text("Loading live status from Bridge…");
		btn.prop("disabled", true);
		frappe.call({
			method: "admin_panel.api.bridge_kyc.get_kyc_overview",
			callback: (res) => {
				btn.prop("disabled", false);
				const d = res.message;
				if (!d || d.success === false) {
					meta.addClass("err").text(
						(d && d.error) || "Could not load Bridge KYC status."
					);
					return;
				}
				this.data = d;
				meta.text(`Live from Bridge · ${d.now} · ${d.summary.total} customers`);
				this.render_tiles();
				this.render_table();
			},
			error: () => {
				btn.prop("disabled", false);
				meta.addClass("err").text("Could not load Bridge KYC status.");
			},
		});
	}

	render_tiles() {
		const s = this.data.summary;
		const tiles = [
			{
				key: "all",
				label: "All customers",
				value: s.total,
				sub: `${s.unlinked} not linked to a Flash account`,
			},
			{ key: "approved", label: "Approved", value: s.buckets.approved, tone: "ok" },
			{
				key: "in_progress",
				label: "In progress",
				value: s.buckets.in_progress,
				tone: "warn",
			},
			{ key: "not_started", label: "Not started", value: s.buckets.not_started },
			{
				key: "attention",
				label: "Needs attention",
				value: s.buckets.attention,
				tone: s.buckets.attention ? "bad" : "",
			},
		];
		this.page.main
			.find("#bk-tiles")
			.html(
				tiles
					.map(
						(t) => `
                <div class="bk-tile" role="button" tabindex="0" data-bucket="${t.key}"
                    aria-pressed="${this.filter === t.key}">
                    <div class="bk-tile-label">${bkEsc(t.label)}</div>
                    <div class="bk-tile-value ${t.tone || ""}">${bkEsc(t.value)}</div>
                    ${t.sub ? `<div class="bk-tile-sub">${bkEsc(t.sub)}</div>` : ""}
                </div>`
					)
					.join("")
			)
			.show();
		this.page.main.find(".bk-tile").on("click keydown", (e) => {
			if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
			e.preventDefault();
			this.filter = $(e.currentTarget).data("bucket");
			this.render_tiles();
			this.render_table();
		});
	}

	filtered_rows() {
		let rows = this.data.rows;
		if (this.filter !== "all") {
			rows = rows.filter((r) => r.bucket === this.filter);
		}
		if (this.query) {
			rows = rows.filter((r) =>
				[r.name, r.email, r.customer_id, r.status, ...(r.usernames || [])]
					.filter(Boolean)
					.some((v) => String(v).toLowerCase().includes(this.query))
			);
		}
		return rows;
	}

	render_table() {
		const rows = this.filtered_rows();
		if (!rows.length) {
			this.page.main.find("#bk-table").html(
				`<div class="bk-empty">No customers match
                    ${this.filter === "all" ? "" : ` "${bkEsc(BK_BUCKET_LABELS[this.filter])}"`}
                    ${this.query ? ` · "${bkEsc(this.query)}"` : ""}.</div>`
			);
			return;
		}
		const now = this.data.now;
		const body = rows
			.map((r) => {
				const tone = BK_STATUS_TONES[r.bucket] || "muted";
				const shared =
					r.usernames && r.usernames.length > 1
						? ` <span class="bk-chip bad" title="${bkEsc(
								r.usernames.join(", ")
						  )}">shared by ${r.usernames.length} accounts</span>`
						: "";
				const flash = r.linked
					? `<span class="bk-chip user">${bkEsc(
							r.username || "(no username)"
					  )}</span>${shared}`
					: '<span class="bk-chip muted">not linked</span>';
				const missing = r.missing_count
					? `<span class="bk-chip warn">${r.missing_count} missing</span>`
					: r.status === "active"
					? '<span class="bk-chip ok">complete</span>'
					: "—";
				return `
                <tr class="bk-row" data-customer="${bkEsc(r.customer_id)}" data-status="${bkEsc(
					r.status
				)}">
                    <td>
                        <div class="bk-row-name">${bkEsc(r.name || "(no name at Bridge)")}</div>
                        <div class="bk-row-email">${bkEsc(r.email || "")}</div>
                    </td>
                    <td>${flash}</td>
                    <td>${bkEsc(r.type || "—")}</td>
                    <td><span class="bk-chip ${tone}">${bkEsc(bkLabel(r.status))}</span></td>
                    <td>${missing}</td>
                    <td title="${bkEsc(r.updated_at || "")}">${bkEsc(
					bkAgo(r.updated_at, now)
				)}</td>
                    <td title="${bkEsc(r.created_at || "")}">${bkEsc(
					(r.created_at || "—").slice(0, 10)
				)}</td>
                </tr>
                <tr class="bk-detail" data-detail="${bkEsc(r.customer_id)}" style="display:none;">
                    <td colspan="7"></td>
                </tr>`;
			})
			.join("");
		this.page.main.find("#bk-table").html(`
            <table class="bk-table">
                <thead><tr>
                    <th>Customer</th><th>Flash account</th><th>Type</th><th>Status</th>
                    <th>Requirements</th><th>Last activity</th><th>Created</th>
                </tr></thead>
                <tbody>${body}</tbody>
            </table>
        `);
		this.page.main.find(".bk-row").on("click", (e) => {
			const row = $(e.currentTarget);
			this.toggle_detail(row.data("customer"), row.data("status"));
		});
	}

	toggle_detail(customerId, status) {
		const box = this.page.main.find(`[data-detail="${customerId}"]`);
		if (box.is(":visible")) {
			box.hide();
			return;
		}
		this.page.main.find(".bk-detail").hide();
		if (status === "missing_at_bridge") {
			box.find("td").html(
				`<div class="bk-detail-empty">The linked Bridge customer
                <span class="bk-detail-id">${bkEsc(customerId)}</span> no longer exists at Bridge.
                The account needs to be re-linked (or the customer re-created) before topup/settle
                will work — this is the "KYC modal came back" failure mode.</div>`
			);
			box.show();
			return;
		}
		box.find("td").html('<div class="bk-detail-empty">Loading live detail…</div>');
		box.show();
		frappe.call({
			method: "admin_panel.api.bridge_kyc.get_kyc_customer",
			args: { customer_id: customerId },
			callback: (res) => {
				const d = res.message;
				if (!d || d.success === false || !d.customer) {
					box.find("td").html(
						`<div class="bk-detail-empty">${bkEsc(
							(d && d.error) || "Could not load customer detail."
						)}</div>`
					);
					return;
				}
				const overviewRow = (this.data.rows || []).find(
					(r) => r.customer_id === customerId
				);
				box.find("td").html(this.detail_html(d.customer, overviewRow));
			},
			error: () =>
				box
					.find("td")
					.html('<div class="bk-detail-empty">Could not load customer detail.</div>'),
		});
	}

	detail_html(c, overviewRow) {
		const list = (items, cls) =>
			items && items.length
				? `<ul>${items
						.map((i) => `<li class="${cls || ""}">${bkEsc(bkLabel(i))}</li>`)
						.join("")}</ul>`
				: '<div class="bk-detail-empty">None</div>';
		const endorsements = (c.endorsements || [])
			.map((e) => {
				const tone =
					e.status === "approved" ? "ok" : e.status === "incomplete" ? "warn" : "muted";
				return `
                <div class="bk-detail-block">
                    <div class="bk-detail-title">Endorsement: ${bkEsc(e.name || "?")}
                        <span class="bk-chip ${tone}">${bkEsc(bkLabel(e.status || "?"))}</span>
                    </div>
                    <div class="bk-detail-empty">${e.complete_count} items complete</div>
                    ${list(e.missing, "")}
                    ${e.issues && e.issues.length ? list(e.issues, "bk-issue") : ""}
                </div>`;
			})
			.join("");
		const usernames = (overviewRow && overviewRow.usernames) || [];
		const flashBlock = `
                <div class="bk-detail-block">
                    <div class="bk-detail-title">Linked Flash account${
						usernames.length > 1 ? "s" : ""
					}
                        ${
							usernames.length > 1
								? '<span class="bk-chip bad">shared link</span>'
								: ""
						}
                    </div>
                    ${
						usernames.length
							? `<ul>${usernames.map((u) => `<li>${bkEsc(u)}</li>`).join("")}</ul>`
							: '<div class="bk-detail-empty">Not linked to a Flash account</div>'
					}
                </div>`;
		return `
            <div class="bk-detail-grid">
                ${flashBlock}
                <div class="bk-detail-block">
                    <div class="bk-detail-title">Missing (all endorsements)</div>
                    ${list(c.missing, "")}
                </div>
                <div class="bk-detail-block">
                    <div class="bk-detail-title">Issues / rejections</div>
                    ${list(c.issues, "bk-issue")}
                    ${
						c.rejection_reasons && c.rejection_reasons.length
							? list(c.rejection_reasons, "bk-reject")
							: ""
					}
                </div>
                <div class="bk-detail-block">
                    <div class="bk-detail-title">Also due (non-KYC)</div>
                    ${list(c.requirements_due, "")}
                    <div class="bk-detail-title" style="margin-top:8px;">Bridge customer id</div>
                    <div class="bk-detail-id">${bkEsc(c.customer_id)}</div>
                </div>
                ${endorsements}
            </div>
        `;
	}
}

frappe.pages["account-hub"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Account Hub",
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

	wrapper.account_hub = new AccountHub(page);
};

frappe.pages["account-hub"].on_page_show = function (wrapper) {
	if (wrapper.account_hub) {
		wrapper.account_hub.handle_route_options();
	}
};

/* ─────────────────────────────────────────────
   Helpers
   ───────────────────────────────────────────── */
function debounce(func, wait) {
	let timeout;
	return function executedFunction(...args) {
		const later = () => {
			clearTimeout(timeout);
			func(...args);
		};
		clearTimeout(timeout);
		timeout = setTimeout(later, wait);
	};
}

const ACCOUNT_LEVELS = {
	ZERO: "ZERO",
	ONE: "ONE",
	TWO: "TWO",
	THREE: "THREE",
};

const ACCOUNT_STATUSES = {
	NEW: "NEW",
	PENDING: "PENDING",
	ACTIVE: "ACTIVE",
	LOCKED: "LOCKED",
	CLOSED: "CLOSED",
};

// ENG-516 nomenclature: Pro and International are retired, Merchant is now
// Business, and levels are internal. The account leads with one headline word
// (Trial → Verified → Business, the "light headline status" decision) with
// capability badges as supporting detail. L1 and L2 both read "Verified" —
// bank payout is a badge, not a tier.
const ACCOUNT_LEVEL_LABELS = {
	[ACCOUNT_LEVELS.ZERO]: "Trial",
	[ACCOUNT_LEVELS.ONE]: "Verified",
	[ACCOUNT_LEVELS.TWO]: "Verified",
	[ACCOUNT_LEVELS.THREE]: "Business",
};

// On an upgrade request, requested_level reads as the capability being
// requested, not a tier the user picked.
const REQUESTED_LEVEL_LABELS = {
	[ACCOUNT_LEVELS.ZERO]: "Trial",
	[ACCOUNT_LEVELS.ONE]: "Verified",
	[ACCOUNT_LEVELS.TWO]: "Bank payout",
	[ACCOUNT_LEVELS.THREE]: "Business",
};

const STATUS_HEADLINE_LABELS = {
	TRIAL: "Trial",
	VERIFIED: "Verified",
	BUSINESS: "Business",
};

const STATUS_HEADLINE_BADGES = {
	TRIAL: "badge-trial",
	VERIFIED: "badge-personal",
	BUSINESS: "badge-merchant",
};

// Internal levels for the admin change-level action — disambiguated with the
// level number because L1 and L2 share the "Verified" headline.
const ADMIN_LEVEL_OPTIONS = {
	[ACCOUNT_LEVELS.ZERO]: "Trial (L0)",
	[ACCOUNT_LEVELS.ONE]: "Verified (L1)",
	[ACCOUNT_LEVELS.TWO]: "Verified + Bank payout (L2)",
	[ACCOUNT_LEVELS.THREE]: "Business (L3)",
};

const ACCOUNT_LEVEL_BADGES = {
	[ACCOUNT_LEVELS.ZERO]: "badge-trial",
	[ACCOUNT_LEVELS.ONE]: "badge-personal",
	[ACCOUNT_LEVELS.TWO]: "badge-business",
	[ACCOUNT_LEVELS.THREE]: "badge-merchant",
};

const ACCOUNT_STATUS_LABELS = {
	[ACCOUNT_STATUSES.NEW]: "New",
	[ACCOUNT_STATUSES.PENDING]: "Pending",
	[ACCOUNT_STATUSES.ACTIVE]: "Active",
	[ACCOUNT_STATUSES.LOCKED]: "Locked",
	[ACCOUNT_STATUSES.CLOSED]: "Closed",
};

const ACCOUNT_STATUS_BADGES = {
	[ACCOUNT_STATUSES.NEW]: "badge-pending",
	[ACCOUNT_STATUSES.PENDING]: "badge-pending",
	[ACCOUNT_STATUSES.ACTIVE]: "badge-approved",
	[ACCOUNT_STATUSES.LOCKED]: "badge-rejected",
	[ACCOUNT_STATUSES.CLOSED]: "badge-closed",
};

function getLevelLabel(level) {
	return ACCOUNT_LEVEL_LABELS[level] || level;
}

function getRequestedLevelLabel(level) {
	return REQUESTED_LEVEL_LABELS[level] || level;
}

// Headline status straight from the backend when available (ENG-516);
// falls back to the stored level for older backends.
function getHeadlineLabel(account) {
	if (account.statusHeadline) {
		return STATUS_HEADLINE_LABELS[account.statusHeadline] || account.statusHeadline;
	}
	return getLevelLabel(account.level);
}

function getHeadlineBadge(account) {
	if (account.statusHeadline) {
		return STATUS_HEADLINE_BADGES[account.statusHeadline] || "badge-trial";
	}
	return getLevelBadge(account.level);
}

// Supporting capability badges next to the headline. verified/business are
// already the headline; bankPayout and usdAccount are the orthogonal extras.
function capabilityBadgesHtml(capabilities) {
	if (!capabilities) return "";
	const badges = [];
	if (capabilities.bankPayout) badges.push("Bank payout");
	if (capabilities.usdAccount) badges.push("USD account");
	return badges.map((b) => `<span class="ah-badge badge-capability">${b}</span>`).join(" ");
}

const RESULT_STATUS_TONE = {
	// account statuses (UPPERCASE) — account search results
	[ACCOUNT_STATUSES.ACTIVE]: "ok",
	[ACCOUNT_STATUSES.NEW]: "warn",
	[ACCOUNT_STATUSES.PENDING]: "warn",
	[ACCOUNT_STATUSES.LOCKED]: "bad",
	[ACCOUNT_STATUSES.CLOSED]: "off",
	// upgrade-request statuses arrive Title Case from the doctype; the
	// lookup uppercases, so only the two extra vocabulary words go here
	APPROVED: "ok",
	REJECTED: "bad",
};

function statusDotHtml(status) {
	const tone = RESULT_STATUS_TONE[String(status || "").toUpperCase()];
	return tone ? `<span class="ah-dot ah-dot-${tone}"></span>` : "";
}

function getLevelBadge(level) {
	return ACCOUNT_LEVEL_BADGES[level] || "badge-trial";
}

function getStatusLabel(status) {
	return ACCOUNT_STATUS_LABELS[status] || status;
}

function getStatusBadge(status) {
	return ACCOUNT_STATUS_BADGES[status] || "badge-pending";
}

function formatPhone(phone) {
	if (!phone) return "-";
	return phone.replace(/^\+?(\d{1})(\d{3})(\d{3})(\d{4})$/, "+$1 $2 $3 $4");
}

function formatDate(ts) {
	if (!ts) return "-";
	const d = new Date(ts * 1000);
	return (
		frappe.datetime.global_date_format(d.toISOString().split("T")[0]) +
		" " +
		d.toLocaleTimeString()
	);
}

function formatDateOnly(ts) {
	if (!ts) return "-";
	const d = new Date(ts * 1000);
	return frappe.datetime.global_date_format(d.toISOString().split("T")[0]);
}

function formatCurrency(cents, currency) {
	if (cents == null) return "-";
	const sym = currency === "USD" ? "$" : currency === "USDT" ? "₮" : "$";
	return sym + (cents / 100).toFixed(2);
}

function formatApiErrors(errors) {
	// Flash GraphQL mutations return validation failures as an array of
	// { message } objects, not strings. String()-ing them (e.g. via
	// Array.join) renders "[object Object]" — pull the message out of each.
	if (!errors) return "";
	const list = Array.isArray(errors) ? errors : [errors];
	return list
		.map((e) => {
			if (typeof e === "string") return e;
			if (e && typeof e === "object") return e.message || e.error || JSON.stringify(e);
			return e == null ? "" : String(e);
		})
		.filter(Boolean)
		.join(", ");
}

/* ─────────────────────────────────────────────
   AccountHub Class
   ───────────────────────────────────────────── */
class AccountHub {
	constructor(page) {
		this.page = page;
		this.current_account = null;
		this.default_results = [];
		this.default_list_loaded = false;
		this.pending_route_query = null;
		this.$ = {};
		this.setup_page();
	}

	/* ── Page Setup ────────────────────────────────── */
	setup_page() {
		this.create_layout();
		this.cache_elements();
		this.bind_events();
		this.load_default_list();
	}

	create_layout() {
		this.page.main.html(`
            <style>
                /* ═══ Ops-pulse design system — Account Hub (customer workbench) ═══
                   Same tokens as the dashboard/census; legacy --color-* names are
                   aliased so dynamic templates restyle without markup changes. */
                .account-hub {
                    --ah-surface: var(--card-bg, #ffffff); --ah-ink: var(--text-color, #1a2420);
                    --ah-ink2: var(--text-muted, #5c6b65); --ah-ink3: var(--text-light, #8fa098);
                    --ah-line: var(--border-color, #e2e8e5); --ah-line-soft: var(--subtle-fg, #ecf1ee);
                    --ah-accent: #007856; --ah-accent-ink: #007856; --ah-accent-soft: #e6f3ee;
                    --ah-good: #0ca30c; --ah-warn: #b87d00; --ah-warn-bg: #fff3d6;
                    --ah-serious: #c05a32; --ah-serious-bg: #fdeae2;
                    --ah-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
                    /* legacy aliases (dynamic templates reference these inline) */
                    --color-primary: var(--ah-accent); --color-background: transparent;
                    --color-layer: var(--ah-surface); --color-text01: var(--ah-ink);
                    --color-text02: var(--ah-ink2); --color-border01: var(--ah-line);
                    --color-green: var(--ah-good); --color-error: var(--ah-serious);
                    --color-warning: var(--ah-warn);
                    max-width: 1400px; margin: 0 auto;
                }
                [data-theme="dark"] .account-hub, .dark .account-hub {
                    --ah-accent: #1e9e75; --ah-accent-ink: #4cc29e; --ah-accent-soft: #12352a;
                    --ah-good: #35c135; --ah-warn: #fab219; --ah-warn-bg: #33290d;
                    --ah-serious: #ec835a; --ah-serious-bg: #38211a;
                    --ah-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25);
                }

                /* layout */
                .ah-container { display: flex; gap: 16px; align-items: flex-start; }
                .ah-left-panel { width: 320px; min-width: 280px; flex-shrink: 0;
                    position: sticky; top: calc(var(--navbar-height, 60px) + 12px); }
                .ah-right-panel { flex: 1; min-width: 0; }
                @media (max-width: 900px) {
                    .ah-container { flex-direction: column; }
                    .ah-left-panel { width: 100%; position: static; }
                }

                .ah-card { background: var(--ah-surface); border: 1px solid var(--ah-line);
                    border-radius: 14px; box-shadow: var(--ah-shadow); overflow: hidden; }
                .ah-card-header { padding: 13px 18px; border-bottom: 1px solid var(--ah-line);
                    font-size: 13.5px; font-weight: 650; color: var(--ah-ink);
                    display: flex; align-items: center; }
                .ah-card-header .fa { color: var(--ah-accent-ink); }

                /* search rail */
                .ah-search-wrapper { padding: 14px 16px 10px; }
                .ah-search-input { width: 100%; padding: 9px 13px; border: 1px solid var(--ah-line);
                    border-radius: 10px; font-size: 13.5px; background: var(--ah-surface);
                    color: var(--ah-ink); box-sizing: border-box; transition: border-color 0.15s; }
                .ah-search-input:focus { outline: 2px solid var(--ah-accent); outline-offset: 1px;
                    border-color: var(--ah-accent); }
                .ah-search-input::placeholder { color: var(--ah-ink3); }
                .ah-search-hint { padding: 0 2px; }
                .ah-results-area { border-top: 1px solid var(--ah-line-soft); min-height: 90px;
                    max-height: calc(100vh - 260px); overflow-y: auto; }

                .ah-result-item { display: flex; align-items: center; gap: 11px;
                    padding: 11px 16px; cursor: pointer; border-left: 3px solid transparent;
                    border-bottom: 1px solid var(--ah-line-soft); transition: background 0.12s; }
                .ah-result-item:last-child { border-bottom: none; }
                .ah-result-item:hover { background: var(--ah-line-soft); }
                .ah-result-item.active { background: var(--ah-accent-soft);
                    border-left-color: var(--ah-accent); }
                .ah-result-avatar { position: relative; width: 34px; height: 34px; border-radius: 50%;
                    background: var(--ah-accent-soft); color: var(--ah-accent-ink);
                    display: grid; place-items: center; font-weight: 700; font-size: 14px; flex: none; }
                .ah-result-info { min-width: 0; flex: 1; }
                .ah-result-name { font-weight: 600; font-size: 13px; color: var(--ah-ink);
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                .ah-result-sub { color: var(--ah-ink2); font-size: 11.5px;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

                .ah-loading { text-align: center; padding: 26px 0; }
                .ah-spinner { width: 22px; height: 22px; border: 2px solid var(--ah-line);
                    border-top-color: var(--ah-accent); border-radius: 50%;
                    margin: 0 auto 8px; animation: ah-spin 0.8s linear infinite; }
                @keyframes ah-spin { to { transform: rotate(360deg); } }
                .ah-dot { position: absolute; right: -1px; bottom: -1px; width: 9px; height: 9px;
                    border-radius: 50%; box-shadow: 0 0 0 2px var(--ah-surface); }
                .ah-dot-ok { background: var(--ah-good); }
                .ah-dot-warn { background: var(--ah-warn); }
                .ah-dot-bad { background: var(--ah-serious); }
                .ah-dot-off { background: var(--ah-ink3); }
                .ah-error-msg { margin: 12px 16px; padding: 10px 14px; border-radius: 10px;
                    background: var(--ah-serious-bg); color: var(--ah-serious);
                    font-size: 12.5px; font-weight: 600; }
                .ah-empty, .ah-right-empty { text-align: center; padding: 34px 20px; }
                .ah-empty-icon, .ah-right-empty-icon { font-size: 26px; margin-bottom: 8px;
                    filter: grayscale(0.4); opacity: 0.75; }
                .ah-empty-text, .ah-right-empty-text { font-weight: 650; font-size: 13.5px;
                    color: var(--ah-ink); }
                .ah-empty-sub, .ah-right-empty-sub { color: var(--ah-ink3); font-size: 12px;
                    margin-top: 4px; max-width: 340px; margin-left: auto; margin-right: auto; }
                .ah-right-empty { padding: 90px 20px; }

                /* identity band — who + what they hold, above the tabs */
                .ah-ident { padding: 14px 20px 13px; border-bottom: 1px solid var(--ah-line); }
                .ah-ident-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
                .ah-ident-name { font-size: 18px; font-weight: 650; letter-spacing: -0.01em; }
                .ah-ident-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
                .ah-ident-meta { color: var(--ah-ink2); font-size: 12.5px; margin-top: 4px;
                    display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
                .ah-ident-dot { color: var(--ah-ink3); }
                .ah-ident-balances { display: flex; gap: 8px; margin-top: 11px; flex-wrap: wrap; }
                .ah-bal-chip { display: inline-flex; align-items: baseline; gap: 7px;
                    border: 1px solid var(--ah-line); border-radius: 10px; padding: 5px 12px;
                    background: var(--ah-surface); }
                .ah-bal-cur { font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
                    color: var(--ah-ink2); font-weight: 650; }
                .ah-bal-amt { font-size: 15px; font-weight: 650; color: var(--ah-ink);
                    font-variant-numeric: tabular-nums; }

                /* tabs — underline style */
                .ah-tabs { display: flex; gap: 2px; padding: 0 14px; border-bottom: 1px solid var(--ah-line);
                    overflow-x: auto; }
                .ah-tab { border: none; background: transparent; color: var(--ah-ink2);
                    font-size: 12.5px; font-weight: 600; padding: 10px 12px 9px; cursor: pointer;
                    border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap;
                    transition: color 0.12s; }
                .ah-tab:hover { color: var(--ah-ink); }
                .ah-tab.active { color: var(--ah-accent-ink); border-bottom-color: var(--ah-accent); }
                .ah-tab:focus-visible { outline: 2px solid var(--ah-accent); outline-offset: -2px; }
                .ah-tab-content { display: none; padding: 18px 20px 20px; }
                .ah-tab-content.active { display: block; }

                /* overview kv cards */
                .ah-info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                    gap: 12px; margin-bottom: 16px; }
                .ah-info-card { background: var(--ah-surface); border: 1px solid var(--ah-line);
                    border-radius: 12px; padding: 14px 16px; }
                .ah-info-card h6 { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
                    color: var(--ah-ink2); font-weight: 650; margin: 0 0 10px; }
                .ah-info-card h6 .fa { display: none; }
                .ah-info-row { display: flex; justify-content: space-between; gap: 12px;
                    padding: 5px 0; align-items: baseline; }
                .ah-info-row + .ah-info-row { border-top: 1px solid var(--ah-line-soft); }
                .ah-info-label { font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase;
                    color: var(--ah-ink2); font-weight: 600; flex: none; }
                .ah-info-value { font-size: 13px; font-weight: 600; color: var(--ah-ink);
                    text-align: right; word-break: break-word; min-width: 0; }


                .ah-btn { border: 1px solid var(--ah-line); background: var(--ah-surface);
                    color: var(--ah-ink); border-radius: 9px; padding: 7px 14px; font-size: 13px;
                    font-weight: 600; cursor: pointer; transition: all 0.13s; }
                .ah-btn:hover { border-color: var(--ah-accent); }
                .ah-btn:focus-visible { outline: 2px solid var(--ah-accent); outline-offset: 1px; }
                .ah-btn .fa { margin-right: 5px; }
                .ah-btn-primary { background: var(--ah-accent); border-color: var(--ah-accent); color: #fff; }
                .ah-btn-primary:hover { filter: brightness(1.07); }
                .ah-btn-secondary { background: var(--ah-surface); }
                .ah-btn-success { color: var(--ah-good); border-color: var(--ah-good); background: transparent; }
                .ah-btn-success:hover { background: var(--ah-accent-soft); }
                .ah-btn-danger { color: var(--ah-serious); border-color: var(--ah-serious); background: transparent; }
                .ah-btn-danger:hover { background: var(--ah-serious-bg); border-color: var(--ah-serious); }
                .ah-btn-sm { padding: 4px 10px; font-size: 12px; }
                .ah-btn:disabled { opacity: 0.55; cursor: not-allowed; }

                /* chips — level tiers express intensity of one accent; status is semantic */
                .ah-badge { display: inline-flex; align-items: center; border-radius: 999px;
                    padding: 3px 11px; font-size: 11.5px; font-weight: 650; letter-spacing: 0.02em;
                    background: var(--ah-line-soft); color: var(--ah-ink2); }
                .badge-trial { background: var(--ah-line-soft); color: var(--ah-ink2); }
                .badge-personal { background: var(--ah-accent-soft); color: var(--ah-accent-ink); opacity: 0.85; }
                .badge-business { background: var(--ah-accent-soft); color: var(--ah-accent-ink); }
                .badge-merchant { background: var(--ah-accent); color: #fff; }
                .badge-capability { background: var(--ah-line-soft); color: var(--ah-ink2); }
                .badge-pending { background: var(--ah-warn-bg); color: var(--ah-warn); }
                .badge-approved { background: var(--ah-accent-soft); color: var(--ah-accent-ink); }
                .badge-rejected { background: var(--ah-serious-bg); color: var(--ah-serious); }
                .badge-closed { background: var(--ah-line-soft); color: var(--ah-ink3); }
                .ah-verified-badge { display: inline-flex; align-items: center; border-radius: 999px;
                    padding: 2px 9px; font-size: 11px; font-weight: 650;
                    background: var(--ah-accent-soft); color: var(--ah-accent-ink); margin-left: 6px; }

                /* wallets */
                .ah-wallet-card { background: var(--ah-surface); border: 1px solid var(--ah-line);
                    border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; }
                .ah-wallet-currency-badge { display: inline-flex; border-radius: 999px;
                    padding: 3px 11px; font-size: 11.5px; font-weight: 650;
                    background: var(--ah-accent-soft); color: var(--ah-accent-ink); }
                .ah-wallet-balance { font-size: 20px; font-weight: 650; color: var(--ah-ink);
                    font-variant-numeric: tabular-nums; }
                .ah-wallet-row { display: flex; justify-content: space-between; gap: 12px;
                    padding: 4px 0; align-items: baseline; }

                /* documents */
                .ah-doc-item { display: flex; align-items: center; justify-content: space-between;
                    gap: 12px; background: var(--ah-surface); border: 1px solid var(--ah-line);
                    border-radius: 12px; padding: 12px 16px; margin-bottom: 10px; }
                .ah-doc-info { min-width: 0; flex: 1; font-size: 13px; color: var(--ah-ink); }

                /* merchant */
                .ah-merchant-card { background: var(--ah-surface); border: 1px solid var(--ah-line);
                    border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; }
                .ah-merchant-title { font-weight: 650; font-size: 14px; color: var(--ah-ink);
                    margin-bottom: 8px; }
                .ah-merchant-row { display: flex; justify-content: space-between; gap: 12px;
                    padding: 4px 0; font-size: 13px; align-items: baseline; }
                .ah-merchant-actions { display: flex; gap: 8px; margin-top: 10px; }

                /* upgrade history table */
                .ah-table { width: 100%; border-collapse: collapse; font-size: 13px; }
                .ah-table th { text-align: left; font-size: 11px; letter-spacing: 0.05em;
                    text-transform: uppercase; color: var(--ah-ink2); font-weight: 650;
                    padding: 9px 12px; border-bottom: 1px solid var(--ah-line); }
                .ah-table td { padding: 9px 12px; border-bottom: 1px solid var(--ah-line-soft);
                    color: var(--ah-ink); font-variant-numeric: tabular-nums; }
                .ah-table tr:last-child td { border-bottom: none; }

                @media (prefers-reduced-motion: no-preference) {
                    .ah-detail-content, .ah-result-item { animation: ah-rise 0.3s ease; }
                    @keyframes ah-rise { from { opacity: 0; transform: translateY(5px); } }
                }
            </style>

            <div class="account-hub m-3">
                <div class="ah-container">
                    <!-- Left Panel: Search + Results -->
                    <div class="ah-left-panel">
                        <div class="ah-card">
                            <div class="ah-card-header">
                                <i class="fa fa-search" style="margin-right: 8px;"></i>
                                Search Account
                            </div>
                            <div class="ah-search-wrapper">
                                <input type="text" class="ah-search-input search-input" placeholder="Search by phone (+1...), email, username, or account ID">
                                <div class="ah-search-hint" style="font-size:11px;color:var(--color-text02);margin-top:6px;">
                                    <i class="fa fa-info-circle"></i> Press Enter or pause to search
                                </div>
                            </div>
                            <div class="ah-results-area">
                                <div class="ah-loading search-loading" style="display:none;">
                                    <div class="ah-spinner"></div>
                                    <p style="color:var(--color-text02);font-size:14px;">Searching...</p>
                                </div>
                                <div class="ah-error-msg search-error" style="display:none;">
                                    <i class="fa fa-exclamation-circle"></i>
                                    <span class="error-text"></span>
                                </div>
                                <div class="search-results-list">
                                    <!-- Populated dynamically -->
                                </div>
                                <div class="ah-empty search-empty" style="display:none;">
                                    <div class="ah-empty-icon">🔍</div>
                                    <div class="ah-empty-text">No accounts found</div>
                                    <div class="ah-empty-sub">Recent upgrade requests will appear here. Use the search bar to find specific accounts.</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Right Panel: Detail View -->
                    <div class="ah-right-panel">
                        <div class="ah-card">
                            <!-- Empty State (shown when no account selected) -->
                            <div class="ah-right-empty right-empty-state">
                                <div class="ah-right-empty-icon">👤</div>
                                <div class="ah-right-empty-text">No account selected</div>
                                <div class="ah-right-empty-sub">Search for an account on the left to view details</div>
                            </div>

                            <!-- Detail Content (shown when account is selected) -->
                            <div class="ah-detail-content" style="display:none;">
                                <div class="ah-ident">
                                    <div class="ah-ident-top">
                                        <span class="detail-username-display ah-ident-name"></span>
                                        <span class="ah-badge detail-level-badge"></span>
                                        <span class="detail-cap-badges"></span>
                                        <span class="ah-badge detail-status-badge"></span>
                                        <div class="ah-ident-actions">
                                            <button class="ah-btn ah-btn-sm ah-btn-primary btn-change-level">
                                                <i class="fa fa-level-up"></i> Change Level
                                            </button>
                                            <button class="ah-btn ah-btn-sm ah-btn-secondary btn-update-phone">
                                                <i class="fa fa-phone"></i> Update Phone
                                            </button>
                                            <button class="ah-btn ah-btn-sm ah-btn-success btn-activate-account" style="display:none;">
                                                <i class="fa fa-unlock"></i> Activate
                                            </button>
                                            <button class="ah-btn ah-btn-sm ah-btn-danger btn-lock-account" style="display:none;">
                                                <i class="fa fa-lock"></i> Lock
                                            </button>
                                        </div>
                                    </div>
                                    <div class="ah-ident-meta detail-ident-meta"></div>
                                    <div class="ah-ident-balances detail-ident-balances"></div>
                                </div>

                                <!-- Tabs -->
                                <div class="ah-tabs">
                                    <button class="ah-tab active" data-tab="overview">Overview</button>
                                    <button class="ah-tab" data-tab="banking">Banking</button>
                                    <button class="ah-tab" data-tab="wallets">Wallets</button>
                                    <button class="ah-tab" data-tab="documents">Documents</button>
                                    <button class="ah-tab" data-tab="merchant">Business</button>
                                    <button class="ah-tab" data-tab="upgrade">Upgrade History</button>
                                </div>

                                <!-- Tab: Overview -->
                                <div class="ah-tab-content active" data-tab="overview">
                                    <div class="ah-info-grid">
                                        <!-- Identity Card -->
                                        <div class="ah-info-card">
                                            <h6><i class="fa fa-id-card" style="margin-right:6px;color:var(--color-primary);"></i> Identity</h6>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Phone</span>
                                                <span class="ah-info-value detail-ov-phone"></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Email</span>
                                                <span class="ah-info-value detail-ov-email"></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Username</span>
                                                <span class="ah-info-value detail-ov-username"></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">npub</span>
                                                <span class="ah-info-value detail-ov-npub" style="font-size:12px;word-break:break-all;"></span>
                                            </div>
                                        </div>

                                        <!-- Account State Card -->
                                        <div class="ah-info-card">
                                            <h6><i class="fa fa-shield" style="margin-right:6px;color:var(--color-primary);"></i> Account State</h6>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Level</span>
                                                <span class="ah-info-value"><span class="ah-badge detail-ov-level-badge"></span></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Status</span>
                                                <span class="ah-info-value"><span class="ah-badge detail-ov-status-badge"></span></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">ERP Party</span>
                                                <span class="ah-info-value detail-ov-erp-party"></span>
                                            </div>
                                            <div class="ah-info-row">
                                                <span class="ah-info-label">Created</span>
                                                <span class="ah-info-value detail-ov-created"></span>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <!-- Tab: Banking -->
                                <div class="ah-tab-content" data-tab="banking">
                                    <div class="banking-container"></div>
                                </div>

                                <!-- Tab: Wallets -->
                                <div class="ah-tab-content" data-tab="wallets">
                                    <div class="wallets-container"></div>
                                </div>

                                <!-- Tab: Documents -->
                                <div class="ah-tab-content" data-tab="documents">
                                    <div class="documents-container"></div>
                                </div>

                                <!-- Tab: Merchant -->
                                <div class="ah-tab-content" data-tab="merchant">
                                    <div class="merchant-container"></div>
                                </div>

                                <!-- Tab: Upgrade History -->
                                <div class="ah-tab-content" data-tab="upgrade">
                                    <div class="upgrade-container"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `);
	}

	cache_elements() {
		const main = this.page.main;
		this.$ = {
			searchInput: main.find(".search-input"),
			searchLoading: main.find(".search-loading"),
			searchError: main.find(".search-error"),
			searchErrorText: main.find(".search-error .error-text"),
			searchEmpty: main.find(".search-empty"),
			searchResultsList: main.find(".search-results-list"),
			rightEmpty: main.find(".right-empty-state"),
			detailContent: main.find(".ah-detail-content"),
			detailUsername: main.find(".detail-username-display"),
			detailLevelBadge: main.find(".detail-level-badge"),
			detailCapBadges: main.find(".detail-cap-badges"),
			detailStatusBadge: main.find(".detail-status-badge"),
			identMeta: main.find(".detail-ident-meta"),
			identBalances: main.find(".detail-ident-balances"),
			tabs: main.find(".ah-tab"),
			tabContents: main.find(".ah-tab-content"),
			// Overview
			ovPhone: main.find(".detail-ov-phone"),
			ovEmail: main.find(".detail-ov-email"),
			ovUsername: main.find(".detail-ov-username"),
			ovNpub: main.find(".detail-ov-npub"),
			ovLevelBadge: main.find(".detail-ov-level-badge"),
			ovStatusBadge: main.find(".detail-ov-status-badge"),
			ovErpParty: main.find(".detail-ov-erp-party"),
			ovCreated: main.find(".detail-ov-created"),
			// Action buttons
			btnChangeLevel: main.find(".btn-change-level"),
			btnLockAccount: main.find(".btn-lock-account"),
			btnActivateAccount: main.find(".btn-activate-account"),
			btnUpdatePhone: main.find(".btn-update-phone"),
			// Containers
			bankingContainer: main.find(".banking-container"),
			walletsContainer: main.find(".wallets-container"),
			documentsContainer: main.find(".documents-container"),
			merchantContainer: main.find(".merchant-container"),
			upgradeContainer: main.find(".upgrade-container"),
		};
	}

	bind_events() {
		const main = this.page.main;

		// Search: Enter key — calls API
		this.$.searchInput.on("keypress", (e) => {
			if (e.which === 13) {
				this.perform_search();
			}
		});

		// Search: input — filter local list, debounce API call for longer queries
		const debouncedSearch = debounce(() => {
			const val = this.$.searchInput.val().trim();
			if (val) {
				// Keep fuzzy local results visible while remote exact search runs.
				this.perform_search_with_query(val, false);
			}
		}, 600);

		this.$.searchInput.on("input", () => {
			const val = this.$.searchInput.val().trim();
			// Filter local default list in real-time
			this.filter_local_list(val);
			// Debounce remote search if there's a query
			if (val) {
				debouncedSearch();
			}
		});

		// Tab switching
		this.$.tabs.on("click", function () {
			const tab = $(this).data("tab");
			main.find(".ah-tab").removeClass("active");
			$(this).addClass("active");
			main.find(".ah-tab-content").removeClass("active");
			main.find(`.ah-tab-content[data-tab="${tab}"]`).addClass("active");
		});

		// Action buttons
		this.$.btnChangeLevel.on("click", () => this.change_level());
		this.$.btnLockAccount.on("click", () => this.change_status(ACCOUNT_STATUSES.LOCKED));
		this.$.btnActivateAccount.on("click", () => this.change_status(ACCOUNT_STATUSES.ACTIVE));
		this.$.btnUpdatePhone.on("click", () => this.update_phone());
	}

	/* ── Default User List ────────────────────────────── */

	load_default_list() {
		this.default_list_loaded = false;
		this.$.searchLoading.show();
		this.$.searchError.hide();

		frappe.call({
			method: "admin_panel.api.admin_api.get_upgrade_requests",
			args: { page: 1, page_size: 50 },
			callback: (res) => {
				this.$.searchLoading.hide();
				const result = res.message;
				const requests = (result && result.data) || [];

				if (requests.length === 0) {
					this.$.searchEmpty.show();
					return;
				}

				this.default_results = requests;
				this.default_list_loaded = true;
				this.$.searchEmpty.hide();
				this.render_result_list(requests);
				this.apply_pending_route_query();
			},
			error: () => {
				this.default_list_loaded = true;
				this.$.searchLoading.hide();
				this.$.searchEmpty.show();
				this.apply_pending_route_query();
			},
		});
	}

	render_result_list(items) {
		this.$.searchError.hide();
		this.$.searchResultsList.empty();

		items.forEach((account) => {
			// Use username if available, fallback to phone/email/name
			const displayName =
				account.username ||
				account.phone_number ||
				account.email ||
				account.name ||
				"Unknown";
			const subInfo =
				[account.phone_number, account.email].filter(Boolean).join(" · ") || "—";
			const level = account.requested_level || "ZERO";
			const initial = (displayName || "?")[0].toUpperCase();
			const levelLabel = getRequestedLevelLabel(level);
			const levelBadge = getLevelBadge(level);
			const dotHtml = statusDotHtml(account.status);

			const item = $(`
                <div class="ah-result-item" data-id="${frappe.utils.escape_html(
					account.name
				)}" data-username="${frappe.utils.escape_html(
				account.username || ""
			)}" data-phone="${frappe.utils.escape_html(
				account.phone_number || ""
			)}" data-email="${frappe.utils.escape_html(account.email || "")}">
                    <div class="ah-result-avatar">${initial}${dotHtml}</div>
                    <div class="ah-result-info">
                        <div class="ah-result-name">${frappe.utils.escape_html(displayName)}</div>
                        <div class="ah-result-sub">${frappe.utils.escape_html(subInfo)}</div>
                    </div>
                    <span class="ah-badge ${levelBadge}">${levelLabel}</span>
                </div>
            `);

			item.on("click", () => this.on_result_click(account, item));
			this.$.searchResultsList.append(item);
		});

		if (items.length === 0) {
			this.$.searchEmpty.show();
		}
	}

	filter_local_list(query) {
		if (!query) {
			this.render_result_list(this.default_results);
			return;
		}

		const q = query.toLowerCase();
		const filtered = this.default_results.filter((r) => {
			return (
				(r.username && r.username.toLowerCase().includes(q)) ||
				(r.phone_number && r.phone_number.toLowerCase().includes(q)) ||
				(r.email && r.email.toLowerCase().includes(q)) ||
				(r.name && r.name.toLowerCase().includes(q))
			);
		});

		this.render_result_list(filtered);
	}

	on_result_click(account, itemEl) {
		this.$.searchResultsList.find(".ah-result-item").removeClass("active");
		itemEl.addClass("active");

		// Build a fallback object from local data in case Flash API doesn't have this account
		const fallback = {
			uuid: account.name,
			username: account.username || account.phone_number || account.email || account.name,
			level: account.requested_level || "ZERO",
			status: account.status || "ACTIVE",
			owner: {
				phone: account.phone_number,
				email: { address: account.email, verified: false },
			},
			wallets: [],
			merchants: [],
			createdAt: null,
		};

		if (account.username) {
			this.fetch_account_details(account.username, fallback);
		} else {
			this.show_account(fallback);
		}
	}

	fetch_account_details(username, fallback) {
		/* Fetch full account details without modifying the result list.
           Falls back to local data if the Flash API can't find the account. */
		frappe.call({
			method: "admin_panel.api.admin_api.search_account_smart",
			args: { query: username },
			callback: (res) => {
				const result = res.message;
				if (!result || result.error) {
					if (fallback) {
						this.show_account(fallback);
					}
					return;
				}
				this.show_account(result);
			},
			error: () => {
				if (fallback) {
					this.show_account(fallback);
				}
			},
		});
	}

	/* ── Route Selection ───────────────────────────── */

	consume_route_query() {
		const opts = frappe.route_options || {};
		const query = opts.account_hub_query || opts.account_username || opts.username;
		if (!query) return null;

		delete opts.account_hub_query;
		delete opts.account_username;
		delete opts.username;
		frappe.route_options = Object.keys(opts).length ? opts : null;

		return String(query).trim();
	}

	handle_route_options() {
		const query = this.consume_route_query();
		if (!query) return;

		this.pending_route_query = query;
		this.apply_pending_route_query();
	}

	apply_pending_route_query() {
		if (!this.pending_route_query || !this.default_list_loaded) return;

		const query = this.pending_route_query;
		this.pending_route_query = null;
		this.$.searchInput.val(query);
		this.filter_local_list(query);
		this.perform_search_with_query(query, false);
	}

	/* ── Search ─────────────────────────────────────── */

	perform_search() {
		const query = this.$.searchInput.val().trim();
		if (!query) return;
		this.perform_search_with_query(query, true);
	}

	perform_search_with_query(query, clearLocal) {
		if (!query) return;

		this.$.searchLoading.show();
		this.$.searchError.hide();
		if (clearLocal) {
			this.$.searchResultsList.empty();
		}

		frappe.call({
			method: "admin_panel.api.admin_api.search_account_smart",
			args: { query: query },
			callback: (res) => {
				this.$.searchLoading.hide();
				const result = res.message;
				if (!result || result.error) {
					this.show_search_error(
						result?.error ||
							"Account not found. Try searching by phone (+1...), email, username, or account ID."
					);
					return;
				}
				this.show_search_result(result);
			},
			error: (err) => {
				this.$.searchLoading.hide();
				// Non-2xx responses (404 not-found, 503 upstream) land here, not
				// in callback — surface the server's message when it sent one
				// instead of always blaming the connection.
				const serverMsg =
					(err && typeof err.error === "string" && err.error) ||
					(err &&
						err.responseJSON &&
						typeof err.responseJSON.error === "string" &&
						err.responseJSON.error) ||
					(err &&
						err.message &&
						typeof err.message.error === "string" &&
						err.message.error);
				this.show_search_error(
					serverMsg || "Could not reach the server. Check your connection and try again."
				);
			},
		});
	}

	show_search_error(msg) {
		this.$.searchError.show();
		this.$.searchErrorText.text(msg);
		// Don't clear the search results list — keep the last result visible
	}

	show_search_result(account) {
		this.$.searchError.hide();
		this.$.searchResultsList.empty();
		this.$.searchEmpty.hide();

		const initial = (account.username || "?")[0].toUpperCase();
		const subInfo =
			account.owner?.phone ||
			account.owner?.email?.address ||
			account.username ||
			account.id;
		const levelLabel = getHeadlineLabel(account);
		const levelBadge = getHeadlineBadge(account);

		const item = $(`
            <div class="ah-result-item" data-uuid="${account.uuid}">
                <div class="ah-result-avatar">${initial}${statusDotHtml(account.status)}</div>
                <div class="ah-result-info">
                    <div class="ah-result-name">${frappe.utils.escape_html(
						account.username || "Unknown"
					)}</div>
                    <div class="ah-result-sub">${frappe.utils.escape_html(subInfo)}</div>
                </div>
                <span class="ah-badge ${levelBadge}">${levelLabel}</span>
            </div>
        `);

		item.on("click", () => {
			this.$.searchResultsList.find(".ah-result-item").removeClass("active");
			item.addClass("active");
			this.show_account(account);
		});

		this.$.searchResultsList.append(item);
		item.click(); // Auto-select search result
	}

	/* ── Show Account ────────────────────────────────── */

	show_account(account) {
		this.current_account = account;

		// Switch to detail view
		this.$.rightEmpty.hide();
		this.$.detailContent.show();

		// Update header
		this.$.detailUsername.text(account.username || "Unknown");
		this.$.detailLevelBadge
			.text(getHeadlineLabel(account))
			.attr("class", "ah-badge " + getHeadlineBadge(account));
		this.$.detailCapBadges.html(capabilityBadgesHtml(account.capabilities));
		this.$.detailStatusBadge
			.text(getStatusLabel(account.status))
			.attr("class", "ah-badge " + getStatusBadge(account.status));

		// Identity band: who they are + what they hold, zero clicks in
		const metaBits = [];
		if (account.owner?.phone) metaBits.push(formatPhone(account.owner.phone));
		if (account.owner?.email?.address) metaBits.push(account.owner.email.address);
		if (account.createdAt) metaBits.push("Joined " + formatDateOnly(account.createdAt));
		this.$.identMeta.html(
			metaBits
				.map((bit) => `<span>${frappe.utils.escape_html(bit)}</span>`)
				.join('<span class="ah-ident-dot">\u00b7</span>')
		);
		this.$.identMeta.toggle(metaBits.length > 0);
		const balanceWallets = [...(account.wallets || [])].sort((a, b) => {
			if (a.walletCurrency === "USD") return -1;
			if (b.walletCurrency === "USD") return 1;
			return 0;
		});
		this.$.identBalances.html(
			balanceWallets
				.map(
					(w) =>
						`<span class="ah-bal-chip"><span class="ah-bal-cur">${frappe.utils.escape_html(
							w.walletCurrency || "USD"
						)}</span><span class="ah-bal-amt">${formatCurrency(
							w.balance,
							w.walletCurrency
						)}</span></span>`
				)
				.join("")
		);
		this.$.identBalances.toggle(balanceWallets.length > 0);

		// Activate first tab
		this.$.tabs.removeClass("active");
		this.$.tabs.first().addClass("active");
		this.$.tabContents.removeClass("active");
		this.$.tabContents.first().addClass("active");

		// Populate all tabs
		this.populate_overview(account);
		this.populate_banking(account);
		this.populate_wallets(account);
		this.populate_documents(account);
		this.populate_merchant(account);
		this.populate_upgrade_history(account);
	}

	clear_account() {
		this.current_account = null;
		this.$.detailContent.hide();
		this.$.rightEmpty.show();
		this.$.searchResultsList.find(".ah-result-item").removeClass("active");
	}

	refresh_current_account() {
		if (!this.current_account) return;
		const account = this.current_account;
		frappe.call({
			method: "admin_panel.api.admin_api.search_account_smart",
			args: { query: account.username || account.uuid },
			callback: (res) => {
				const result = res.message;
				if (result && !result.error) {
					this.$.searchResultsList.find(".ah-result-item").remove();
					this.show_search_result(result);
				}
			},
			error: () => {},
		});
	}

	/* ── Tab: Overview ───────────────────────────────── */

	populate_overview(account) {
		// Identity
		const phone = account.owner?.phone;
		this.$.ovPhone.html(
			phone
				? `<a href="tel:${frappe.utils.escape_html(
						phone
				  )}" style="color:var(--color-primary);text-decoration:none;">${formatPhone(
						phone
				  )}</a>`
				: "-"
		);

		const email = account.owner?.email;
		if (email && email.address) {
			const badge = email.verified
				? '<span class="ah-verified-badge"><i class="fa fa-check-circle"></i> Verified</span>'
				: '<span class="ah-verified-badge" style="background:rgba(245,158,11,0.1);color:var(--color-warning);"><i class="fa fa-clock-o"></i> Unverified</span>';
			this.$.ovEmail.html(`${frappe.utils.escape_html(email.address)} ${badge}`);
		} else {
			this.$.ovEmail.text("-");
		}

		this.$.ovUsername.text(account.username || "-");
		this.$.ovNpub.text(account.npub || "-");

		// Account State
		this.$.ovLevelBadge
			.text(getHeadlineLabel(account))
			.attr("class", "ah-badge " + getHeadlineBadge(account));
		this.$.ovStatusBadge
			.text(getStatusLabel(account.status))
			.attr("class", "ah-badge " + getStatusBadge(account.status));
		this.$.ovErpParty.text(account.erpParty || "-");
		this.$.ovCreated.text(formatDate(account.createdAt));

		// Action buttons visibility
		this.$.btnLockAccount.toggle(account.status === ACCOUNT_STATUSES.ACTIVE);
		this.$.btnActivateAccount.toggle(account.status === ACCOUNT_STATUSES.LOCKED);
	}

	/* ── Tab: Banking ────────────────────────────────── */

	populate_banking(account) {
		const container = this.$.bankingContainer;
		container.html(`
            <div class="ah-empty">
                <div class="ah-empty-icon">🏦</div>
                <div class="ah-empty-text">Loading banking information…</div>
            </div>
        `);
		// find_account resolves mongo _id / username / uuid / phone / wallet id.
		const accountRef =
			account.username ||
			account.owner?.phone ||
			account.uuid ||
			((account.wallets || [])[0] || {}).id ||
			"";
		frappe.call({
			method: "admin_panel.api.banking.get_customer_banking",
			args: { erp_party: account.erpParty || "", account_ref: accountRef },
			callback: (res) => {
				if (this.current_account !== account) return; // switched customers mid-flight
				const d = res.message;
				if (!d || d.success === false) {
					container.html(
						this.banking_empty((d && d.error) || "Could not load banking information.")
					);
					return;
				}
				container.html(this.banking_html(d));
				this.bind_banking_actions(container, account, d);
			},
			error: () => {
				if (this.current_account !== account) return;
				container.html(this.banking_empty("Could not load banking information."));
			},
		});
	}

	bind_banking_actions(container, account, d) {
		container
			.find(".banking-add-btn")
			.on("click", () => this.bank_account_dialog(account, null));
		container.find(".banking-edit-btn").on("click", (e) => {
			const name = $(e.currentTarget).data("name");
			const bank = (d.bank_accounts || []).find((b) => b.name === name);
			if (bank) this.bank_account_dialog(account, bank);
		});
		container.find(".banking-default-btn").on("click", (e) => {
			const name = $(e.currentTarget).data("name");
			frappe.confirm(
				`Make <strong>${frappe.utils.escape_html(
					name
				)}</strong> the default cashout account? The current default is cleared.`,
				() => {
					this.banking_call(
						"admin_panel.api.banking.set_default_bank_account",
						{ bank_account_id: name, erp_party: account.erpParty },
						"Default cashout account updated.",
						account
					);
				}
			);
		});
	}

	banking_call(method, args, successMessage, account) {
		frappe.call({
			method,
			args,
			freeze: true,
			callback: (res) => {
				const result = res.message || {};
				if (result.success === false) {
					frappe.msgprint({
						title: "Error",
						indicator: "red",
						message: result.error || "Operation failed",
					});
					return;
				}
				frappe.show_alert({ message: successMessage, indicator: "green" }, 5);
				this.populate_banking(account);
			},
			error: (err) => {
				frappe.msgprint({
					title: "Error",
					indicator: "red",
					message: err?.responseJSON?.exception || err?.message || "Operation failed",
				});
			},
		});
	}

	bank_account_dialog(account, existing) {
		const isEdit = !!existing;
		const fields = [
			{
				fieldname: "bank_name",
				fieldtype: "Data",
				label: "Bank",
				reqd: 1,
				default: existing?.bank || "",
			},
			{
				fieldname: "bank_branch",
				fieldtype: "Data",
				label: "Branch Code",
				default: existing?.branch_code || "",
			},
			{
				fieldname: "account_type",
				fieldtype: "Select",
				label: "Account Type",
				options: "Chequing\nSavings",
				reqd: 1,
				default: existing?.account_type || "Chequing",
			},
			{
				fieldname: "account_number",
				fieldtype: "Data",
				label: "Account Number",
				reqd: 1,
				default: existing?.bank_account_no || "",
			},
			{
				fieldname: "currency",
				fieldtype: "Select",
				label: "Currency",
				options: "JMD\nUSD",
				reqd: 1,
				default: existing?.currency || "JMD",
				description: "Must match the payout currency — cashout accepts JMD or USD only.",
			},
			{
				fieldname: "account_name",
				fieldtype: "Data",
				label: "Account Holder Name",
				default: existing?.account_name || "",
			},
		];
		if (!isEdit) {
			fields.push({
				fieldname: "set_default",
				fieldtype: "Check",
				label: "Set as default cashout account",
			});
		}
		const d = new frappe.ui.Dialog({
			title: isEdit ? `Edit Bank Account — ${existing.bank || ""}` : "Add Bank Account",
			fields,
			primary_action_label: isEdit ? "Save Changes" : "Add Account",
			primary_action: (values) => {
				d.hide();
				const args = { erp_party: account.erpParty, ...values };
				if (isEdit) args.bank_account_id = existing.name;
				this.banking_call(
					isEdit
						? "admin_panel.api.banking.update_bank_account"
						: "admin_panel.api.banking.add_bank_account",
					args,
					isEdit ? "Bank account updated." : "Bank account added.",
					account
				);
			},
		});
		d.show();
	}

	banking_empty(message) {
		return `
            <div class="ah-empty">
                <div class="ah-empty-icon">🏦</div>
                <div class="ah-empty-text">${frappe.utils.escape_html(message)}</div>
            </div>
        `;
	}

	banking_html(d) {
		const esc = frappe.utils.escape_html;
		const row = (label, value) =>
			value == null || value === ""
				? ""
				: `<div class="ah-info-row">
                        <span class="ah-info-label">${esc(label)}</span>
                        <span class="ah-info-value">${esc(String(value))}</span>
                    </div>`;
		const okBadge = (text) =>
			`<span class="ah-verified-badge"><i class="fa fa-check-circle"></i> ${esc(
				text
			)}</span>`;
		const warnBadge = (text) =>
			`<span class="ah-verified-badge" style="background:rgba(245,158,11,0.1);color:var(--color-warning);">${esc(
				text
			)}</span>`;
		const noteCard = (title, message) => `
            <div class="ah-info-card">
                <h6><i class="fa fa-university" style="margin-right:6px;color:var(--color-primary);"></i> ${esc(
					title
				)}</h6>
                <div class="ah-info-row"><span class="ah-info-label">${esc(message)}</span></div>
            </div>`;

		const erpCards = (d.bank_accounts || [])
			.map(
				(b) => `
            <div class="ah-info-card">
                <h6><i class="fa fa-university" style="margin-right:6px;color:var(--color-primary);"></i>
                    Cashout — ${esc(b.bank || "Bank")}
                    ${b.is_default ? okBadge("Default") : ""}
                    ${b.disabled ? warnBadge("Disabled") : ""}
                </h6>
                ${row("Account name", b.account_name)}
                ${row("Account number", b.bank_account_no)}
                ${row("Branch", b.branch_code)}
                ${row("Type", b.account_type)}
                ${row("Currency", b.currency)}
                <div style="margin-top:10px;display:flex;gap:8px;">
                    <button class="btn btn-xs btn-default banking-edit-btn" data-name="${esc(
						b.name
					)}">Edit</button>
                    ${
						b.is_default
							? ""
							: `<button class="btn btn-xs btn-default banking-default-btn" data-name="${esc(
									b.name
							  )}">Set default</button>`
					}
                </div>
            </div>`
			)
			.join("");
		const erpSection =
			erpCards ||
			noteCard(
				"Cashout Bank Accounts",
				d.erp_party
					? "No bank accounts on file for this customer."
					: "No ERP customer linked — nothing on file."
			);

		const bridge = d.bridge || { linked: false };
		let bridgeSection = "";
		if (!bridge.linked) {
			bridgeSection = noteCard(
				"Bridge USD Account",
				bridge.error || "No Bridge customer linked."
			);
		} else {
			const virtuals = (bridge.virtual_accounts || [])
				.map(
					(v) => `
                <div class="ah-info-card">
                    <h6><i class="fa fa-university" style="margin-right:6px;color:var(--color-primary);"></i>
                        Bridge USD Account ${
							v.status === "activated" || v.status === "active"
								? okBadge(v.status)
								: warnBadge(v.status || "unknown")
						}
                    </h6>
                    ${row("Bank", v.bank_name)}
                    ${row("Beneficiary", v.beneficiary_name)}
                    ${row("Routing number", v.routing_number)}
                    ${row("Account number", v.account_number)}
                    ${row("Deposit currency", v.currency)}
                    ${row("Rails", (v.payment_rails || []).join(", "))}
                    ${row("Settles to", v.destination_currency)}
                </div>`
				)
				.join("");
			const externals = (bridge.external_accounts || [])
				.map(
					(e) => `
                <div class="ah-info-card">
                    <h6><i class="fa fa-university" style="margin-right:6px;color:var(--color-primary);"></i>
                        External — ${esc(e.bank_name || "Bank")}
                        ${e.active === false ? warnBadge("Inactive") : ""}
                    </h6>
                    ${row("Owner", e.owner_name)}
                    ${row("Type", e.account_type)}
                    ${row("Account", e.last_4 ? "•••• " + e.last_4 : null)}
                    ${row("Routing number", e.routing_number)}
                    ${row("IBAN", e.iban)}
                    ${row("Currency", e.currency)}
                </div>`
				)
				.join("");
			bridgeSection =
				(bridge.error
					? noteCard("Bridge USD Account", `Bridge error: ${bridge.error}`)
					: "") +
				(virtuals ||
					(bridge.error
						? ""
						: noteCard(
								"Bridge USD Account",
								`No virtual account issued yet (KYC: ${
									bridge.kyc_status || "unknown"
								}).`
						  ))) +
				externals;
		}

		// Bridge cards are read-only (Bridge owns that data); only ERP cashout
		// accounts are editable, and only when the account has an ERP party.
		const toolbar = d.erp_party
			? `<div style="margin-bottom:12px;display:flex;justify-content:flex-end;">
                <button class="btn btn-sm btn-primary banking-add-btn">Add Bank Account</button>
            </div>`
			: "";
		return `${toolbar}<div class="ah-info-grid">${erpSection}${bridgeSection}</div>`;
	}

	/* ── Tab: Wallets ────────────────────────────────── */

	populate_wallets(account) {
		const container = this.$.walletsContainer;
		container.empty();

		const wallets = account.wallets || [];
		if (wallets.length === 0) {
			container.html(`
                <div class="ah-empty">
                    <div class="ah-empty-icon">💰</div>
                    <div class="ah-empty-text">No wallet information available</div>
                </div>
            `);
			return;
		}

		// Sort: USD first, then others
		const sorted = [...wallets].sort((a, b) => {
			if (a.walletCurrency === "USD") return -1;
			if (b.walletCurrency === "USD") return 1;
			return 0;
		});

		sorted.forEach((w) => {
			const cur = w.walletCurrency || "USD";
			const card = $(`
                <div class="ah-wallet-card">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
                        <span class="ah-wallet-currency-badge">${frappe.utils.escape_html(
							cur
						)}</span>
                    </div>
                    <div class="ah-wallet-row">
                        <span class="ah-info-label">Balance</span>
                        <span class="ah-wallet-balance">${formatCurrency(w.balance, cur)}</span>
                    </div>
                    <div class="ah-wallet-row">
                        <span class="ah-info-label">Pending Incoming</span>
                        <span style="font-weight:500;color:var(--color-text01);">${formatCurrency(
							w.pendingIncomingBalance,
							cur
						)}</span>
                    </div>
                    <div class="ah-wallet-row" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--color-border01);">
                        <span class="ah-info-label">Wallet ID</span>
                        <span style="font-size:12px;color:var(--color-text02);font-family:monospace;">${frappe.utils.escape_html(
							w.id
						)}</span>
                    </div>
                </div>
            `);
			container.append(card);
		});
	}

	/* ── Tab: Documents ──────────────────────────────── */

	populate_documents(account) {
		const container = this.$.documentsContainer;
		container.empty();

		const username = account.username;
		if (!username) {
			container.html(`
                <div class="ah-empty">
                    <div class="ah-empty-icon">📄</div>
                    <div class="ah-empty-text">No documents uploaded</div>
                </div>
            `);
			return;
		}

		container.html(
			`<div class="ah-loading"><div class="ah-spinner"></div><p style="color:var(--color-text02);font-size:14px;">Loading documents...</p></div>`
		);

		frappe.call({
			method: "admin_panel.api.admin_api.get_upgrade_requests_by_account",
			args: { username: username },
			callback: (res) => {
				container.empty();
				const result = res.message;
				const requests = (result && result.data) || [];
				const docRequests = requests.filter((r) => r.id_document);

				if (docRequests.length === 0) {
					container.html(`
                        <div class="ah-empty">
                            <div class="ah-empty-icon">📄</div>
                            <div class="ah-empty-text">No documents uploaded</div>
                        </div>
                    `);
					return;
				}

				docRequests.forEach((r) => {
					const item = $(`
                        <div class="ah-doc-item">
                            <div>
                                <div class="ah-doc-info"><i class="fa fa-file-image-o" style="margin-right:6px;color:var(--color-primary);"></i> ${frappe.utils.escape_html(
									r.requested_level || "Unknown"
								)} Upgrade</div>
                                <div style="font-size:12px;color:var(--color-text02);margin-top:2px;">Submitted ${frappe.utils.escape_html(
									r.creation || ""
								)}</div>
                            </div>
                            <button class="ah-btn ah-btn-secondary ah-btn-sm btn-view-doc" data-file-key="${frappe.utils.escape_html(
								r.id_document
							)}">
                                <i class="fa fa-eye"></i> View
                            </button>
                        </div>
                    `);

					const requestName = r.name;
					item.find(".btn-view-doc").on("click", () => {
						window.open(
							"/app/account-upgrade-request/" + encodeURIComponent(requestName),
							"_blank"
						);
					});

					container.append(item);
				});
			},
			error: () => {
				container.html(`
                    <div class="ah-empty">
                        <div class="ah-empty-icon">⚠️</div>
                        <div class="ah-empty-text">Failed to load documents</div>
                        <div class="ah-empty-sub">An error occurred while fetching document data</div>
                    </div>
                `);
			},
		});
	}

	/* ── Tab: Merchant ───────────────────────────────── */

	populate_merchant(account) {
		const container = this.$.merchantContainer;
		container.empty();

		const merchants = account.merchants || [];
		if (merchants.length === 0) {
			container.html(`
                <div class="ah-empty">
                    <div class="ah-empty-icon">🏪</div>
                    <div class="ah-empty-text">No merchant information</div>
                </div>
            `);
			return;
		}

		merchants.forEach((m) => {
			const validBadge = m.validated
				? '<span class="ah-badge badge-approved"><i class="fa fa-check"></i> Validated</span>'
				: '<span class="ah-badge badge-pending"><i class="fa fa-clock-o"></i> Not Validated</span>';

			let mapLink = "-";
			const coords = m.coordinates || {};
			if (coords.latitude != null && coords.longitude != null) {
				mapLink = `<a href="https://www.google.com/maps?q=${coords.latitude},${
					coords.longitude
				}" target="_blank" style="color:var(--color-primary);text-decoration:none;">${coords.latitude.toFixed(
					4
				)}, ${coords.longitude.toFixed(4)}</a>`;
			}

			const card = $(`
                <div class="ah-merchant-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div class="ah-merchant-title">
                            <i class="fa fa-shopping-cart" style="margin-right:6px;color:var(--color-primary);"></i>
                            ${frappe.utils.escape_html(m.title || "Unnamed")}
                        </div>
                        ${validBadge}
                    </div>
                    <div class="ah-merchant-row"><strong>Username:</strong> ${frappe.utils.escape_html(
						m.username || "-"
					)}</div>
                    <div class="ah-merchant-row"><strong>Coordinates:</strong> ${mapLink}</div>
                    <div class="ah-merchant-row"><strong>Created:</strong> ${formatDate(
						m.createdAt
					)}</div>
                </div>
            `);

			// Action buttons for unvalidated merchants
			if (!m.validated) {
				const actionsDiv = $(`<div class="ah-merchant-actions"></div>`);

				const validateBtn = $(
					`<button class="ah-btn ah-btn-success ah-btn-sm"><i class="fa fa-check"></i> Validate</button>`
				);
				validateBtn.on("click", () => this.validate_merchant(m.id));

				const deleteBtn = $(
					`<button class="ah-btn ah-btn-danger ah-btn-sm"><i class="fa fa-trash"></i> Delete</button>`
				);
				deleteBtn.on("click", () => this.delete_merchant(m.id));

				actionsDiv.append(validateBtn, deleteBtn);
				card.append(actionsDiv);
			}

			container.append(card);
		});
	}

	/* ── Tab: Upgrade History ────────────────────────── */

	populate_upgrade_history(account) {
		const container = this.$.upgradeContainer;
		container.empty();

		const username = account.username;
		if (!username) {
			container.html(`
                <div class="ah-empty">
                    <div class="ah-empty-icon">📋</div>
                    <div class="ah-empty-text">No upgrade requests for this account</div>
                </div>
            `);
			return;
		}

		container.html(
			`<div class="ah-loading"><div class="ah-spinner"></div><p style="color:var(--color-text02);font-size:14px;">Loading upgrade history...</p></div>`
		);

		frappe.call({
			method: "admin_panel.api.admin_api.get_upgrade_requests_by_account",
			args: { username: username },
			callback: (res) => {
				container.empty();
				const result = res.message;
				const requests = (result && result.data) || [];

				if (requests.length === 0) {
					container.html(`
                        <div class="ah-empty">
                            <div class="ah-empty-icon">📋</div>
                            <div class="ah-empty-text">No upgrade requests for this account</div>
                        </div>
                    `);
					return;
				}

				const table = $(`
                    <table class="ah-table">
                        <thead>
                            <tr>
                                <th>Requested Level</th>
                                <th>Status</th>
                                <th>Submitted</th>
                                <th>Reviewed</th>
                                <th>Support Note</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                `);

				const tbody = table.find("tbody");
				requests.forEach((r) => {
					const statusLabel = getStatusLabel(r.status || "PENDING");
					const statusBadge = getStatusBadge(r.status || "PENDING");
					const levelLabel = getRequestedLevelLabel(r.requested_level);
					const levelBadge = getLevelBadge(r.requested_level);

					const row = $(`
                        <tr>
                            <td><span class="ah-badge ${levelBadge}">${levelLabel}</span></td>
                            <td><span class="ah-badge ${statusBadge}">${statusLabel}</span></td>
                            <td>${r.creation ? frappe.datetime.str_to_user(r.creation) : "-"}</td>
                            <td>${r.modified ? frappe.datetime.str_to_user(r.modified) : "-"}</td>
                            <td style="max-width:250px;white-space:normal;word-break:break-word;">${
								r.support_note ? frappe.utils.escape_html(r.support_note) : "-"
							}</td>
                        </tr>
                    `);
					tbody.append(row);
				});

				container.append(table);
			},
			error: () => {
				container.html(`
                    <div class="ah-empty">
                        <div class="ah-empty-icon">⚠️</div>
                        <div class="ah-empty-text">Failed to load upgrade history</div>
                        <div class="ah-empty-sub">An error occurred while fetching upgrade data</div>
                    </div>
                `);
			},
		});
	}

	/* ── Actions: Change Level ────────────────────────── */

	change_level() {
		if (!this.current_account) return;
		const account = this.current_account;

		const currentLevel = account.level;
		const options = Object.keys(ADMIN_LEVEL_OPTIONS)
			.filter((k) => k !== currentLevel)
			.map((k) => ({
				label: ADMIN_LEVEL_OPTIONS[k],
				value: k,
			}));

		if (options.length === 0) {
			frappe.msgprint({
				title: "Info",
				indicator: "blue",
				message: "No other levels available to change to.",
			});
			return;
		}

		const d = new frappe.ui.Dialog({
			title: "Change Account Level",
			fields: [
				{
					fieldname: "new_level",
					fieldtype: "Select",
					label: "New Level",
					reqd: 1,
					options: options.map((o) => o.label),
					default: options[0].label,
				},
			],
			primary_action_label: "Update Level",
			primary_action: (values) => {
				const selectedOption = options.find((o) => o.label === values.new_level);
				if (!selectedOption) return;

				// Flash requires an ERP party for level 2 (Pro) and 3 (Merchant)
				// accounts. Existing Pro/Merchant accounts already carry one — pass
				// it back so a re-level doesn't strip it. Minting a new party is the
				// upgrade-request approval flow's job (it creates the ERP Customer/
				// Address/Bank records), so don't fabricate one here.
				const needsErpParty =
					selectedOption.value === ACCOUNT_LEVELS.TWO ||
					selectedOption.value === ACCOUNT_LEVELS.THREE;
				if (needsErpParty && !account.erpParty) {
					frappe.msgprint({
						title: "ERP Party Required",
						indicator: "orange",
						message: `${
							ADMIN_LEVEL_OPTIONS[selectedOption.value]
						} accounts require an ERP party, and this account has none. Approve an account upgrade request instead — that flow creates the ERP Customer, Address, and Bank Account records.`,
					});
					return;
				}

				d.hide();
				frappe.call({
					method: "admin_panel.api.admin_api.update_account_level",
					args: {
						uid: account.id || account.uuid,
						level: selectedOption.value,
						erp_party: needsErpParty ? account.erpParty : undefined,
					},
					freeze: true,
					freeze_message: "Updating account level...",
					callback: (res) => {
						const result = res.message || {};
						if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
							frappe.msgprint({
								title: "Error",
								indicator: "red",
								message: formatApiErrors(result.errors),
							});
						} else {
							frappe.show_alert(
								{
									message: `Account level updated to ${
										ADMIN_LEVEL_OPTIONS[selectedOption.value]
									}`,
									indicator: "green",
								},
								5
							);
							this.refresh_current_account();
						}
					},
					error: (err) => {
						frappe.msgprint({
							title: "Error",
							indicator: "red",
							message:
								err?.responseJSON?.exception ||
								err?.message ||
								"Failed to update account level",
						});
					},
				});
			},
		});

		d.show();
	}

	/* ── Actions: Change Status ───────────────────────── */

	change_status(newStatus) {
		if (!this.current_account) return;
		const account = this.current_account;
		const isLock = newStatus === ACCOUNT_STATUSES.LOCKED;

		const d = new frappe.ui.Dialog({
			title: isLock ? "Lock Account" : "Activate Account",
			fields: [
				{
					fieldname: "comment",
					fieldtype: "Small Text",
					label: isLock ? "Reason for locking" : "Comment (optional)",
					reqd: isLock ? 1 : 0,
				},
			],
			primary_action_label: isLock ? "Lock Account" : "Activate Account",
			primary_action: (values) => {
				d.hide();
				frappe.call({
					method: "admin_panel.api.admin_api.update_account_status_api",
					args: {
						uid: account.id || account.uuid,
						account_uuid: account.uuid,
						username: account.username,
						status: newStatus,
						comment: values.comment || "",
					},
					freeze: true,
					freeze_message: isLock ? "Locking account..." : "Activating account...",
					callback: (res) => {
						const result = res.message || {};
						if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
							frappe.msgprint({
								title: "Error",
								indicator: "red",
								message: formatApiErrors(result.errors),
							});
						} else {
							frappe.show_alert(
								{
									message: `Account ${
										isLock ? "locked" : "activated"
									} successfully`,
									indicator: "green",
								},
								5
							);
							this.refresh_current_account();
						}
					},
					error: (err) => {
						frappe.msgprint({
							title: "Error",
							indicator: "red",
							message:
								err?.responseJSON?.exception ||
								err?.message ||
								`Failed to ${isLock ? "lock" : "activate"} account`,
						});
					},
				});
			},
		});

		d.show();
	}

	/* ── Actions: Update Phone ────────────────────────── */

	update_phone() {
		if (!this.current_account) return;
		const account = this.current_account;

		const d = new frappe.ui.Dialog({
			title: "Update Phone Number",
			fields: [
				{
					fieldname: "phone",
					fieldtype: "Data",
					label: "New Phone Number",
					description: "Enter phone number with country code (e.g., +1234567890)",
					reqd: 1,
					default: account.owner?.phone || "",
				},
			],
			primary_action_label: "Update Phone",
			primary_action: (values) => {
				d.hide();
				frappe.call({
					method: "admin_panel.api.admin_api.update_user_phone_api",
					args: {
						account_uuid: account.uuid,
						username: account.username,
						phone: values.phone,
					},
					freeze: true,
					freeze_message: "Updating phone number...",
					callback: (res) => {
						const result = res.message || {};
						if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
							frappe.msgprint({
								title: "Error",
								indicator: "red",
								message: formatApiErrors(result.errors),
							});
						} else {
							frappe.show_alert(
								{
									message: "Phone number updated successfully",
									indicator: "green",
								},
								5
							);
							this.refresh_current_account();
						}
					},
					error: (err) => {
						frappe.msgprint({
							title: "Error",
							indicator: "red",
							message:
								err?.responseJSON?.exception ||
								err?.message ||
								"Failed to update phone number",
						});
					},
				});
			},
		});

		d.show();
	}

	/* ── Actions: Validate / Delete Merchant ─────────── */

	validate_merchant(merchantId) {
		frappe.confirm("Are you sure you want to validate this merchant?", () => {
			frappe.call({
				method: "admin_panel.api.admin_api.validate_merchant_api",
				args: { merchant_id: merchantId },
				freeze: true,
				freeze_message: "Validating merchant...",
				callback: (res) => {
					const result = res.message || {};
					if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
						frappe.msgprint({
							title: "Error",
							indicator: "red",
							message: formatApiErrors(result.errors),
						});
					} else {
						frappe.show_alert(
							{ message: "Merchant validated successfully", indicator: "green" },
							5
						);
						this.refresh_current_account();
					}
				},
				error: (err) => {
					frappe.msgprint({
						title: "Error",
						indicator: "red",
						message:
							err?.responseJSON?.exception ||
							err?.message ||
							"Failed to validate merchant",
					});
				},
			});
		});
	}

	delete_merchant(merchantId) {
		frappe.confirm(
			"Are you sure you want to delete this merchant? This action cannot be undone.",
			() => {
				frappe.call({
					method: "admin_panel.api.admin_api.delete_merchant_api",
					args: { merchant_id: merchantId },
					freeze: true,
					freeze_message: "Deleting merchant...",
					callback: (res) => {
						const result = res.message || {};
						if (Array.isArray(result.errors) ? result.errors.length : result.errors) {
							frappe.msgprint({
								title: "Error",
								indicator: "red",
								message: formatApiErrors(result.errors),
							});
						} else {
							frappe.show_alert(
								{ message: "Merchant deleted successfully", indicator: "green" },
								5
							);
							this.refresh_current_account();
						}
					},
					error: (err) => {
						frappe.msgprint({
							title: "Error",
							indicator: "red",
							message:
								err?.responseJSON?.exception ||
								err?.message ||
								"Failed to delete merchant",
						});
					},
				});
			}
		);
	}

	/* ── View Document ───────────────────────────────── */

	view_document(fileKey) {
		if (!fileKey) return;
		frappe.show_alert(
			{
				message: __("Open the Account Upgrade Request form to view the document."),
				indicator: "blue",
			},
			5
		);
	}
}

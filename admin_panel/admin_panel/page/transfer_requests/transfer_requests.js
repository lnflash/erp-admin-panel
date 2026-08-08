frappe.pages["transfer-requests"].on_page_load = function (wrapper) {
	if (!frappe.user_roles.includes("Accounts Manager")) {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Transfer Requests",
			single_column: true,
		});

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

	page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Transfer Requests",
		single_column: true,
	});

	wrapper.transfer_requests = new TransferRequestsManager(page);
};

const CashoutStatus = {
	PENDING: "Pending",
	DRAFT: "Draft",
	IN_PROGRESS: "In Progress",
	PAID: "Paid",
	COMPLETED: "Completed",
	CANCELLED: "Cancelled",
	CANCELED: "Canceled",
	FAILED: "Failed",
};

const CASHOUT_STATUS_BADGE_MAP = {
	[CashoutStatus.PENDING]: "cashout-badge-pending",
	[CashoutStatus.DRAFT]: "cashout-badge-pending",
	[CashoutStatus.IN_PROGRESS]: "cashout-badge-pending",
	[CashoutStatus.PAID]: "cashout-badge-paid",
	[CashoutStatus.COMPLETED]: "cashout-badge-paid",
	[CashoutStatus.CANCELLED]: "cashout-badge-cancelled",
	[CashoutStatus.CANCELED]: "cashout-badge-cancelled",
	[CashoutStatus.FAILED]: "cashout-badge-failed",
};

const BridgeStatus = {
	PENDING: "Pending",
	FIAT_RECEIVED: "Fiat Received",
	SETTLED: "Settled",
	COMPLETED: "Completed",
	FAILED: "Failed",
};

const BRIDGE_STATUS_BADGE_MAP = {
	[BridgeStatus.PENDING]: "cashout-badge-pending",
	[BridgeStatus.FIAT_RECEIVED]: "cashout-badge-pending",
	[BridgeStatus.SETTLED]: "cashout-badge-paid",
	[BridgeStatus.COMPLETED]: "cashout-badge-paid",
	[BridgeStatus.FAILED]: "cashout-badge-failed",
};

function getCashoutStatusBadgeClass(status) {
	return CASHOUT_STATUS_BADGE_MAP[status] || "cashout-badge-pending";
}

function getBridgeStatusBadgeClass(status) {
	return BRIDGE_STATUS_BADGE_MAP[status] || "cashout-badge-pending";
}

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

class TransferRequestsManager {
	constructor(page) {
		this.page = page;
		this.selected_request = null;
		this.active_type = "cashout";
		this.cashout_requests = [];
		this.bridge_requests = [];
		this.current_page = 1;
		this.page_size = 10;
		this.total_pages = 1;
		this.total_count = 0;
		this.cashoutDetailsHtml = "";
		this.$cache = {};
		this.setup_page();
	}

	setup_page() {
		this.create_layout();
		this.cache_elements();
		this.cashoutDetailsHtml = this.$cache.requestDetails.find(".card-body").html();
		this.bind_events();
		this.update_type_controls();
		this.load_requests();
	}

	cache_elements() {
		const main = this.page.main;
		this.$cache = {
			searchInput: main.find(".search-input"),
			requestsLoading: main.find(".requests-loading"),
			requestsTable: main.find(".requests-list table"),
			noRequests: main.find(".no-requests"),
			requestDetails: main.find(".request-details"),
			pulseTiles: main.find(".pulse-tiles"),
			paginationControls: main.find(".pagination-controls"),
			requestsTbody: main.find(".requests-tbody"),
			searchLoading: main.find(".search-loading"),
			searchError: main.find(".search-error"),
			filterStatus: main.find("#filter-status"),
			filterTransactionType: main.find("#filter-transaction-type"),
			tableHead: main.find(".requests-thead"),
			tableTitle: main.find(".request-table-title"),
			noRequestsTitle: main.find(".no-requests-title"),
			noRequestsBody: main.find(".no-requests-body"),
		};
	}

	create_layout() {
		this.page.main.html(`
            <style>
                /* ═══ Ops-pulse design system — Transfer Requests (daily queue) ═══
                   Same tokens as dashboard/census/account-hub; legacy --color-*
                   names aliased so dynamic templates + inline styles convert. */
                .flash-cashout-manager {
                    --tr-surface: var(--card-bg, #ffffff); --tr-ink: var(--text-color, #1a2420);
                    --tr-ink2: var(--text-muted, #5c6b65); --tr-ink3: var(--text-light, #8fa098);
                    --tr-line: var(--border-color, #e2e8e5); --tr-line-soft: var(--subtle-fg, #ecf1ee);
                    --tr-accent: #007856; --tr-accent-ink: #007856; --tr-accent-soft: #e6f3ee;
                    --tr-good: #0ca30c; --tr-warn: #b87d00; --tr-warn-bg: #fff3d6;
                    --tr-serious: #c05a32; --tr-serious-bg: #fdeae2;
                    --tr-shadow: 0 1px 2px rgba(26,36,32,0.05), 0 4px 14px rgba(26,36,32,0.04);
                    /* legacy aliases */
                    --color-primary: var(--tr-accent); --color-background: transparent;
                    --color-layer: var(--tr-surface); --color-text01: var(--tr-ink);
                    --color-text02: var(--tr-ink2); --color-border01: var(--tr-line);
                    --color-green: var(--tr-good); --color-error: var(--tr-serious);
                    --color-warning: var(--tr-warn);
                    max-width: 1400px; margin: 0 auto;
                }
                [data-theme="dark"] .flash-cashout-manager, .dark .flash-cashout-manager {
                    --tr-accent: #1e9e75; --tr-accent-ink: #4cc29e; --tr-accent-soft: #12352a;
                    --tr-good: #35c135; --tr-warn: #fab219; --tr-warn-bg: #33290d;
                    --tr-serious: #ec835a; --tr-serious-bg: #38211a;
                    --tr-shadow: 0 1px 2px rgba(0,0,0,0.35), 0 6px 18px rgba(0,0,0,0.25);
                }

                /* dataset switch — segmented control */
                .flash-cashout-manager .transfer-tabs { display: inline-flex; gap: 3px;
                    background: var(--tr-line-soft); border: 1px solid var(--tr-line);
                    border-radius: 11px; padding: 3px; margin-bottom: 14px; }
                .flash-cashout-manager .transfer-tab { border: 0; background: transparent;
                    color: var(--tr-ink2); font-size: 13px; font-weight: 600;
                    padding: 6px 18px; border-radius: 8px; cursor: pointer; transition: all 0.13s; }
                .flash-cashout-manager .transfer-tab:hover { color: var(--tr-ink); }
                .flash-cashout-manager .transfer-tab.active { background: var(--tr-surface);
                    color: var(--tr-accent-ink); box-shadow: var(--tr-shadow); }
                .flash-cashout-manager .transfer-tab:focus-visible { outline: 2px solid var(--tr-accent);
                    outline-offset: 1px; }

                /* toolbar */
                .flash-cashout-manager .modern-search-card { background: var(--tr-surface);
                    border: 1px solid var(--tr-line); border-radius: 14px;
                    box-shadow: var(--tr-shadow); padding: 14px 16px; margin-bottom: 14px; }
                .flash-cashout-manager .modern-search-wrapper { display: flex; gap: 10px;
                    flex-wrap: wrap; align-items: center; }
                .flash-cashout-manager .modern-search-wrapper[style*="margin-bottom"] {
                    margin-bottom: 10px !important; }
                .flash-cashout-manager .modern-search-input { flex: 1; min-width: 220px;
                    padding: 8px 13px; border: 1px solid var(--tr-line); border-radius: 10px;
                    font-size: 13.5px; background: var(--tr-surface); color: var(--tr-ink); }
                .flash-cashout-manager .modern-search-input:focus { outline: 2px solid var(--tr-accent);
                    outline-offset: 1px; border-color: var(--tr-accent); }
                .flash-cashout-manager .modern-search-input::placeholder { color: var(--tr-ink3); }
                .flash-cashout-manager .modern-search-select { flex: 0 1 220px; min-width: 170px;
                    appearance: auto; }

                /* buttons */
                .flash-cashout-manager .modern-btn { display: inline-flex; align-items: center;
                    gap: 6px; border: 1px solid var(--tr-line); background: var(--tr-surface);
                    color: var(--tr-ink); border-radius: 9px; padding: 7px 14px; font-size: 13px;
                    font-weight: 600; cursor: pointer; transition: all 0.13s; }
                .flash-cashout-manager .modern-btn:hover { border-color: var(--tr-accent); }
                .flash-cashout-manager .modern-btn:focus-visible { outline: 2px solid var(--tr-accent);
                    outline-offset: 1px; }
                .flash-cashout-manager .modern-btn:disabled { opacity: 0.55; cursor: not-allowed; }
                .flash-cashout-manager .modern-btn-primary { background: var(--tr-accent);
                    border-color: var(--tr-accent); color: #fff; }
                .flash-cashout-manager .modern-btn-primary:hover { filter: brightness(1.07); }

                /* quick actions — quiet round icon buttons */
                .flash-cashout-manager .modern-icon-btn { width: 28px; height: 28px;
                    display: inline-grid; place-items: center; border-radius: 8px;
                    border: 1px solid var(--tr-line); background: var(--tr-surface);
                    color: var(--tr-ink2); cursor: pointer; margin: 0 2px;
                    font-size: 12px; transition: all 0.13s; }
                .flash-cashout-manager .modern-icon-btn:hover { border-color: currentColor; }
                .flash-cashout-manager .modern-icon-btn-primary { color: var(--tr-accent-ink); }
                .flash-cashout-manager .modern-icon-btn-primary:hover { background: var(--tr-accent-soft); }
                .flash-cashout-manager .modern-icon-btn-success { color: var(--tr-good); }
                .flash-cashout-manager .modern-icon-btn-success:hover { background: var(--tr-accent-soft); }

                /* cards */
                .flash-cashout-manager .modern-requests-card { background: var(--tr-surface);
                    border: 1px solid var(--tr-line); border-radius: 14px;
                    box-shadow: var(--tr-shadow); overflow: hidden; margin-bottom: 14px; }
                .flash-cashout-manager .modern-card-header { display: flex; align-items: center;
                    justify-content: space-between; gap: 12px; padding: 13px 18px;
                    border-bottom: 1px solid var(--tr-line); }
                .flash-cashout-manager .modern-card-title { margin: 0; font-size: 13.5px;
                    font-weight: 650; color: var(--tr-ink); display: flex; align-items: center; }
                .flash-cashout-manager .modern-card-title .fa { color: var(--tr-accent-ink); }

                /* table */
                .flash-cashout-manager .modern-table-wrapper { overflow-x: auto; }
                .flash-cashout-manager .modern-table { width: 100%; border-collapse: collapse;
                    font-size: 13px; }
                .flash-cashout-manager .modern-table th { text-align: left; font-size: 11px;
                    letter-spacing: 0.05em; text-transform: uppercase; color: var(--tr-ink2);
                    font-weight: 650; padding: 10px 14px; border-bottom: 1px solid var(--tr-line);
                    white-space: nowrap; }
                .flash-cashout-manager .modern-table td { padding: 10px 14px;
                    border-bottom: 1px solid var(--tr-line-soft); color: var(--tr-ink);
                    font-variant-numeric: tabular-nums; }
                .flash-cashout-manager .modern-table td strong { font-weight: 600; }
                .flash-cashout-manager .modern-table tbody tr { cursor: pointer;
                    border-left: 3px solid transparent; transition: background 0.12s; }
                .flash-cashout-manager .modern-table tbody tr:hover { background: var(--tr-line-soft); }
                .flash-cashout-manager .modern-table tbody tr.selected { background: var(--tr-accent-soft);
                    border-left-color: var(--tr-accent); }
                .flash-cashout-manager .modern-table tbody tr:last-child td { border-bottom: none; }

                /* status chips — pending work is amber, settled is green, failed is serious */
                .flash-cashout-manager .modern-badge { display: inline-flex; align-items: center;
                    border-radius: 999px; padding: 3px 11px; font-size: 11.5px; font-weight: 650;
                    letter-spacing: 0.02em; white-space: nowrap; }
                .flash-cashout-manager .cashout-badge-pending { background: var(--tr-warn-bg);
                    color: var(--tr-warn); }
                .flash-cashout-manager .cashout-badge-paid { background: var(--tr-accent-soft);
                    color: var(--tr-accent-ink); }
                .flash-cashout-manager .cashout-badge-cancelled { background: var(--tr-line-soft);
                    color: var(--tr-ink3); }
                .flash-cashout-manager .cashout-badge-failed { background: var(--tr-serious-bg);
                    color: var(--tr-serious); }

                /* empty + loading */
                .flash-cashout-manager .no-requests { text-align: center; padding: 40px 20px; }
                .flash-cashout-manager .no-requests-icon { font-size: 26px; margin-bottom: 8px;
                    filter: grayscale(0.4); opacity: 0.75; }
                .flash-cashout-manager .no-requests-title { color: var(--tr-ink); margin: 0; }
                .flash-cashout-manager .no-requests-body { color: var(--tr-ink3); margin: 4px 0 0; }
                .flash-cashout-manager .loading-spinner { text-align: center; padding: 34px 0; }
                .flash-cashout-manager .loading-spinner p { margin: 8px 0 0; font-size: 12.5px; }
                .flash-cashout-manager .spinner { width: 22px; height: 22px;
                    border: 2px solid var(--tr-line); border-top-color: var(--tr-accent);
                    border-radius: 50%; margin: 0 auto; animation: tr-spin 0.8s linear infinite; }
                @keyframes tr-spin { to { transform: rotate(360deg); } }

                /* detail panel */
                .flash-cashout-manager .detail-section { margin-bottom: 18px; }
                .flash-cashout-manager .section-header { font-size: 11px; letter-spacing: 0.06em;
                    text-transform: uppercase; color: var(--tr-ink2); font-weight: 650;
                    margin: 0 0 8px; display: flex; align-items: center; }
                .flash-cashout-manager .detail-item { display: flex; justify-content: space-between;
                    gap: 12px; align-items: baseline; padding: 6px 0;
                    border-bottom: 1px solid var(--tr-line-soft); }
                .flash-cashout-manager .detail-label { font-size: 11px; letter-spacing: 0.05em;
                    text-transform: uppercase; color: var(--tr-ink2); font-weight: 600; flex: none; }
                .flash-cashout-manager .detail-value { font-size: 13px; font-weight: 600;
                    color: var(--tr-ink); text-align: right; word-break: break-word; min-width: 0;
                    font-variant-numeric: tabular-nums; }
                .flash-cashout-manager .detail-value.amount-display { font-size: 15px;
                    font-weight: 650; }
                .flash-cashout-manager .detail-link { color: var(--tr-accent-ink);
                    text-decoration: none; font-weight: 600; }
                .flash-cashout-manager .detail-link:hover { text-decoration: underline; }
                .flash-cashout-manager .detail-remarks { white-space: pre-wrap; text-align: right; }

                /* pagination */
                .flash-cashout-manager .pagination-controls { display: flex; }

                /* queue pulse tiles */
                .flash-cashout-manager .tr-tiles { display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                    gap: 12px; margin-bottom: 14px; }
                .flash-cashout-manager .tr-tile { background: var(--tr-surface);
                    border: 1px solid var(--tr-line); border-radius: 14px;
                    box-shadow: var(--tr-shadow); padding: 12px 16px; }
                .flash-cashout-manager .tr-tile-label { font-size: 11px; letter-spacing: 0.06em;
                    text-transform: uppercase; color: var(--tr-ink2); font-weight: 650; }
                .flash-cashout-manager .tr-tile-value { font-size: 22px; font-weight: 650;
                    color: var(--tr-ink); font-variant-numeric: tabular-nums; margin-top: 2px; }
                .flash-cashout-manager .tr-tile-value.warn { color: var(--tr-warn); }
                .flash-cashout-manager .tr-tile-value.bad { color: var(--tr-serious); }
                .flash-cashout-manager .tr-tile-sub { font-size: 11.5px; color: var(--tr-ink3);
                    margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

                /* row age chips */
                .flash-cashout-manager .tr-age { display: inline-flex; border-radius: 999px;
                    padding: 2px 8px; font-size: 11px; font-weight: 650; margin-left: 8px;
                    background: var(--tr-line-soft); color: var(--tr-ink2); }
                .flash-cashout-manager .tr-age.warn { background: var(--tr-warn-bg); color: var(--tr-warn); }
                .flash-cashout-manager .tr-age.bad { background: var(--tr-serious-bg); color: var(--tr-serious); }

                /* details as a right drawer — no scroll-jump on row click */
                .flash-cashout-manager .request-details { position: fixed; top: 0; right: 0;
                    bottom: 0; width: min(620px, 94vw); z-index: 1040; margin: 0;
                    border-radius: 16px 0 0 16px; border-right: none;
                    box-shadow: -20px 0 50px rgba(26, 36, 32, 0.18); overflow-y: auto; }
                [data-theme="dark"] .flash-cashout-manager .request-details,
                .dark .flash-cashout-manager .request-details {
                    box-shadow: -20px 0 50px rgba(0, 0, 0, 0.5); }
                .flash-cashout-manager .request-details .modern-card-header { position: sticky;
                    top: 0; background: var(--tr-surface); z-index: 1; }

                @media (prefers-reduced-motion: no-preference) {
                    .flash-cashout-manager .modern-requests-card { animation: tr-rise 0.3s ease; }
                    @keyframes tr-rise { from { opacity: 0; transform: translateY(5px); } }
                    .flash-cashout-manager .request-details { animation: tr-slide 0.22s ease; }
                    @keyframes tr-slide { from { opacity: 0.4; transform: translateX(40px); } }
                }
            </style>

            <div class="flash-cashout-manager m-3">
                <div class="transfer-tabs" role="tablist" aria-label="Transfer request type">
                    <button class="transfer-tab active" data-type="cashout" role="tab" aria-selected="true">Cashouts</button>
                    <button class="transfer-tab" data-type="bridge" role="tab" aria-selected="false">Bridge</button>
                    <button class="transfer-tab" data-type="fygaro" role="tab" aria-selected="false">Card Top-Ups</button>
                </div>

                <!-- Queue pulse -->
                <div class="tr-tiles pulse-tiles" style="display:none;"></div>

                <!-- Search & Filter -->
                <div class="modern-search-card">
                    <div class="modern-search-wrapper" style="margin-bottom: 20px;">
                        <input
                            type="text"
                            class="modern-search-input search-input"
                            placeholder="Enter username or phone number"
                        >
                        <button class="modern-btn modern-btn-primary btn-search">
                            <i class="fa fa-search"></i>
                            Search
                        </button>
                    </div>
                    <div class="modern-search-wrapper">
                        <select id="filter-status" class="modern-search-input modern-search-select">
                            <option value="">Status (All)</option>
                            <option value="${CashoutStatus.PENDING}">Pending</option>
                            <option value="${CashoutStatus.PAID}">Paid</option>
                            <option value="${CashoutStatus.CANCELLED}">Cancelled</option>
                            <option value="${CashoutStatus.FAILED}">Failed</option>
                        </select>
                        <select id="filter-transaction-type" class="modern-search-input modern-search-select" style="display:none;">
                            <option value="">Bridge Type (All)</option>
                            <option value="Topup">Topup</option>
                            <option value="Cashout">Cashout</option>
                        </select>
                    </div>
                </div>

                <!-- Transfer Requests Table -->
                <div class="modern-requests-card">
                    <div class="modern-card-header">
                        <h5 class="modern-card-title">
                            <i class="fa fa-money" style="margin-right: 10px;"></i>
                            <span class="request-table-title">Cashout Requests</span>
                        </h5>
                        <button class="modern-btn modern-btn-secondary btn-refresh">
                            <i class="fa fa-refresh"></i>
                            Refresh
                        </button>
                    </div>
                    <div class="modern-table-wrapper">
                        <div class="requests-loading loading-spinner" style="display: none;">
                            <div class="spinner"></div>
                            <p style="color: var(--color-text02);">Loading requests...</p>
                        </div>

                        <div class="requests-list">
                            <table class="modern-table">
                                <thead class="requests-thead">
                                    <tr>
                                        <th>Username</th>
                                        <th>Phone</th>
                                        <th>Send (USD)</th>
                                        <th>Receive (JMD)</th>
                                        <th>Status</th>
                                        <th>Submitted</th>
                                    </tr>
                                </thead>
                                <tbody class="requests-tbody">
                                    <!-- Populated dynamically -->
                                </tbody>
                            </table>
                            <div class="no-requests" style="display: none;">
                                <div class="no-requests-icon">💸</div>
                                <p class="no-requests-title" style="font-size: 16px; font-weight: 500;">No cashout requests found</p>
                                <p class="no-requests-body" style="font-size: 14px;">Cashout requests will appear here when submitted</p>
                            </div>
                        </div>
                    </div>
                    <!-- Pagination Controls -->
                    <div class="pagination-controls" style="display: none; padding: 16px 24px; border-top: 1px solid var(--color-border01); justify-content: space-between; align-items: center;">
                        <div class="pagination-info" style="color: var(--color-text02); font-size: 14px;">
                            Showing <span class="page-start">1</span>-<span class="page-end">10</span> of <span class="total-count">0</span> requests
                        </div>
                        <div class="pagination-buttons" style="display: flex; gap: 8px; align-items: center;">
                            <button class="modern-btn modern-btn-secondary btn-first-page" title="First page" style="padding: 8px 12px;">
                                <i class="fa fa-angle-double-left"></i>
                            </button>
                            <button class="modern-btn modern-btn-secondary btn-prev-page" title="Previous page" style="padding: 8px 12px;">
                                <i class="fa fa-angle-left"></i>
                            </button>
                            <span class="page-indicator" style="padding: 8px 16px; font-weight: 500; color: var(--color-text01);">
                                Page <span class="current-page">1</span> of <span class="total-pages">1</span>
                            </span>
                            <button class="modern-btn modern-btn-secondary btn-next-page" title="Next page" style="padding: 8px 12px;">
                                <i class="fa fa-angle-right"></i>
                            </button>
                            <button class="modern-btn modern-btn-secondary btn-last-page" title="Last page" style="padding: 8px 12px;">
                                <i class="fa fa-angle-double-right"></i>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Request Details Panel -->
                <div class="request-details modern-requests-card" style="display: none;">
                    <div class="modern-card-header">
                        <h5 class="modern-card-title">
                            <i class="fa fa-file-text-o" style="margin-right: 10px;"></i>
                            Cashout Details
                        </h5>
                        <button class="modern-btn modern-btn-secondary btn-close-details">
                            <i class="fa fa-times"></i>
                            Close
                        </button>
                    </div>
                    <div class="card-body" style="padding: 24px;">

                        <!-- User Information -->
                        <div class="detail-section mb-4">
                            <h6 class="section-header">
                                <i class="fa fa-user" style="margin-right: 8px; color: var(--color-primary);"></i>
                                User Information
                            </h6>
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Username</span>
                                        <span class="detail-value detail-username"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Full Name</span>
                                        <span class="detail-value detail-fullname"></span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Phone</span>
                                        <span class="detail-value detail-phone"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Email</span>
                                        <span class="detail-value detail-email"></span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Cashout Information -->
                        <div class="detail-section mb-4">
                            <h6 class="section-header">
                                <i class="fa fa-exchange" style="margin-right: 8px; color: var(--color-primary);"></i>
                                Cashout Information
                            </h6>
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Offer ID</span>
                                        <span class="detail-value detail-offer-id"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Wallet ID</span>
                                        <span class="detail-value detail-wallet-id"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Send (USD)</span>
                                        <span class="detail-value amount-display detail-send"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Flash Fee</span>
                                        <span class="detail-value detail-flash-fee"></span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Exchange Rate</span>
                                        <span class="detail-value detail-exchange-rate"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Receive (JMD)</span>
                                        <span class="detail-value amount-display detail-receive-jmd"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Receive (USD)</span>
                                        <span class="detail-value detail-receive-usd"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Journal Entry</span>
                                        <span class="detail-value detail-journal-entry"></span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Bank Account -->
                        <div class="detail-section mb-4">
                            <h6 class="section-header">
                                <i class="fa fa-bank" style="margin-right: 8px; color: var(--color-primary);"></i>
                                Bank Account
                            </h6>
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Bank Account</span>
                                        <span class="detail-value detail-bank-account"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Bank Name</span>
                                        <span class="detail-value detail-bank-name"></span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Account Number</span>
                                        <span class="detail-value detail-account-number"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Account Type</span>
                                        <span class="detail-value detail-account-type"></span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Payment Journal Entry (shown only when recorded) -->
                        <div class="detail-section detail-payment-entry-section mb-4" style="display: none;">
                            <h6 class="section-header">
                                <i class="fa fa-credit-card" style="margin-right: 8px; color: var(--color-green);"></i>
                                Payment Journal Entry
                            </h6>
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Payment Journal Entry</span>
                                        <span class="detail-value detail-payment-entry"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Payment Amount</span>
                                        <span class="detail-value detail-pe-amount"></span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Payment Date</span>
                                        <span class="detail-value detail-pe-date"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Mode of Payment</span>
                                        <span class="detail-value detail-pe-mode"></span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Other Information -->
                        <div class="detail-section mb-4">
                            <h6 class="section-header">
                                <i class="fa fa-info-circle" style="margin-right: 8px; color: var(--color-primary);"></i>
                                Other Information
                            </h6>
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Status</span>
                                        <span class="detail-value detail-status"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Request ID</span>
                                        <span class="detail-value detail-request-id"></span>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="detail-item">
                                        <span class="detail-label">Submitted</span>
                                        <span class="detail-value detail-submitted"></span>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">Last Modified</span>
                                        <span class="detail-value detail-modified"></span>
                                    </div>
                                </div>
                                <div class="col-md-12">
                                    <div class="detail-item">
                                        <span class="detail-label">Remarks</span>
                                        <span class="detail-value detail-remarks"></span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="d-flex gap-2 justify-content-end" style="gap: 12px;">
                            <button class="modern-btn modern-btn-secondary btn-create-cashout">
                                <i class="fa fa-plus"></i>
                                Create
                            </button>
                            <button class="modern-btn modern-btn-primary btn-confirm-payment">
                                <i class="fa fa-key"></i>
                                Confirm
                            </button>
                            <button class="modern-btn modern-btn-primary btn-complete-cashout" style="background: var(--color-green);">
                                <i class="fa fa-check"></i>
                                Mark as Complete
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Search States -->
                <div class="search-loading loading-spinner" style="display: none;">
                    <div class="spinner"></div>
                    <p style="color: var(--color-text02);">Searching...</p>
                </div>

                <div class="search-error modern-search-card" style="display: none; background: rgba(220, 38, 38, 0.05); border-color: var(--color-error);">
                    <div style="color: var(--color-error); display: flex; align-items: center; gap: 12px;">
                        <i class="fa fa-exclamation-circle" style="font-size: 24px;"></i>
                        <span class="error-message"></span>
                    </div>
                </div>
            </div>
        `);
	}

	bind_events() {
		const main = this.page.main;

		const debouncedSearch = debounce(() => {
			if (this.$cache.searchInput.val().trim()) {
				this.search();
			} else {
				this.$cache.searchError.hide();
				this.current_page = 1;
				this.load_requests();
			}
		}, 300);

		main.find(".transfer-tab").on("click", (event) => {
			this.switch_type($(event.currentTarget).data("type"));
		});
		main.find(".btn-search").on("click", () => this.search());
		this.$cache.searchInput.on("keypress", (e) => {
			if (e.which === 13) this.search();
		});
		this.$cache.searchInput.on("input", debouncedSearch);

		main.find(".btn-refresh").on("click", () => this.load_requests());

		$(document).on("keydown.transfer_requests", (e) => {
			// wrapper visibility guard: desk keeps this page alive after
			// navigation, and this handler must not fire on other pages
			if (e.key === "Escape" && !window.cur_dialog && this.page.wrapper.is(":visible")) {
				this.close_details();
			}
		});
		main.find(".btn-close-details").on("click", () => this.close_details());
		main.on("click", ".btn-create-cashout", () =>
			this.create_cashout_request(this.selected_request)
		);
		main.on("click", ".btn-confirm-payment", () =>
			this.confirm_cashout_payment(this.selected_request)
		);
		main.on("click", ".btn-complete-cashout", () =>
			this.complete_cashout(this.selected_request)
		);

		this.$cache.filterStatus.on("change", () => {
			this.current_page = 1;
			this.load_requests();
		});
		this.$cache.filterTransactionType.on("change", () => {
			this.current_page = 1;
			this.load_requests();
		});

		main.find(".btn-first-page").on("click", () => this.go_to_page(1));
		main.find(".btn-prev-page").on("click", () => this.go_to_page(this.current_page - 1));
		main.find(".btn-next-page").on("click", () => this.go_to_page(this.current_page + 1));
		main.find(".btn-last-page").on("click", () => this.go_to_page(this.total_pages));
	}

	switch_type(type) {
		if (!["cashout", "bridge", "fygaro"].includes(type) || this.active_type === type) return;
		this.active_type = type;
		this.current_page = 1;
		this.selected_request = null;
		this.$cache.searchInput.val("");
		this.$cache.searchError.hide();
		this.$cache.requestDetails.hide();
		this.update_type_controls();
		this.load_requests();
	}

	update_type_controls() {
		const isBridge = this.active_type === "bridge";
		const isFygaro = this.active_type === "fygaro";
		// Bridge and Card Top-Ups are both audit views over Bridge Transfer
		// Request rows — one per provider; only the cashout tab differs.
		const isAudit = isBridge || isFygaro;
		this.page.main.find(".transfer-tab").removeClass("active").attr("aria-selected", "false");
		this.page.main
			.find(`.transfer-tab[data-type="${this.active_type}"]`)
			.addClass("active")
			.attr("aria-selected", "true");

		this.$cache.tableTitle.text(
			isFygaro
				? "Card Top-Ups (Fygaro)"
				: isBridge
				? "Bridge Transfer Requests"
				: "Cashout Requests"
		);
		this.$cache.searchInput.attr(
			"placeholder",
			isFygaro
				? "Search request, Fygaro transaction, account, or wallet ID"
				: isBridge
				? "Search request, Bridge transfer, account, or wallet ID"
				: "Enter username or phone number"
		);

		// Card top-ups are Topup-only; the type filter is a Bridge concern.
		this.$cache.filterTransactionType.toggle(isBridge);
		this.$cache.noRequestsTitle.text(
			isFygaro
				? "No card top-ups found"
				: isBridge
				? "No Bridge transfer requests found"
				: "No cashout requests found"
		);
		this.$cache.noRequestsBody.text(
			isFygaro
				? "Fygaro card top-ups will appear here as payments arrive"
				: isBridge
				? "Bridge transfer audit records will appear here when received"
				: "Cashout requests will appear here when submitted"
		);

		const options = isAudit
			? [
					"",
					BridgeStatus.PENDING,
					BridgeStatus.FIAT_RECEIVED,
					BridgeStatus.SETTLED,
					BridgeStatus.COMPLETED,
					BridgeStatus.FAILED,
			  ]
			: [
					"",
					CashoutStatus.PENDING,
					CashoutStatus.PAID,
					CashoutStatus.CANCELLED,
					CashoutStatus.FAILED,
			  ];
		const labels = isAudit
			? ["Status (All)", "Pending", "Fiat Received", "Settled", "Completed", "Failed"]
			: ["Status (All)", "Pending", "Paid", "Cancelled", "Failed"];
		this.$cache.filterStatus.html(
			options
				.map((value, index) => `<option value="${value}">${labels[index]}</option>`)
				.join("")
		);

		this.render_table_header();
	}

	render_table_header() {
		const cashoutHeaders = [
			"Username",
			"Phone",
			"Send (USD)",
			"Receive (JMD)",
			"Status",
			"Submitted",
			"Actions",
		];
		const bridgeHeaders = ["Request ID", "Type", "Amount", "Status", "Failure", "Last Seen"];
		const headers = this.active_type !== "cashout" ? bridgeHeaders : cashoutHeaders;

		this.$cache.tableHead.html(`
            <tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr>
        `);
	}

	server_now_ms() {
		// Ages are measured against the server clock the payload ships, not
		// the browser clock — operator tz must not skew warn/bad tones.
		const raw = this.pulse && this.pulse.now;
		const parsed = raw ? new Date(String(raw).replace(" ", "T")).getTime() : NaN;
		return isNaN(parsed) ? Date.now() : parsed;
	}

	formatAge(dateStr) {
		const then = new Date(String(dateStr).replace(" ", "T"));
		if (isNaN(then)) return "";
		const mins = Math.max(0, Math.floor((this.server_now_ms() - then.getTime()) / 60000));
		if (mins < 60) return `${mins}m`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h`;
		return `${Math.floor(hours / 24)}d ${hours % 24}h`;
	}

	age_tone(dateStr) {
		const then = new Date(String(dateStr).replace(" ", "T"));
		if (isNaN(then)) return "";
		const hours = (this.server_now_ms() - then.getTime()) / 3600e3;
		if (hours >= 24) return "bad";
		if (hours >= 6) return "warn";
		return "";
	}

	is_actionable(req) {
		const status = req.display_status || req.status || "";
		return (
			status === CashoutStatus.PENDING ||
			status === CashoutStatus.DRAFT ||
			status === CashoutStatus.IN_PROGRESS
		);
	}

	render_age_chip(req) {
		if (!this.is_actionable(req) || !req.creation) return "";
		const age = this.formatAge(req.creation);
		if (!age) return "";
		return `<span class="tr-age ${this.age_tone(req.creation)}">${age}</span>`;
	}

	load_pulse() {
		frappe.call({
			method: "admin_panel.api.pulse.get_transfer_pulse",
			callback: (res) => {
				this.pulse = res.message;
				this.render_pulse();
			},
			error: () => this.$cache.pulseTiles.hide(),
		});
	}

	render_pulse() {
		if (!this.pulse) return;
		const tiles = [];
		if (this.active_type === "fygaro") {
			const f = this.pulse.fygaro || {};
			tiles.push({
				label: "Fiat Received",
				value: f.fiat_received ?? 0,
				tone: f.fiat_received ? "warn" : "",
				sub: f.fiat_received ? "awaiting credit" : "queue clear",
			});
			tiles.push({ label: "Completed", value: f.completed ?? 0 });
			tiles.push({
				label: "Failed",
				value: f.failed ?? 0,
				tone: f.failed ? "bad" : "",
				sub: f.failed ? "needs review" : "none unresolved",
			});
		} else if (this.active_type === "bridge") {
			const b = this.pulse.bridge || {};
			tiles.push({ label: "Pending", value: b.pending ?? 0 });
			tiles.push({ label: "Fiat Received", value: b.fiat_received ?? 0 });
			tiles.push({
				label: "Failed",
				value: b.failed ?? 0,
				tone: b.failed ? "bad" : "",
				sub: b.failed ? "needs review" : "none unresolved",
			});
		} else {
			const c = this.pulse.cashouts || {};
			tiles.push({ label: "Pending", value: c.pending ?? 0 });
			tiles.push({ label: "In Progress", value: c.in_progress ?? 0 });
			tiles.push({
				label: "Oldest Waiting",
				value: c.oldest_at ? this.formatAge(c.oldest_at) : "\u2014",
				tone: c.oldest_at ? this.age_tone(c.oldest_at) : "",
				sub: c.oldest_id || "queue clear",
			});
		}
		this.$cache.pulseTiles.html(
			tiles
				.map(
					(t) => `
                <div class="tr-tile">
                    <div class="tr-tile-label">${this.escapeHtml(t.label)}</div>
                    <div class="tr-tile-value ${t.tone || ""}">${this.escapeHtml(
						String(t.value)
					)}</div>
                    ${t.sub ? `<div class="tr-tile-sub">${this.escapeHtml(t.sub)}</div>` : ""}
                </div>`
				)
				.join("")
		);
		this.$cache.pulseTiles.show();
	}

	load_requests() {
		// tab switches re-render tiles from the cached pulse immediately —
		// both datasets are in the payload; the fetch then freshens it
		if (this.pulse) this.render_pulse();
		this.load_pulse();
		if (this.active_type !== "cashout") {
			this.load_bridge_requests();
		} else {
			this.load_cashout_requests();
		}
	}

	canCreateCashout(req) {
		const status = req.status || "";
		const displayStatus = req.display_status || status;
		return (
			!req.payment_entry &&
			(req.docstatus === 0 ||
				status === CashoutStatus.PENDING ||
				status === CashoutStatus.DRAFT ||
				displayStatus === CashoutStatus.PENDING)
		);
	}

	canSettleCashout(req) {
		const status = req.status || "";
		const displayStatus = req.display_status || status;
		return (
			!req.payment_entry &&
			(status === CashoutStatus.IN_PROGRESS || displayStatus === CashoutStatus.IN_PROGRESS)
		);
	}

	render_cashout_actions(req, showActions = true) {
		const actions = [];
		if (showActions && this.canCreateCashout(req)) {
			actions.push(`
                <button class="modern-icon-btn modern-icon-btn-primary btn-quick-create" data-request-id="${this.escapeHtml(
					req.name
				)}" title="Create">
                    <i class="fa fa-plus"></i>
                </button>
            `);
		}
		if (showActions && this.canSettleCashout(req)) {
			actions.push(`
                <button class="modern-icon-btn modern-icon-btn-primary btn-quick-confirm" data-request-id="${this.escapeHtml(
					req.name
				)}" title="Confirm">
                    <i class="fa fa-key"></i>
                </button>
            `);
			actions.push(`
                <button class="modern-icon-btn modern-icon-btn-success btn-quick-complete" data-request-id="${this.escapeHtml(
					req.name
				)}" title="Mark as Complete">
                    <i class="fa fa-check"></i>
                </button>
            `);
		}

		return actions.length
			? `<td style="text-align:center;">${actions.join("")}</td>`
			: `<td style="text-align:center;"><span>-</span></td>`;
	}

	create_request_row(req, showActions = true) {
		const statusVal = req.display_status || req.status || CashoutStatus.PENDING;
		const statusBadge = getCashoutStatusBadgeClass(statusVal);
		const displayStatus = statusVal;
		const sendDisplay =
			req.send != null
				? `USD ${parseFloat(req.send).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-";
		const receiveJmdDisplay =
			req.receive_jmd != null
				? `JMD ${parseFloat(req.receive_jmd).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-";
		const actionsHtml = this.render_cashout_actions(req, showActions);

		const row = $(`
            <tr class="cashout-row" data-request-id="${this.escapeHtml(req.name)}">
                <td><strong>${this.escapeHtml(req.username || "-")}</strong></td>
                <td>${this.escapeHtml(this.formatPhone(req.phone_number))}</td>
                <td><strong>${sendDisplay}</strong></td>
                <td>${receiveJmdDisplay}</td>
                <td><span class="modern-badge ${this.escapeHtml(statusBadge)}">${this.escapeHtml(
			displayStatus
		)}</span></td>
                <td>${this.formatDateTime(req.creation)}${this.render_age_chip(req)}</td>
                ${actionsHtml}
            </tr>
        `);

		row.on("click", (e) => {
			if (!$(e.target).closest("button").length) {
				this.page.main.find(".cashout-row").removeClass("selected");
				row.addClass("selected");
				this.show_request_details(req);
			}
		});

		row.find(".btn-quick-create").on("click", (e) => {
			e.stopPropagation();
			this.create_cashout_request(req);
		});
		row.find(".btn-quick-confirm").on("click", (e) => {
			e.stopPropagation();
			this.confirm_cashout_payment(req);
		});
		row.find(".btn-quick-complete").on("click", (e) => {
			e.stopPropagation();
			this.complete_cashout(req);
		});

		return row;
	}

	create_bridge_request_row(req) {
		const statusVal = req.status || BridgeStatus.PENDING;
		const statusBadge = getBridgeStatusBadgeClass(statusVal);
		const amountDisplay = this.formatAmount(req.amount, req.currency);
		const failureDisplay = req.failure_reason ? this.escapeHtml(req.failure_reason) : "-";
		const requestId = req.request_id || req.name || "-";

		const row = $(`
            <tr class="bridge-row" data-request-id="${this.escapeHtml(req.name)}">
                <td><strong>${this.escapeHtml(requestId)}</strong></td>
                <td>${this.escapeHtml(req.transaction_type || "-")}</td>
                <td><strong>${this.escapeHtml(amountDisplay)}</strong></td>
                <td><span class="modern-badge ${statusBadge}">${this.escapeHtml(
			statusVal
		)}</span></td>
                <td>${failureDisplay}</td>
                <td>${this.formatDateTime(req.last_seen_at || req.modified || req.creation)}</td>
            </tr>
        `);

		row.on("click", () => {
			this.page.main.find(".bridge-row").removeClass("selected");
			row.addClass("selected");
			this.show_bridge_details(req);
		});

		return row;
	}

	go_to_page(page) {
		if (page < 1 || page > this.total_pages) return;
		this.current_page = page;
		this.load_requests();
	}

	load_cashout_requests() {
		this.$cache.requestsLoading.show();
		this.$cache.requestsTable.hide();
		this.$cache.noRequests.hide();
		this.$cache.requestDetails.hide();
		this.$cache.paginationControls.hide();

		frappe.call({
			method: "admin_panel.api.admin_api.get_cashout_requests",
			args: {
				status: this.$cache.filterStatus.val(),
				page: this.current_page,
				page_size: this.page_size,
			},
			callback: (response) => {
				this.$cache.requestsLoading.hide();
				const result = response.message || {};
				this.cashout_requests = result.data || [];
				this.total_count = result.total || 0;
				this.total_pages = result.total_pages || 1;
				this.current_page = result.page || 1;
				this.render_requests();
				this.update_pagination();
			},
			error: () => {
				this.$cache.requestsLoading.hide();
				frappe.show_alert(
					{ message: "Failed to load cashout requests", indicator: "red" },
					5
				);
			},
		});
	}

	load_bridge_requests() {
		this.$cache.requestsLoading.show();
		this.$cache.requestsTable.hide();
		this.$cache.noRequests.hide();
		this.$cache.requestDetails.hide();
		this.$cache.paginationControls.hide();

		frappe.call({
			method: "admin_panel.api.admin_api.get_bridge_transfer_requests",
			args: {
				status: this.$cache.filterStatus.val(),
				transaction_type: this.$cache.filterTransactionType.val(),
				provider: this.active_type === "fygaro" ? "Fygaro" : "Bridge",
				query: this.$cache.searchInput.val().trim(),
				page: this.current_page,
				page_size: this.page_size,
			},
			callback: (response) => {
				this.$cache.requestsLoading.hide();
				const result = response.message || {};
				this.bridge_requests = result.data || [];
				this.total_count = result.total || 0;
				this.total_pages = result.total_pages || 1;
				this.current_page = result.page || 1;
				this.render_requests();
				this.update_pagination();
			},
			error: () => {
				this.$cache.requestsLoading.hide();
				frappe.show_alert(
					{ message: "Failed to load Bridge transfer requests", indicator: "red" },
					5
				);
			},
		});
	}

	update_pagination() {
		if (this.total_count === 0) {
			this.$cache.paginationControls.hide();
			return;
		}

		this.$cache.paginationControls.css("display", "flex");

		const start = (this.current_page - 1) * this.page_size + 1;
		const end = Math.min(this.current_page * this.page_size, this.total_count);
		const main = this.page.main;

		main.find(".page-start").text(start);
		main.find(".page-end").text(end);
		main.find(".total-count").text(this.total_count);
		main.find(".current-page").text(this.current_page);
		main.find(".total-pages").text(this.total_pages);

		main.find(".btn-first-page, .btn-prev-page").prop("disabled", this.current_page <= 1);
		main.find(".btn-next-page, .btn-last-page").prop(
			"disabled",
			this.current_page >= this.total_pages
		);
	}

	render_requests() {
		this.$cache.requestsTbody.empty();
		this.render_table_header();
		const requests =
			this.active_type !== "cashout" ? this.bridge_requests : this.cashout_requests;

		if (requests.length === 0) {
			this.$cache.requestsTable.hide();
			this.$cache.noRequests.show();
			return;
		}

		this.$cache.requestsTable.show();
		this.$cache.noRequests.hide();

		requests.forEach((req) => {
			this.$cache.requestsTbody.append(
				this.active_type !== "cashout"
					? this.create_bridge_request_row(req)
					: this.create_request_row(req)
			);
		});
	}

	show_request_details(req) {
		if (this.active_type !== "cashout") {
			this.show_bridge_details(req);
			return;
		}

		this.selected_request = req;
		const panel = this.page.main.find(".request-details");
		panel.data("detail-mode", "cashout");
		panel
			.find(".modern-card-title")
			.html('<i class="fa fa-file-text-o" style="margin-right: 10px;"></i> Cashout Details');
		panel.find(".card-body").html(this.cashoutDetailsHtml);

		// User Information
		panel.find(".detail-username").text(req.username || "-");
		panel.find(".detail-fullname").text(req.full_name || "-");
		panel.find(".detail-phone").text(this.formatPhone(req.phone_number) || "-");
		panel.find(".detail-email").text(req.email || "-");

		// Cashout Information
		panel.find(".detail-offer-id").text(req.offer_id || "-");
		panel.find(".detail-wallet-id").text(req.wallet_id || "-");
		panel.find(".detail-send").text(
			req.send != null
				? `USD ${parseFloat(req.send).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-"
		);
		panel.find(".detail-flash-fee").text(
			req.flash_fee != null
				? `USD ${parseFloat(req.flash_fee).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-"
		);
		panel.find(".detail-exchange-rate").text(
			req.exchange_rate != null
				? parseFloat(req.exchange_rate).toLocaleString("en-US", {
						minimumFractionDigits: 4,
				  })
				: "-"
		);
		panel.find(".detail-receive-jmd").text(
			req.receive_jmd != null
				? `JMD ${parseFloat(req.receive_jmd).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-"
		);
		panel.find(".detail-receive-usd").text(
			req.receive_usd != null
				? `USD ${parseFloat(req.receive_usd).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "-"
		);
		if (req.journal_entry) {
			panel
				.find(".detail-journal-entry")
				.html(
					`<a class="detail-link" href="/app/journal-entry/${encodeURIComponent(
						req.journal_entry
					)}" target="_blank">${this.escapeHtml(req.journal_entry)}</a>`
				);
		} else {
			panel.find(".detail-journal-entry").text("-");
		}

		// Bank Account
		if (req.bank_account) {
			panel
				.find(".detail-bank-account")
				.html(
					`<a class="detail-link" href="/app/bank-account/${encodeURIComponent(
						req.bank_account
					)}" target="_blank">${this.escapeHtml(req.bank_account)}</a>`
				);
		} else {
			panel.find(".detail-bank-account").text("-");
		}
		panel.find(".detail-bank-name").text(req.bank_name || "-");
		panel.find(".detail-account-number").text(req.account_number || "-");
		panel.find(".detail-account-type").text(req.account_type || "-");

		// Payment Journal Entry section (shown only when recorded)
		const paymentSection = panel.find(".detail-payment-entry-section");
		if (req.payment_entry) {
			panel
				.find(".detail-payment-entry")
				.html(
					`<a class="detail-link" href="/app/journal-entry/${encodeURIComponent(
						req.payment_entry
					)}" target="_blank">${this.escapeHtml(req.payment_entry)}</a>`
				);
			panel
				.find(".detail-pe-amount")
				.text(
					req.pe_paid_amount != null
						? `${req.pe_currency || ""} ${parseFloat(
								req.pe_paid_amount
						  ).toLocaleString("en-US", { minimumFractionDigits: 2 })}`.trim()
						: "-"
				);
			panel
				.find(".detail-pe-date")
				.text(
					req.pe_posting_date ? frappe.datetime.str_to_user(req.pe_posting_date) : "-"
				);
			panel.find(".detail-pe-mode").text(req.pe_mode_of_payment || "-");
			paymentSection.show();
		} else {
			paymentSection.hide();
		}

		// Other Information
		panel
			.find(".detail-status")
			.html(
				`<span class="modern-badge ${getCashoutStatusBadgeClass(
					req.display_status || req.status
				)}">${req.display_status || req.status || "-"}</span>`
			);
		panel.find(".detail-request-id").text(req.name || "-");
		panel.find(".detail-submitted").text(this.formatDateTime(req.creation));
		panel.find(".detail-modified").text(this.formatDateTime(req.modified));
		panel.find(".detail-remarks").text(req.remarks || "-");

		const createBtn = panel.find(".btn-create-cashout");
		const confirmBtn = panel.find(".btn-confirm-payment");
		const completeBtn = panel.find(".btn-complete-cashout");
		createBtn.toggle(this.canCreateCashout(req));
		confirmBtn.toggle(this.canSettleCashout(req));
		completeBtn.toggle(this.canSettleCashout(req));

		panel.show();
	}

	set_cashout_action_buttons_disabled(disabled) {
		this.page.main
			.find(
				".btn-create-cashout, .btn-confirm-payment, .btn-complete-cashout, .btn-quick-create, .btn-quick-confirm, .btn-quick-complete"
			)
			.prop("disabled", disabled);
	}

	show_cashout_action_result(
		result,
		successTitle,
		fallbackSuccessMessage,
		fallbackErrorMessage
	) {
		if (result.success) {
			frappe.msgprint({
				title: successTitle,
				indicator: "green",
				message: result.message || fallbackSuccessMessage,
			});
			this.load_requests();
		} else {
			frappe.msgprint({
				title: "Error",
				indicator: "red",
				message: result.error || fallbackErrorMessage,
			});
			this.set_cashout_action_buttons_disabled(false);
		}
	}

	create_cashout_request(req) {
		if (!req) return;

		const sendDisplay =
			req.send != null
				? `USD ${parseFloat(req.send).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "this cashout";

		frappe.confirm(
			`Create cashout request for <strong>${this.escapeHtml(
				req.username
			)}</strong> worth <strong>${sendDisplay}</strong>?<br><br>This submits the Cashout and payable Journal Entry so the bank transfer can be settled.`,
			() => {
				this.set_cashout_action_buttons_disabled(true);

				frappe.call({
					method: "admin_panel.api.admin_api.create_cashout_request",
					args: { cashout_id: req.name },
					freeze: true,
					freeze_message: "Creating cashout request...",
					callback: (r) => {
						const result = r.message || {};
						this.show_cashout_action_result(
							result,
							"Cashout Created",
							"Cashout request is ready for settlement.",
							"Failed to create cashout request."
						);
					},
					error: (err) => {
						this.set_cashout_action_buttons_disabled(false);
						const msg =
							err?.responseJSON?.exception ||
							err?.responseJSON?.message ||
							"Failed to create cashout request";
						frappe.msgprint({ title: "Error", indicator: "red", message: msg });
					},
				});
			}
		);
	}

	confirm_cashout_payment(req) {
		if (!req) return;

		const dialog = new frappe.ui.Dialog({
			title: "Confirm Cashout Payment",
			fields: [
				{
					fieldname: "confirmation_code",
					fieldtype: "Data",
					label: "Bank Confirmation Code",
					reqd: 1,
				},
			],
			primary_action_label: "Confirm Payment",
			primary_action: (values) => {
				const code = (values.confirmation_code || "").trim();
				if (!code) {
					frappe.msgprint({
						title: "Confirmation Code Required",
						indicator: "red",
						message: "Enter the bank confirmation code before confirming the payment.",
					});
					return;
				}

				dialog.get_primary_btn().prop("disabled", true);
				this.set_cashout_action_buttons_disabled(true);

				frappe.call({
					method: "admin_panel.api.admin_api.confirm_cashout_payment",
					args: {
						cashout_id: req.name,
						confirmation_code: code,
					},
					freeze: true,
					freeze_message: "Confirming payment...",
					callback: (r) => {
						dialog.hide();
						const result = r.message || {};
						this.show_cashout_action_result(
							result,
							"Payment Confirmed",
							"Cashout payment confirmed successfully.",
							"Failed to confirm cashout payment."
						);
					},
					error: (err) => {
						dialog.get_primary_btn().prop("disabled", false);
						this.set_cashout_action_buttons_disabled(false);
						const msg =
							err?.responseJSON?.exception ||
							err?.responseJSON?.message ||
							"Failed to confirm cashout payment";
						frappe.msgprint({ title: "Error", indicator: "red", message: msg });
					},
				});
			},
		});
		dialog.show();
	}

	complete_cashout(req) {
		if (!req) return;

		const sendDisplay =
			req.send != null
				? `USD ${parseFloat(req.send).toLocaleString("en-US", {
						minimumFractionDigits: 2,
				  })}`
				: "this cashout";

		frappe.confirm(
			`Mark <strong>${this.escapeHtml(
				req.username
			)}</strong>'s <strong>${sendDisplay}</strong> cashout as complete?<br><br>This creates the payment Journal Entry if one does not already exist.`,
			() => {
				this.set_cashout_action_buttons_disabled(true);

				frappe.call({
					method: "admin_panel.api.admin_api.complete_cashout",
					args: { cashout_id: req.name },
					freeze: true,
					freeze_message: "Completing cashout...",
					callback: (r) => {
						const result = r.message || {};
						this.show_cashout_action_result(
							result,
							"Cashout Completed",
							"Cashout marked complete successfully.",
							"Failed to complete cashout."
						);
					},
					error: (err) => {
						this.set_cashout_action_buttons_disabled(false);
						const msg =
							err?.responseJSON?.exception ||
							err?.responseJSON?.message ||
							"Failed to complete cashout";
						frappe.msgprint({ title: "Error", indicator: "red", message: msg });
					},
				});
			}
		);
	}

	record_payment_entry(req) {
		this.complete_cashout(req);
	}

	show_bridge_details(req) {
		this.selected_request = req;
		const panel = this.page.main.find(".request-details");
		panel.data("detail-mode", "bridge");
		panel
			.find(".modern-card-title")
			.html(
				req.provider === "Fygaro"
					? '<i class="fa fa-credit-card" style="margin-right: 10px;"></i> Card Top-Up Details'
					: '<i class="fa fa-exchange" style="margin-right: 10px;"></i> Bridge Transfer Details'
			);

		panel.find(".card-body").html(`
            <div class="detail-section mb-4">
                <h6 class="section-header">
                    <i class="fa fa-info-circle" style="margin-right: 8px; color: var(--color-primary);"></i>
                    Request Summary
                </h6>
                <div class="row">
                    <div class="col-md-6">
                        ${this.renderDetailItem("Request ID", req.request_id || req.name)}
                        ${this.renderDetailItem("Transaction Type", req.transaction_type)}
                        ${this.renderDetailItem("Provider", req.provider || "Bridge")}
                        ${this.renderDetailItem(
							"Status",
							`<span class="modern-badge ${getBridgeStatusBadgeClass(
								req.status
							)}">${this.escapeHtml(req.status || "-")}</span>`,
							true
						)}
                    </div>
                    <div class="col-md-6">
                        ${this.renderDetailItem(
							"Amount",
							this.formatAmount(req.amount, req.currency),
							false,
							true
						)}
                        ${this.renderDetailItem("Asset", req.asset)}
                        ${this.renderDetailItem("Network", req.network)}
                    </div>
                </div>
            </div>

            <div class="detail-section mb-4">
                <h6 class="section-header">
                    <i class="fa fa-link" style="margin-right: 8px; color: var(--color-primary);"></i>
                    References
                </h6>
                <div class="row">
                    <div class="col-md-6">
                        ${this.renderDetailItem(
							"Bridge Document",
							this.renderDocLink("bridge-transfer-request", req.name),
							true
						)}
                        ${this.renderDetailItem("Bridge Transfer ID", req.bridge_transfer_id)}
                        ${this.renderDetailItem("Bridge Customer ID", req.bridge_customer_id)}
                        ${this.renderDetailItem("IBEX TX Hash", req.ibex_tx_hash)}
                    </div>
                    <div class="col-md-6">
                        ${this.renderDetailItem("Account ID", req.account_id)}
                        ${this.renderDetailItem("Wallet ID", req.wallet_id)}
                        ${this.renderDetailItem("Address", req.address)}
                    </div>
                </div>
            </div>

            <div class="detail-section mb-4">
                <h6 class="section-header">
                    <i class="fa fa-clock-o" style="margin-right: 8px; color: var(--color-primary);"></i>
                    Event Trace
                </h6>
                <div class="row">
                    <div class="col-md-6">
                        ${this.renderDetailItem("Source Event ID", req.source_event_id)}
                        ${this.renderDetailItem("Source Event Type", req.source_event_type)}
                        ${this.renderDetailItem("Source Systems Seen", req.source_systems_seen)}
                    </div>
                    <div class="col-md-6">
                        ${this.renderDetailItem(
							"First Seen",
							this.formatDateTime(req.first_seen_at)
						)}
                        ${this.renderDetailItem(
							"Last Seen",
							this.formatDateTime(req.last_seen_at)
						)}
                        ${this.renderDetailItem(
							"Last Modified",
							this.formatDateTime(req.modified)
						)}
                    </div>
                </div>
            </div>

            <div class="detail-section mb-4">
                <h6 class="section-header">
                    <i class="fa fa-exclamation-circle" style="margin-right: 8px; color: var(--color-error);"></i>
                    Failure / Payload
                </h6>
                ${this.renderDetailItem("Failure Reason", req.failure_reason)}
                <details>
                    <summary class="detail-link" style="cursor:pointer;">Raw Payload</summary>
                    <pre style="margin-top: 12px; white-space: pre-wrap; word-break: break-word; background: var(--color-background); border: 1px solid var(--color-border01); border-radius: 8px; padding: 12px;">${this.escapeHtml(
						req.raw_payload_json || "-"
					)}</pre>
                </details>
            </div>
        `);

		panel.show();
	}

	close_details() {
		this.$cache.requestDetails.hide();
		this.selected_request = null;
	}

	search() {
		const input = this.$cache.searchInput.val().trim();
		if (!input) {
			frappe.show_alert({ message: "Please enter a search value", indicator: "orange" }, 3);
			return;
		}

		if (this.active_type !== "cashout") {
			this.current_page = 1;
			this.load_bridge_requests();
			return;
		}

		this.$cache.searchLoading.show();
		this.$cache.searchError.hide();
		this.$cache.requestDetails.hide();

		frappe.call({
			method: "admin_panel.api.admin_api.search_cashout_account",
			args: { id: input },
			callback: (res) => {
				this.$cache.searchLoading.hide();
				const results = res.message;
				if (!results || results.error) {
					this.show_search_error(results?.error || "Account not found");
					return;
				}
				this.show_search_results(Array.isArray(results) ? results : []);
			},
			error: (e) => {
				this.$cache.searchLoading.hide();
				this.show_search_error(e.message || "Account not found");
			},
		});
	}

	show_search_results(results) {
		this.$cache.requestsTbody.empty();
		this.render_table_header();
		this.$cache.searchError.hide();
		this.$cache.paginationControls.hide();

		if (!results || !results.length) {
			this.$cache.noRequests.show();
			this.$cache.requestsTable.hide();
			this.show_search_error("No cashout requests found");
			return;
		}

		this.$cache.noRequests.hide();
		this.$cache.requestsTable.show();

		results.forEach((req) => {
			this.$cache.requestsTbody.append(this.create_request_row(req));
		});
	}

	show_search_error(msg) {
		this.$cache.searchLoading.hide();
		this.$cache.searchError.show();
		this.page.main.find(".error-message").text(msg);
	}

	formatPhone(phone) {
		if (!phone) return "-";
		return phone.replace(/^(\d{3})(\d{3})(\d{2})(\d{2})$/, "+$1 $2 $3 $4");
	}

	formatDateTime(dt) {
		return dt ? frappe.datetime.str_to_user(dt) : "-";
	}

	formatAmount(amount, currency) {
		if (amount === null || amount === undefined || amount === "") return "-";
		const value = parseFloat(amount);
		if (Number.isNaN(value)) return `${currency || ""} ${amount}`.trim();
		return `${currency || ""} ${value.toLocaleString("en-US", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 8,
		})}`.trim();
	}

	renderDetailItem(label, value, allowHtml = false, isAmount = false) {
		const displayValue = allowHtml ? value || "-" : this.escapeHtml(value || "-");
		const valueClass = isAmount ? "detail-value amount-display" : "detail-value";
		return `
            <div class="detail-item">
                <span class="detail-label">${this.escapeHtml(label)}</span>
                <span class="${valueClass}">${displayValue}</span>
            </div>
        `;
	}

	renderDocLink(route, name) {
		if (!name) return "-";
		return `<a class="detail-link" href="/app/${route}/${encodeURIComponent(
			name
		)}" target="_blank">${this.escapeHtml(name)}</a>`;
	}

	escapeHtml(value) {
		if (value === null || value === undefined || value === "") return "-";
		return $("<div>").text(String(value)).html();
	}
}

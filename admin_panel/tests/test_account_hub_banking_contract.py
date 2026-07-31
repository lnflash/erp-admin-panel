"""Contract tests for the Account Hub Banking tab + banking API wiring."""

from pathlib import Path

ADMIN_PANEL = Path(__file__).resolve().parents[1]
API = ADMIN_PANEL / "api"


def read(path):
	return path.read_text()


BANKING_PY = read(API / "banking.py")
BRIDGE_CLIENT_PY = read(API / "bridge_client.py")
ACCOUNT_HUB_JS = read(ADMIN_PANEL / "admin_panel" / "page" / "account_hub" / "account_hub.js")


def test_banking_endpoint_is_whitelisted_and_admin_gated():
	"""Full bank account numbers are PII — whitelist alone would expose them
	to any logged-in user."""
	stack = "@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef get_customer_banking("
	assert stack in BANKING_PY


def test_banking_tab_sits_between_overview_and_wallets():
	"""The Banking tab button AND its content panel must both sit between
	Overview and Wallets — panels follow tab order in this page."""
	for needle_set in (
		('data-tab="overview">Overview<', 'data-tab="banking">Banking<', 'data-tab="wallets">Wallets<'),
		(
			'class="ah-tab-content active" data-tab="overview"',
			'class="ah-tab-content" data-tab="banking"',
			'class="ah-tab-content" data-tab="wallets"',
		),
	):
		positions = [ACCOUNT_HUB_JS.index(n) for n in needle_set]
		assert positions == sorted(positions), f"out of order: {needle_set}"


def test_js_wires_banking_endpoint_and_populates_on_select():
	assert 'method: "admin_panel.api.banking.get_customer_banking"' in ACCOUNT_HUB_JS
	assert "this.populate_banking(account);" in ACCOUNT_HUB_JS


def test_js_guards_stale_responses():
	"""Switching customers while banking data is in flight must not paint the
	previous customer's bank details into the new customer's tab."""
	assert ACCOUNT_HUB_JS.count("if (this.current_account !== account) return;") >= 2


def test_erp_lookup_mirrors_cashout_ownership_filter():
	"""Bank accounts are resolved exactly the way Cashout.validate does —
	party_type Customer + party — never by account number or name."""
	assert '"party_type": "Customer", "party": erp_party' in BANKING_PY


def test_bridge_side_is_partial_tolerant():
	"""A Bridge/mongo failure must degrade in-band, not 500 the whole tab —
	ERP bank accounts still render when Bridge is down or unconfigured."""
	assert "except (BridgeApiError, ValueError) as e:" in BANKING_PY
	assert '"error": f"mongo lookup failed: {e}"' in BANKING_PY


def test_bridge_banking_paths_are_percent_encoded():
	for fn in ("list_virtual_accounts", "list_external_accounts"):
		assert f"def {fn}" in BRIDGE_CLIENT_PY
	assert BRIDGE_CLIENT_PY.replace('"', "'").count("quote(str(customer_id), safe='')") >= 3


def test_bridge_customer_id_validated_before_use():
	assert "CUSTOMER_ID_RE.fullmatch(customer_id)" in BANKING_PY

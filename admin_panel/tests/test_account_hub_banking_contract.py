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


# ---- Editable Banking tab (admin write endpoints) ---------------------------


def test_write_endpoints_are_whitelisted_and_admin_gated():
	"""Bank-account writes move real cashout rails — whitelist alone would let
	any logged-in user redirect a customer's payouts."""
	for fn in ("add_bank_account", "update_bank_account", "set_default_bank_account"):
		stack = f"@frappe.whitelist()\n@require_admin()\n@handle_api_errors\ndef {fn}("
		assert stack in BANKING_PY, f"{fn} is missing the whitelist/require_admin/handle_api_errors stack"


def test_writes_verify_ownership_before_touching_records():
	"""Every mutation resolves the record through the single ownership gate
	(mirror of Cashout.validate): party_type Customer + party must match."""
	assert 'bank_account.party_type != "Customer" or bank_account.party != erp_party' in BANKING_PY
	assert BANKING_PY.count("_owned_bank_account(") >= 3  # definition + update + set_default


def test_writes_enforce_cashout_safe_fields():
	"""flash's bankAccounts GraphQL has NonNull fields and cashout only accepts
	JMD/USD + Chequing/Savings — a single bad value blanks the customer's whole
	bank list in the app, so every write goes through the validator."""
	assert 'ALLOWED_CURRENCIES = ("JMD", "USD")' in BANKING_PY
	assert 'ALLOWED_ACCOUNT_TYPES = ("Chequing", "Savings")' in BANKING_PY
	assert BANKING_PY.count("_validate_bank_fields(") >= 3  # definition + add + update


def test_account_number_collisions_rejected():
	assert 'frappe.db.exists("Bank Account", {"bank_account_no": account_number})' in BANKING_PY
	assert '"bank_account_no": account_number, "name": ("!=", bank_account.name)' in BANKING_PY


def test_update_never_touches_identity_or_default():
	"""Mirror of the ENG-509 approve flow: an edit patches details in place —
	the doc name and is_default flag are owned by other flows."""
	body = BANKING_PY.split("def update_bank_account(", 1)[1].split("@frappe.whitelist()", 1)[0]
	assert ".is_default" not in body
	assert "is_default =" not in body
	assert '"is_default"' not in body
	assert "rename" not in body


def test_every_write_is_audited():
	assert BANKING_PY.count("audit_log(") >= 3
	for action in ("add_bank_account", "update_bank_account", "set_default_bank_account"):
		assert f'"{action}"' in BANKING_PY, f"audit_log entry for {action} missing"
	assert "from .auth import audit_log, require_admin" in BANKING_PY


def test_bank_master_created_before_linking():
	"""Mirror of _create_erp_records — linking to a missing Bank master fails."""
	assert BANKING_PY.count("_ensure_bank_master(") >= 3  # definition + add + update


def test_js_wires_banking_write_endpoints_and_buttons():
	for method in ("add_bank_account", "update_bank_account", "set_default_bank_account"):
		assert f"admin_panel.api.banking.{method}" in ACCOUNT_HUB_JS
	for hook in ("banking-add-btn", "banking-edit-btn", "banking-default-btn"):
		assert hook in ACCOUNT_HUB_JS
	# Mutations repaint the Banking tab, not the whole account.
	assert "this.populate_banking(account);" in ACCOUNT_HUB_JS


def test_second_account_at_same_bank_gets_disambiguated_name():
	"""ERPNext autonames Bank Accounts "{account_name} - {bank}" — without
	disambiguation, a customer's second account at the same bank collides on
	the doc name and the insert dies."""
	assert 'frappe.db.exists("Bank Account", f"{holder} - {bank_name}")' in BANKING_PY
	assert 'f"{holder} (…{account_number[-4:]})"' in BANKING_PY


def test_js_never_interpolates_bank_name_raw():
	"""The edit-dialog title must escape the bank name — it is the only place
	admin-entered data could reach a dialog title unescaped."""
	assert "${existing.bank" not in ACCOUNT_HUB_JS


def test_js_error_chain_surfaces_envelope_errors():
	"""handle_api_errors failures arrive as HTTP 500 with responseJSON.error —
	without it in the chain, a mongo/Bridge outage shows a generic message."""
	assert "err?.responseJSON?.error" in ACCOUNT_HUB_JS

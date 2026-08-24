"""Contract tests for the support lookup relay endpoint.

The endpoint module imports frappe, so these are source-level checks in the
established contract-test style: they pin the auth gate, the upstream query's
field set (a privacy boundary — the response leaves the cluster), and the
role provisioning, without a Frappe runtime.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "admin_panel" / "api"
SETUP_PY = REPO_ROOT / "admin_panel" / "admin_panel" / "setup.py"

ENDPOINT_SRC = (API_DIR / "support_lookup.py").read_text()
CLIENT_SRC = (API_DIR / "graphql_client.py").read_text()


def test_endpoint_is_whitelisted_behind_the_role_gate():
	# Decorator order matters: whitelist -> role gate -> error handler -> fn.
	m = re.search(
		r"@frappe\.whitelist\(\)\s*\n"
		r"@require_roles\(SUPPORT_LOOKUP_ROLES\)\s*\n"
		r"@handle_api_errors\s*\n"
		r"def get_support_contact_by_npub\(",
		ENDPOINT_SRC,
	)
	assert m, "get_support_contact_by_npub must be whitelisted behind SUPPORT_LOOKUP_ROLES"


def test_role_gate_includes_the_dedicated_service_role():
	assert re.search(
		r"SUPPORT_LOOKUP_ROLES\s*=\s*\[\"Support Lookup\", \*ADMIN_ROLES\]", ENDPOINT_SRC
	)


def test_setup_provisions_the_support_lookup_role_without_desk_access():
	setup_src = SETUP_PY.read_text()
	assert re.search(r"\(\"Support Lookup\",\s*0\)", setup_src), (
		"ensure_roles must create the Support Lookup role with desk_access=0"
	)


def test_query_targets_account_details_by_npub():
	assert "accountDetailsByNpub(npub: $npub)" in ENDPOINT_SRC


def test_query_never_requests_financial_fields():
	# The response leaves the cluster for the support droplet. Identity only.
	query = re.search(
		r"SUPPORT_CONTACT_BY_NPUB_QUERY\s*=\s*\"\"\"(.*?)\"\"\"", ENDPOINT_SRC, re.S
	).group(1)
	for forbidden in ("wallets", "balance", "capabilities", "erpParty", "coordinates"):
		assert forbidden not in query, f"support lookup query must not request {forbidden}"


def test_upstream_jwt_roles_stay_read_narrow():
	# Accounts Manager is what the flash admin shield requires; the frappe-side
	# gate is the boundary. System Manager would be gratuitous power.
	assert re.search(r"UPSTREAM_JWT_ROLES\s*=\s*\(\"Accounts Manager\",\)", ENDPOINT_SRC)
	assert "System Manager" not in ENDPOINT_SRC


def test_graphql_client_supports_fixed_jwt_roles():
	assert re.search(r"def __init__\(self, jwt_roles=None\):", CLIENT_SRC)
	assert re.search(
		r"self\._jwt_roles or \(frappe\.get_roles\(user\) if user else \[\]\)", CLIENT_SRC
	)

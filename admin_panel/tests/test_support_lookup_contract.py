"""Source-level contract tests for the support lookup relay endpoint.

Behavioral coverage of the endpoint lives in test_support_lookup.py (stubbed
frappe, real function calls) and of the JWT it mints in
test_graphql_client_extract.py. What is left here is the set of invariants no
call to the function can observe: the decorator stack, the upstream query's
field set (a privacy boundary — the response leaves the cluster), the Role
provisioning in setup.py, and the repo-wide confinement of the ``jwt_roles``
privilege-forging knob.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "admin_panel"
API_DIR = APP_DIR / "api"
SETUP_PY = APP_DIR / "admin_panel" / "setup.py"

ENDPOINT_SRC = (API_DIR / "support_lookup.py").read_text()
CLIENT_SRC = (API_DIR / "graphql_client.py").read_text()

# jwt_roles mints upstream privilege from a frappe role that may have none of
# it, so every use is a security decision. graphql_client.py defines it;
# support_lookup.py is the one reviewed caller. Anything else must be reviewed
# before it is added here.
JWT_ROLES_ALLOWED_FILES = {"graphql_client.py", "support_lookup.py"}


def test_endpoint_is_whitelisted_behind_the_rate_limit_and_role_gate():
	# Decorator order matters: whitelist -> rate limit -> role gate -> error
	# handler -> fn.
	m = re.search(
		r"@frappe\.whitelist\(\)\s*\n"
		r"@rate_limit\([^)]*\)\s*\n"
		r"@require_roles\(SUPPORT_LOOKUP_ROLES\)\s*\n"
		r"@handle_api_errors\s*\n"
		r"def get_support_contact_by_npub\(",
		ENDPOINT_SRC,
	)
	assert m, "get_support_contact_by_npub must be rate limited and whitelisted behind SUPPORT_LOOKUP_ROLES"


def test_rate_limit_is_ip_bucketed_not_npub_bucketed():
	# frappe buckets on "<ip>:<key>" when a key is given, which would hand an
	# enumerator a fresh allowance per npub — the opposite of the point.
	decorator = re.search(r"@rate_limit\(([^)]*)\)", ENDPOINT_SRC).group(1)
	assert "ip_based=True" in decorator
	assert "key=" not in decorator


def test_role_gate_includes_the_dedicated_service_role():
	assert re.search(r"SUPPORT_LOOKUP_ROLES\s*=\s*\[\"Support Lookup\", \*ADMIN_ROLES\]", ENDPOINT_SRC)


def test_setup_provisions_the_support_lookup_role_without_desk_access():
	setup_src = SETUP_PY.read_text()
	assert re.search(
		r"\(\"Support Lookup\",\s*0\)", setup_src
	), "ensure_roles must create the Support Lookup role with desk_access=0"


def test_query_targets_account_details_by_npub():
	assert "accountDetailsByNpub(npub: $npub)" in ENDPOINT_SRC


def test_query_never_requests_financial_fields():
	# The response leaves the cluster for the support droplet. Identity only.
	query = re.search(r"SUPPORT_CONTACT_BY_NPUB_QUERY\s*=\s*\"\"\"(.*?)\"\"\"", ENDPOINT_SRC, re.S).group(1)
	for forbidden in ("wallets", "balance", "capabilities", "erpParty", "coordinates"):
		assert forbidden not in query, f"support lookup query must not request {forbidden}"


def test_upstream_jwt_roles_stay_read_narrow():
	# Accounts Manager is what the flash admin shield requires; the frappe-side
	# gate is the boundary. System Manager would be gratuitous power. Assert on
	# the literal itself, not the file — prose mentioning the role is fine.
	literal = re.search(r"UPSTREAM_JWT_ROLES\s*=\s*\(([^)]*)\)", ENDPOINT_SRC)
	assert literal, "UPSTREAM_JWT_ROLES must be a tuple literal"
	roles = re.findall(r"\"([^\"]+)\"", literal.group(1))
	assert roles == ["Accounts Manager"]


def test_jwt_roles_stays_confined_to_the_reviewed_call_site():
	# Repo-wide, not one file: any endpoint may pass jwt_roles=("System
	# Manager",) and mint full upstream admin from a frappe role with no desk
	# access. New call sites must be reviewed into JWT_ROLES_ALLOWED_FILES.
	offenders = sorted(
		str(p.relative_to(REPO_ROOT))
		for p in APP_DIR.rglob("*.py")
		if "tests" not in p.parts and p.name not in JWT_ROLES_ALLOWED_FILES and "jwt_roles" in p.read_text()
	)
	assert not offenders, (
		"jwt_roles forges upstream privilege independent of the caller's frappe "
		f"roles; unreviewed use in: {', '.join(offenders)}"
	)


def test_graphql_client_supports_fixed_jwt_roles():
	assert re.search(r"def __init__\(self, jwt_roles=None\):", CLIENT_SRC)
	assert re.search(r"self\._jwt_roles or \(frappe\.get_roles\(user\) if user else \[\]\)", CLIENT_SRC)

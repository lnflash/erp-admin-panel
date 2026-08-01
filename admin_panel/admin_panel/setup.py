import frappe

from admin_panel.admin_panel.doctype.allowed_country.seed import seed_allowed_countries


def after_migrate():
	ensure_roles()
	ensure_service_account_roles()
	sync_pages()
	delete_legacy_pages()
	seed_allowed_countries()


def ensure_roles():
	"""Create custom roles referenced by RBAC (admin_panel.api.auth) if missing.

	The Account Upgrade Request permissions and the require_admin decorator
	reference "Flash Admin"; without the Role record it cannot be assigned.
	"""
	for role_name in ("Flash Admin",):
		if not frappe.db.exists("Role", role_name):
			role = frappe.new_doc("Role")
			role.role_name = role_name
			role.desk_access = 1
			role.flags.ignore_permissions = True
			role.insert()
	frappe.db.commit()


# One Flash backend service-account User per environment (prod / test). Whichever
# exists on this site gets the roles; the other is simply absent. Optional
# `flash_service_account` site_config key overrides the list without a code change.
SERVICE_ACCOUNT_CANDIDATES = (
	"flash_sa@getflash.io",
	"flash-service-account@getflash.io",
)

# Flash Admin gates the admin_panel custom doctypes (Account Upgrade Request,
# Bank Account Update Request); Accounts Manager gates the standard ERPNext
# doctypes the flash backend reads (Bank Account, Currency Exchange, Customer,
# Journal Entry, Bank). Losing either breaks a slice of cashout/upgrade with 403s.
SERVICE_ACCOUNT_ROLES = ("Flash Admin", "Accounts Manager")


def ensure_service_account_roles():
	"""Idempotently re-assert the Flash backend service account's roles.

	Role *definitions* ship in doctype JSON (versioned); the role *assignment* on
	the User record is not, and has silently dropped before — breaking cashout and
	the upgrade flow with 403s. This runs on every ``bench migrate`` (via
	after_migrate), so the assignment self-heals on every deploy.
	"""
	configured = frappe.conf.get("flash_service_account")
	candidates = [configured] if configured else list(SERVICE_ACCOUNT_CANDIDATES)
	for email in candidates:
		if not email or not frappe.db.exists("User", email):
			continue
		existing = {
			r.role
			for r in frappe.get_all(
				"Has Role",
				filters={"parent": email, "parenttype": "User"},
				fields=["role"],
			)
		}
		missing = [r for r in SERVICE_ACCOUNT_ROLES if r not in existing]
		if not missing:
			continue  # already converged — no needless User.save() this migrate
		frappe.get_doc("User", email).add_roles(*missing)
	frappe.db.commit()


def sync_pages():
	pages = [
		{
			"name": "alert-users",
			"title": "Alert Users",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "account-management",
			"title": "Account Management",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "account-hub",
			"title": "Account Hub",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "admin-dashboard",
			"title": "Dashboard",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "transfer-requests",
			"title": "Transfer Requests",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "system-accounts",
			"title": "System Accounts",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "wallet-census",
			"title": "Wallet Census",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
		{
			"name": "referral-rewards",
			"title": "Referral Rewards",
			"module": "Admin Panel",
			"standard": "Yes",
			"roles": [],
		},
	]

	for page_data in pages:
		name = page_data["name"]
		if frappe.db.exists("Page", name):
			doc = frappe.get_doc("Page", name)
			doc.update(page_data)
		else:
			doc = frappe.new_doc("Page")
			doc.update(page_data)

		doc.flags.ignore_permissions = True
		doc.flags.ignore_validate = True
		doc.save()

	frappe.db.commit()


def delete_legacy_pages():
	if frappe.db.exists("Page", "cashout-requests"):
		frappe.delete_doc("Page", "cashout-requests", ignore_permissions=True, force=True)
		frappe.db.commit()

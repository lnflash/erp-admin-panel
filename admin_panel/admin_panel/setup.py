import frappe

from admin_panel.admin_panel.doctype.allowed_country.seed import seed_allowed_countries


def after_migrate():
	ensure_roles()
	ensure_service_account_roles()
	sync_pages()
	delete_legacy_pages()
	ensure_desk_home_page()
	ensure_public_assets_symlink()
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
			# The ONLY page here that carries roles, and it is load-bearing:
			# this is the desk home page (see ensure_desk_home_page), and
			# boot.add_home_page falls back to the Workspaces view when
			# Page.is_permitted() says no. Role-gating the page is therefore
			# what gives every non-admin desk user their normal landing page
			# back, with no separate opt-out list to maintain. Mirrors
			# admin_panel.api.auth.ADMIN_ROLES.
			"roles": [
				{"role": "System Manager"},
				{"role": "Accounts Manager"},
				{"role": "Flash Admin"},
			],
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
		{
			"name": "bridge-kyc",
			"title": "Bridge KYC",
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


# The Page that desk users land on at /app. Overridable per-site with the
# `desk_home_page` site_config key; set it to an empty value to opt out and
# keep Frappe's stock Workspaces landing.
DESK_HOME_PAGE = "admin-dashboard"


def ensure_desk_home_page():
	"""Make the Admin Dashboard the desk landing page.

	``frappe.boot.add_home_page`` reads the GLOBAL default ``desktop:home_page``
	and hands it to ``frappe.desk.desk_page.get``, falling back to the
	``Workspaces`` view on DoesNotExistError or PermissionError. So this one
	default plus the Page's roles is the whole mechanism: admins get the
	dashboard, everyone else keeps Workspaces, and no user record is touched.

	Re-asserted on every migrate so a restored or re-seeded site converges,
	and skipped when already correct so a deploy is a no-op.
	"""
	configured = frappe.conf.get("desk_home_page", DESK_HOME_PAGE)
	current = frappe.db.get_default("desktop:home_page")
	if not configured:
		# Opting out must also undo the default a previous migrate of this
		# app set — otherwise the opt-out is inert on any site that has
		# migrated once, and admins keep landing on the dashboard the
		# operator just asked to be rid of. Only our own value is cleared;
		# a page the operator chose themselves is left alone.
		if current == DESK_HOME_PAGE:
			frappe.defaults.clear_default("desktop:home_page", parent="__default")
			frappe.db.commit()
		return
	if current == configured:
		return
	frappe.db.set_default("desktop:home_page", configured)
	frappe.db.commit()


def _ensure_symlink(link, target):
	"""Idempotently point ``link`` at ``target``; leave a real directory alone.

	Pure helper (no frappe) so the branch logic is testable with tmp paths.
	Returns what it did: "created", "repointed", "ok", or "kept-dir".
	"""
	import os

	if os.path.islink(link):
		if os.readlink(link) == target:
			return "ok"
		os.remove(link)
		os.symlink(target, link)
		return "repointed"
	if os.path.isdir(link):
		# Some setups copy assets instead of symlinking; don't fight them.
		return "kept-dir"
	os.symlink(target, link)
	return "created"


def ensure_public_assets_symlink():
	"""Make ``sites/assets/admin_panel`` exist on the runtime volume.

	nginx serves ``/assets`` with ``root .../sites`` (``try_files $uri``), and
	in the k8s deployment ``sites/`` is the shared PVC mounted OVER the
	image's own sites dir. ``bench build`` wrote the assets symlink into the
	image layer at build time — exactly where nginx never looks — so the
	app's public files 404'd on every environment while frappe/erpnext
	(provisioned onto the volume at install) served fine. Runs on every
	migrate, which executes with the PVC mounted; harmless on a plain bench
	where the link already exists and is correct.
	"""
	import os

	bench_path = frappe.utils.get_bench_path()
	_ensure_symlink(
		os.path.join(bench_path, "sites", "assets", "admin_panel"),
		os.path.join(bench_path, "apps", "admin_panel", "admin_panel", "public"),
	)

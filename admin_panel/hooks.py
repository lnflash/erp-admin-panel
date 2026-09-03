app_name = "admin_panel"
app_title = "Admin Panel"
app_publisher = "Ben Hindman"
app_description = "Tool for admin users to manage the Flash application"
app_email = "bhindman@proton.me"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "admin_panel",
# 		"logo": "/assets/admin_panel/logo.png",
# 		"title": "Admin Panel",
# 		"route": "/admin_panel",
# 		"has_permission": "admin_panel.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/admin_panel/css/admin_panel.css"
# Desk-wide: the Back-to-Dashboard button on every dashboard destination.
app_include_js = "/assets/admin_panel/js/back_to_dashboard.js"

# include js, css files in header of web template
# web_include_css = "/assets/admin_panel/css/admin_panel.css"
# web_include_js = "/assets/admin_panel/js/admin_panel.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "admin_panel/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "admin_panel/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "admin_panel.utils.jinja_methods",
# 	"filters": "admin_panel.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "admin_panel.install.before_install"
# after_install = "admin_panel.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "admin_panel.uninstall.before_uninstall"
# after_uninstall = "admin_panel.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "admin_panel.utils.before_app_install"
# after_app_install = "admin_panel.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "admin_panel.utils.before_app_uninstall"
# after_app_uninstall = "admin_panel.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "admin_panel.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------
# Only `daily` is enabled. These fire ONLY when a scheduler worker is running
# (`bench schedule` / the scheduler container) and the site's scheduler is not
# paused — without one post_daily_anchor never runs and nothing warns about it.

scheduler_events = {
	"daily": [
		# Publish the compliance ledger's chain head to the ops Discord webhook
		# (site_config `ops_discord_webhook_url`); no-op when unset.
		"admin_panel.api.compliance_audit.post_daily_anchor",
	],
}

# scheduler_events = {
# 	"all": [
# 		"admin_panel.tasks.all"
# 	],
# 	"daily": [
# 		"admin_panel.tasks.daily"
# 	],
# 	"hourly": [
# 		"admin_panel.tasks.hourly"
# 	],
# 	"weekly": [
# 		"admin_panel.tasks.weekly"
# 	],
# 	"monthly": [
# 		"admin_panel.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "admin_panel.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "admin_panel.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "admin_panel.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["admin_panel.utils.before_request"]
# after_request = ["admin_panel.utils.after_request"]

# Job Events
# ----------
# before_job = ["admin_panel.utils.before_job"]
# after_job = ["admin_panel.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"admin_panel.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

after_migrate = ["admin_panel.admin_panel.setup.after_migrate"]

doctype_dashboards = {
	"Allowed Country": "admin_panel.admin_panel.doctype.allowed_country.allowed_country_dashboard",
}

fixtures = [
	{"doctype": "Workspace", "filters": [["module", "=", "Admin Panel"]]},
	{"doctype": "Client Script", "filters": [["module", "=", "Admin Panel"]]},
	{"doctype": "Custom Field", "filters": [["dt", "=", "Bank Account"], ["fieldname", "=", "currency"]]},
	{"doctype": "Number Card", "filters": [["module", "=", "Admin Panel"]]},
	{"doctype": "Dashboard Chart", "filters": [["module", "=", "Admin Panel"]]},
]

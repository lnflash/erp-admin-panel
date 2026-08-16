import frappe
from frappe.model.document import Document


class FeeDiscount(Document):
	def before_insert(self):
		# Resolve the username against flash BEFORE set_new_name runs, so the
		# document name (autoname field:username) is built from the canonical
		# spelling — _sync_autoname_field would otherwise revert a validate()-
		# time correction back to the typo'd name on save.
		self._sync_username_with_flash()

	def validate(self):
		# Defense-in-depth at the point of entry. The flash backend re-validates
		# (and fails open to a 0% discount on malformed rows), but this row
		# directly changes what a named user pays without further review, so
		# refuse obviously-wrong values here.
		self.username = (self.username or "").strip()
		if not self.username:
			frappe.throw("Username is required.")

		# In-place username edits on a saved row can NEVER work with autoname
		# field:username: Frappe v15's _sync_autoname_field reverts the field
		# to self.name BEFORE validate_set_only_once compares, so a scripted /
		# REST edit would "succeed" while the username silently snaps back —
		# the caller believes the discount moved; the old user keeps it.
		# (set_only_once's real effect is only making the field read-only in
		# Desk.) Reject loudly and point at the one path that actually works.
		if not self.is_new() and self.has_value_changed("username"):
			frappe.throw(
				"Username cannot be edited in place — use the Rename dialog, "
				"which verifies the new username against flash."
			)

		value = frappe.utils.flt(self.discount_percent)
		if value < 0 or value > 100:
			frappe.throw("Flash Fee Discount (%) must be between 0 and 100.")

		if not (self.applies_to_topup or self.applies_to_cashout):
			frappe.throw(
				"The discount must apply to at least one flow "
				"(Card Top-Ups and/or Bank Cashouts) — uncheck Active to suspend it instead."
			)

	def before_rename(self, old, new, merge=False):
		# The Rename dialog is the documented path for changing the username
		# (set_only_once blocks direct edits, and the field description points
		# operators here) — but rename_doc writes both the document name and
		# the username column raw, bypassing before_insert/validate entirely.
		# Without this hook a typo'd rename would succeed silently and the
		# flash reader would fail open to a 0% discount. Same resolution as
		# create: unknown username → block the rename; found → rename to
		# flash's canonical spelling (rename_doc honors the returned "new"
		# override); flash unreachable → warn but allow.
		return {"new": self._resolve_flash_username(new)}

	def _sync_username_with_flash(self):
		self.username = self._resolve_flash_username(self.username)

	def _resolve_flash_username(self, username):
		"""Resolve a username against flash and return its canonical form.

		The flash reader matches case-insensitively (both sides lowercased)
		but fails open to a 0% discount for unknown usernames — a typo'd
		entry would save cleanly and silently never discount, which is why
		existence is verified here. Unknown username → block the save;
		found → return flash's canonical spelling (keeps the row name
		matching what the admin pages display); flash unreachable → warn
		but return the trimmed input, so a flash outage never bricks the
		admin panel.
		"""
		username = (username or "").strip()
		if not username:
			frappe.throw("Username is required.")

		try:
			from admin_panel.api.graphql_client import GraphQLClient

			account = GraphQLClient().get_account_by_username(username)
		except Exception:
			frappe.log_error(
				title="Fee Discount: flash username check failed",
				message=frappe.get_traceback(),
			)
			frappe.msgprint(
				msg=(
					f"Could not verify username '{username}' against flash "
					"(API unreachable or not configured). Saving anyway — "
					"double-check the spelling, or the discount will silently never apply."
				),
				title="Username not verified",
				indicator="orange",
			)
			return username

		if not account:
			frappe.throw(
				f"No flash account found with username '{username}'. "
				"An unknown username would save cleanly and silently never "
				"apply (matching is case-insensitive — existence is what's "
				"being verified). Check the spelling against the flash account."
			)

		canonical = (account.get("username") or "").strip()
		return canonical or username

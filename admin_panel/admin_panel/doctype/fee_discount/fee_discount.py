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

		# set_only_once normally blocks username edits on saved rows, but a
		# programmatic change must re-resolve too — the flash reader matches
		# the stored string exactly (trim only, case-sensitive).
		if not self.is_new() and self.has_value_changed("username"):
			self._sync_username_with_flash()

		value = frappe.utils.flt(self.discount_percent)
		if value < 0 or value > 100:
			frappe.throw("Flash Fee Discount (%) must be between 0 and 100.")

		if not (self.applies_to_topup or self.applies_to_cashout):
			frappe.throw(
				"The discount must apply to at least one flow "
				"(Card Top-Ups and/or Bank Cashouts) — uncheck Active to suspend it instead."
			)

	def _sync_username_with_flash(self):
		"""Resolve the username against flash and store its canonical form.

		The flash reader keys its discount map on the exact stored string
		(trim only, case-sensitive) and fails open to a 0% discount for
		unknown usernames — a typo'd or case-drifted entry would save
		cleanly and silently never discount. Unknown username → block the
		save; found → store flash's canonical spelling (closes case drift);
		flash unreachable → warn but allow the save, so a flash outage
		never bricks the admin panel.
		"""
		self.username = (self.username or "").strip()
		if not self.username:
			frappe.throw("Username is required.")

		try:
			from admin_panel.api.graphql_client import GraphQLClient

			account = GraphQLClient().get_account_by_username(self.username)
		except Exception:
			frappe.log_error(
				title="Fee Discount: flash username check failed",
				message=frappe.get_traceback(),
			)
			frappe.msgprint(
				msg=(
					f"Could not verify username '{self.username}' against flash "
					"(API unreachable or not configured). Saving anyway — "
					"double-check the spelling, or the discount will silently never apply."
				),
				title="Username not verified",
				indicator="orange",
			)
			return

		if not account:
			frappe.throw(
				f"No flash account found with username '{self.username}'. "
				"Discounts are matched against the flash username exactly "
				"(case-sensitive), so an unknown username would save cleanly "
				"and silently never apply."
			)

		canonical = (account.get("username") or "").strip()
		if canonical:
			self.username = canonical

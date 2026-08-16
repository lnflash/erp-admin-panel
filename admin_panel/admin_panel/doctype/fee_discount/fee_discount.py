import frappe
from frappe.model.document import Document


class FeeDiscount(Document):
	def validate(self):
		# Defense-in-depth at the point of entry. The flash backend re-validates
		# (and fails open to a 0% discount on malformed rows), but this row
		# directly changes what a named user pays without further review, so
		# refuse obviously-wrong values here.
		self.username = (self.username or "").strip()
		if not self.username:
			frappe.throw("Username is required.")

		value = frappe.utils.flt(self.discount_percent)
		if value < 0 or value > 100:
			frappe.throw("Flash Fee Discount (%) must be between 0 and 100.")

		if not (self.applies_to_topup or self.applies_to_cashout):
			frappe.throw(
				"The discount must apply to at least one flow "
				"(Card Top-Ups and/or Bank Cashouts) — uncheck Active to suspend it instead."
			)

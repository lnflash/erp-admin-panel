import frappe
from frappe.model.document import Document


class FygaroSettings(Document):
	def validate(self):
		# Defense-in-depth at the point of entry. The flash backend re-validates,
		# but this is a financial-policy single (auto-credit toggle + limit + fee
		# model): a mistyped limit or a negative fee here directly changes what
		# gets credited without review, so refuse obviously-wrong values.
		for fieldname in (
			"processor_fee_percent",
			"processor_fee_fixed",
			"flash_margin_percent",
			"flash_margin_fixed",
		):
			if frappe.utils.flt(self.get(fieldname)) < 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} cannot be negative.")

		for fieldname in ("processor_fee_percent", "flash_margin_percent"):
			value = frappe.utils.flt(self.get(fieldname))
			if value > 100:
				frappe.throw(f"{self.meta.get_label(fieldname)} must be between 0 and 100.")

		if frappe.utils.flt(self.minimum_topup) <= 0:
			frappe.throw("Minimum Top-Up must be greater than 0.")

		if frappe.utils.flt(self.auto_credit_limit) < frappe.utils.flt(self.minimum_topup):
			frappe.throw("Auto-Credit Limit cannot be below the Minimum Top-Up.")

		# Zero is a deliberate "no card top-ups for this level"; negative is a typo.
		for fieldname in ("l1_daily_limit", "l2_daily_limit", "l3_daily_limit"):
			if frappe.utils.flt(self.get(fieldname)) < 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} cannot be negative.")

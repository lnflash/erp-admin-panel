import frappe
from frappe.model.document import Document

from admin_panel.api.idv_core import ALLOWED_STATUSES, DECIDED_STATUSES


class IDVerification(Document):
	def validate(self):
		if self.status not in ALLOWED_STATUSES:
			frappe.throw(
				f"Invalid ID Verification status '{self.status}'. Allowed: {', '.join(ALLOWED_STATUSES)}."
			)
		if self.status in DECIDED_STATUSES and not (self.reviewed_by and self.reviewed_at):
			frappe.throw(f"An {self.status} verification must record who reviewed it and when.")

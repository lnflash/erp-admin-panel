import frappe
from frappe.model.document import Document

from admin_panel.api.compliance_audit import record_event
from admin_panel.api.idv_core import SETTINGS_DOCTYPE, coerce, settings_diff


class IDVerificationSettings(Document):
	def validate(self):
		if coerce("Int", self.retention_years) < 1:
			frappe.throw("Retention (years) must be at least 1.")
		sampling = coerce("Int", self.auto_approve_sampling_percent)
		if sampling < 0 or sampling > 100:
			frappe.throw("Auto-Approve Sampling (%) must be between 0 and 100.")
		min_score = coerce("Float", self.auto_approve_min_score)
		if min_score < 0 or min_score > 1:
			frappe.throw("Auto-Approve Minimum Score must be between 0 and 1.")

	def on_update(self):
		# Every policy change is a ledger event; an untouched save is not.
		changed = settings_diff(self.get_doc_before_save(), self)
		if not changed:
			return
		record_event("idv_settings_changed", SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, {"changed": changed})

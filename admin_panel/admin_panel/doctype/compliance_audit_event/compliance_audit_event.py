import frappe
from frappe.model.document import Document

APPEND_ONLY_MESSAGE = (
	"Compliance Audit Event is append-only: rows are written once by "
	"admin_panel.api.compliance_audit.record_event and never edited or deleted."
)


class ComplianceAuditEvent(Document):
	def before_save(self):
		# The doctype grants no write permission to anyone, but Administrator
		# bypasses permission checks — the controller is what makes the
		# ledger append-only for everybody.
		if not self.is_new():
			frappe.throw(APPEND_ONLY_MESSAGE)

	def on_trash(self):
		frappe.throw(APPEND_ONLY_MESSAGE)

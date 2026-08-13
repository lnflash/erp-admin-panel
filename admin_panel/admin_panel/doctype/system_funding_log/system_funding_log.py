# Append-only treasury funding audit trail. Rows are created exclusively by
# api/system_accounts.create_funding_invoice (financial-gated) — one row per
# Lightning receive invoice generated on a treasury (role) wallet. in_create
# hides the desk "New" button, and no role has write/create/delete permission
# on purpose. It also exists so audit_log() has a real record to reference: the
# audit Comment's reference_name is a Dynamic Link and only persists against an
# existing doctype row.

from frappe.model.document import Document


class SystemFundingLog(Document):
	pass

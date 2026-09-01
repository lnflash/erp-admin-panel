from frappe.model.document import Document


class ReferralSettings(Document):
	# A single Check field needs no validation: both states are legal and the
	# flash backend treats an unreadable row the same as "off" (payouts defer,
	# nothing is lost). Kill switches must stay simple enough to flip at 3am.
	pass

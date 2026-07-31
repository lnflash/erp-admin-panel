"""Pure shaping logic for the Account Hub Banking tab.

No frappe or IO imports — takes raw Bridge virtual/external account dicts
(shapes verified against the flash backend's Bridge client types) and returns
the exact fields the tab renders. Unit-tested directly, like bridge_kyc_core.
"""


def slim_virtual_account(v):
	"""Deposit instructions for one Bridge virtual account (the US account)."""
	instructions = v.get("source_deposit_instructions") or {}
	destination = v.get("destination") or {}
	return {
		"id": v.get("id"),
		"status": v.get("status"),
		"currency": instructions.get("currency"),
		"bank_name": instructions.get("bank_name"),
		"routing_number": instructions.get("bank_routing_number"),
		"account_number": instructions.get("bank_account_number"),
		"beneficiary_name": instructions.get("bank_beneficiary_name"),
		"payment_rails": instructions.get("payment_rails") or [],
		"destination_currency": destination.get("currency"),
		"created_at": v.get("created_at"),
	}


def slim_external_account(e):
	"""One linked external bank account (Plaid/Bridge). Bridge only exposes
	the last 4 digits for these — there is no full number to show."""
	return {
		"id": e.get("id"),
		"bank_name": e.get("bank_name"),
		"owner_name": e.get("account_owner_name"),
		"account_type": e.get("account_type"),
		"currency": e.get("currency"),
		"last_4": e.get("last_4") or e.get("account_number_last_4"),
		"routing_number": e.get("routing_number"),
		"iban": e.get("iban"),
		"active": e.get("active"),
		"created_at": e.get("created_at"),
	}

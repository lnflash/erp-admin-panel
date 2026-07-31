"""Unit tests for the pure Banking-tab shaping logic.

Shapes mirror the flash backend's Bridge client types (VirtualAccount /
ExternalAccount interfaces in src/services/bridge/client.ts).
"""

from admin_panel.api.banking_core import slim_external_account, slim_virtual_account


def test_slim_virtual_account_extracts_deposit_instructions():
	virtual = {
		"id": "va-1",
		"status": "activated",
		"customer_id": "cus-1",
		"source_deposit_instructions": {
			"currency": "usd",
			"payment_rails": ["ach_push", "wire"],
			"bank_name": "Lead Bank",
			"bank_beneficiary_name": "Jane Doe",
			"bank_account_number": "123456789012",
			"bank_routing_number": "101019644",
		},
		"destination": {"currency": "usdc", "payment_rail": "polygon"},
		"created_at": "2026-07-01T00:00:00.000Z",
	}
	slim = slim_virtual_account(virtual)
	assert slim == {
		"id": "va-1",
		"status": "activated",
		"currency": "usd",
		"bank_name": "Lead Bank",
		"routing_number": "101019644",
		"account_number": "123456789012",
		"beneficiary_name": "Jane Doe",
		"payment_rails": ["ach_push", "wire"],
		"destination_currency": "usdc",
		"created_at": "2026-07-01T00:00:00.000Z",
	}


def test_slim_virtual_account_tolerates_missing_blocks():
	slim = slim_virtual_account({"id": "va-2", "status": "pending"})
	assert slim["account_number"] is None
	assert slim["payment_rails"] == []
	assert slim["destination_currency"] is None


def test_slim_external_account_prefers_last_4_and_falls_back():
	base = {
		"id": "ea-1",
		"account_owner_name": "Jane Doe",
		"account_type": "checking",
		"currency": "usd",
		"bank_name": "Chase",
		"active": True,
		"created_at": "2026-07-02T00:00:00.000Z",
	}
	assert slim_external_account({**base, "last_4": "4321"})["last_4"] == "4321"
	# Older responses use account_number_last_4 instead.
	assert slim_external_account({**base, "account_number_last_4": "9876"})["last_4"] == "9876"
	slim = slim_external_account(base)
	assert slim["last_4"] is None
	assert slim["owner_name"] == "Jane Doe"
	assert slim["active"] is True

"""Unit tests for the pure payer-identity resolution logic.

Fygaro payload shape mirrors real webhook payloads: ``customReference`` is the
Flash username the app sent with the payment, ``client`` is what the payer
typed at checkout. Bridge payloads have neither field.
"""

import json

from admin_panel.api.transfer_identity_core import (
	PAYER_FIELDS,
	build_payer_fields,
	empty_payer_fields,
	parse_payload_identity,
)

FYGARO_PAYLOAD = json.dumps(
	{
		"amount": 50,
		"currency": "USD",
		"customReference": "hotsteppa",
		"client": {"name": "Jane Doe", "email": "jane@example.com"},
	}
)

BRIDGE_PAYLOAD = json.dumps(
	{
		"id": "9a1f8c2e",
		"on_behalf_of": "cust_123",
		"source": {"payment_rail": "polygon"},
	}
)


def test_parse_payload_extracts_fygaro_identity():
	assert parse_payload_identity(FYGARO_PAYLOAD) == {
		"username": "hotsteppa",
		"name": "Jane Doe",
		"email": "jane@example.com",
	}


def test_parse_payload_bridge_rows_yield_blanks():
	assert parse_payload_identity(BRIDGE_PAYLOAD) == {"username": "", "name": "", "email": ""}


def test_parse_payload_never_raises_on_garbage():
	for garbage in (None, "", "not json", "[1, 2]", '"a string"', json.dumps({"client": "x"}), 42):
		out = parse_payload_identity(garbage)
		assert out == {"username": "", "name": "", "email": ""}


def test_account_truth_wins_over_provider_payload():
	fields = build_payer_fields(
		payload_identity=parse_payload_identity(FYGARO_PAYLOAD),
		account_identity={"username": "hotsteppa", "phone": "+18765550100", "erp_party": "CUST-1"},
		customer_info={"customer_name": "Jane A. Doe", "email_id": "jane@flash.com", "mobile_no": ""},
	)
	assert fields["payer_username"] == "hotsteppa"
	assert fields["payer_name"] == "Jane A. Doe"
	assert fields["payer_email"] == "jane@flash.com"
	assert fields["payer_phone"] == "+18765550100"
	assert fields["payer_provider_fields"] == []


def test_provider_fallback_is_labeled():
	fields = build_payer_fields(payload_identity=parse_payload_identity(FYGARO_PAYLOAD))
	assert fields["payer_username"] == "hotsteppa"
	assert fields["payer_name"] == "Jane Doe"
	assert fields["payer_email"] == "jane@example.com"
	assert fields["payer_phone"] == ""
	assert sorted(fields["payer_provider_fields"]) == [
		"payer_email",
		"payer_name",
		"payer_username",
	]


def test_mixed_sources_label_only_provider_fields():
	# Account resolved via customReference but no ERP customer: username/phone
	# come from Flash, name/email fall back to the checkout form.
	fields = build_payer_fields(
		payload_identity=parse_payload_identity(FYGARO_PAYLOAD),
		account_identity={"username": "hotsteppa", "phone": "+18765550100", "erp_party": None},
	)
	assert fields["payer_username"] == "hotsteppa"
	assert fields["payer_phone"] == "+18765550100"
	assert fields["payer_name"] == "Jane Doe"
	assert sorted(fields["payer_provider_fields"]) == ["payer_email", "payer_name"]


def test_missing_account_degrades_to_blanks():
	fields = build_payer_fields(payload_identity=parse_payload_identity(BRIDGE_PAYLOAD))
	for field in PAYER_FIELDS:
		assert fields[field] == ""
	assert fields["payer_provider_fields"] == []


def test_phone_falls_back_to_erp_customer_mobile():
	fields = build_payer_fields(
		account_identity={"username": "hotsteppa", "phone": None, "erp_party": "CUST-1"},
		customer_info={"customer_name": "Jane A. Doe", "email_id": None, "mobile_no": "+18765550199"},
	)
	assert fields["payer_phone"] == "+18765550199"
	assert fields["payer_provider_fields"] == []


def test_empty_payer_fields_shape_matches_build_output():
	empty = empty_payer_fields()
	built = build_payer_fields()
	assert set(empty) == set(built)
	for field in PAYER_FIELDS:
		assert empty[field] == ""
	assert empty["payer_provider_fields"] == []

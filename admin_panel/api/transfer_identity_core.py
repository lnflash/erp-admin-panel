"""Pure payer-identity resolution for the Transfer Requests audit tabs.

No frappe or IO imports — everything takes plain dicts (parsed provider
payloads, account identities from mongo_reader, ERPNext Customer rows) so it
can be unit-tested directly, mirroring census_core / bridge_kyc_core.

Field priority (Flash account truth first, provider payload as fallback):
  username — accounts.username, else Fygaro ``customReference``
  name     — ERPNext Customer name (via erpParty), else Fygaro ``client.name``
  email    — ERPNext Customer email_id, else Fygaro ``client.email``
  phone    — mongo users.phone (via kratosUserId), else Customer mobile_no

Values that fell back to the provider payload are listed in
``payer_provider_fields`` so the UI can label them "(from provider)" — a
Fygaro ``client`` block is whatever the payer typed at checkout, not verified
Flash identity.
"""

import json

PAYER_FIELDS = ("payer_name", "payer_username", "payer_email", "payer_phone")


def empty_payer_fields():
	"""Blank payer_* dict — every audit row carries these keys even when
	enrichment is skipped or fails, so the UI never branches on presence."""
	out = dict.fromkeys(PAYER_FIELDS, "")
	out["payer_provider_fields"] = []
	return out


def _clean(value):
	return value.strip() if isinstance(value, str) else ""


def parse_payload_identity(raw_payload_json):
	"""Extract payer hints from a provider payload (best effort, never raises).

	Fygaro payloads carry ``customReference`` (the Flash username the app sent
	with the payment) and ``client: {name, email}`` (payer details captured at
	checkout). Bridge payloads have neither; malformed or non-dict payloads
	yield blanks.
	"""
	out = {"username": "", "name": "", "email": ""}
	if not raw_payload_json:
		return out
	payload = raw_payload_json
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			return out
	if not isinstance(payload, dict):
		return out

	out["username"] = _clean(payload.get("customReference"))
	client = payload.get("client")
	if isinstance(client, dict):
		out["name"] = _clean(client.get("name"))
		out["email"] = _clean(client.get("email"))
	return out


def build_payer_fields(payload_identity=None, account_identity=None, customer_info=None):
	"""Merge account truth + ERP Customer + provider payload into payer_* fields.

	``account_identity`` comes from mongo (username/phone via kratos user),
	``customer_info`` from the erpParty-linked ERPNext Customer (name/email/
	mobile), ``payload_identity`` from parse_payload_identity. Any of them may
	be None/empty — missing sources just leave blanks.
	"""
	payload_identity = payload_identity or {}
	account_identity = account_identity or {}
	customer_info = customer_info or {}
	provider_fields = []

	def pick(field, flash_value, provider_value=""):
		if flash_value:
			return str(flash_value)
		if provider_value:
			provider_fields.append(field)
			return str(provider_value)
		return ""

	return {
		"payer_name": pick("payer_name", customer_info.get("customer_name"), payload_identity.get("name")),
		"payer_username": pick(
			"payer_username", account_identity.get("username"), payload_identity.get("username")
		),
		"payer_email": pick("payer_email", customer_info.get("email_id"), payload_identity.get("email")),
		"payer_phone": pick("payer_phone", account_identity.get("phone") or customer_info.get("mobile_no")),
		"payer_provider_fields": provider_fields,
	}

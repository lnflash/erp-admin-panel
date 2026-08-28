"""Unit tests for the support contact shaping (support_lookup_core).

The returned dict is a cross-repo contract with the nostr-dm-bridge in
flash-support-infra (services/nostr-dm-bridge/bridge.mjs) AND a privacy
boundary: it leaves the cluster for the support droplet, so a new field
sneaking in (wallets, balances) is as much a bug as a missing one.
"""

from admin_panel.api.support_lookup_core import (
	SUPPORT_CONTACT_KEYS,
	slim_support_contact,
)

FULL_ACCOUNT = {
	"id": "acct-1",
	"uuid": "39c6e986-979b-40ab-9e7b-df18a9277a84",
	"npub": "npub1" + "q" * 58,
	"username": "jaceth2009",
	"level": "TWO",
	"createdAt": 1720000000,
	"title": "Account Title",
	"owner": {
		"id": "user-1",
		"phone": "+18765550100",
		"language": "en",
		"email": {"address": "jaceth@example.com", "verified": True},
	},
	"merchants": [{"title": "Jaceth's Shop"}],
	# Fields the query must never request — present here to prove the
	# shaper drops unexpected input rather than passing it through.
	"wallets": [{"id": "w-1", "balance": 12345}],
}


def test_full_account_maps_every_contract_key():
	slim = slim_support_contact(FULL_ACCOUNT)
	assert slim == {
		"npub": FULL_ACCOUNT["npub"],
		"username": "jaceth2009",
		"level": "TWO",
		"accountCreatedAt": 1720000000,
		"phone": "+18765550100",
		"email": "jaceth@example.com",
		"emailVerified": True,
		"language": "en",
		"merchantTitle": "Jaceth's Shop",
	}


def test_output_keys_are_exactly_the_contract():
	assert set(slim_support_contact(FULL_ACCOUNT).keys()) == set(SUPPORT_CONTACT_KEYS)


def test_never_leaks_wallets_or_extra_fields():
	slim = slim_support_contact(FULL_ACCOUNT)
	assert "wallets" not in slim
	assert "balance" not in str(slim)


def test_tolerates_missing_blocks():
	slim = slim_support_contact({"npub": "npub1x", "username": "u"})
	assert slim["phone"] is None
	assert slim["email"] is None
	assert slim["emailVerified"] is None
	assert slim["merchantTitle"] is None
	assert slim["accountCreatedAt"] is None


def test_tolerates_null_owner_and_email():
	# Partial responses (allow_not_found lookup semantics) can null out
	# owner.email on a dangling Kratos identity.
	slim = slim_support_contact({"npub": "npub1x", "owner": {"phone": "+18765550100", "email": None}})
	assert slim["phone"] == "+18765550100"
	assert slim["email"] is None
	assert slim["emailVerified"] is None


def test_merchant_title_falls_back_to_account_title():
	slim = slim_support_contact({"title": "Biz Title", "merchants": []})
	assert slim["merchantTitle"] == "Biz Title"

	slim = slim_support_contact({"title": "Biz Title", "merchants": [{"title": None}]})
	assert slim["merchantTitle"] == "Biz Title"

	slim = slim_support_contact({"title": "Biz Title", "merchants": [{"title": "Shop"}]})
	assert slim["merchantTitle"] == "Shop"


def test_email_verified_is_none_without_address():
	# verified:false with no address is meaningless — keep the card blank.
	slim = slim_support_contact({"owner": {"email": {"address": None, "verified": False}}})
	assert slim["emailVerified"] is None

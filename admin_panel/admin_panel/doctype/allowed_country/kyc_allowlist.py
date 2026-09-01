"""The Bridge KYC country allowlist — the contract the Flash api reads.

Flash's `bridgeInitiateKyc` mutation fetches
``GET /api/resource/Allowed Country?filters=[["flash_allowed","=",1]]``
every 60s and only lets a user start Bridge KYC (the US virtual account
onboarding) when the ISO alpha-2 country of their verified phone number is in
that result. A country that is unchecked — or has no row at all — is denied.

Two things live here and nowhere else, so the seed (fresh sites), the one-shot
reseed patch (existing sites) and the contract test cannot drift from each
other:

* ``BRIDGE_KYC_ALLOWLIST`` — the alpha-2 codes seeded as ``flash_allowed = 1``.
  Chosen by the operator (2026-09-01): the Caribbean, US/CA/GB, MX, SV, SN and
  KE. Haiti and Cuba are deliberately absent. Kenya is included on the
  operator's instruction although Bridge's published table marks KE as not
  eligible for US ACH/FedWire — if Kenyan users get "not authorized to create
  USD Virtual Accounts" after approval, uncheck KE in the list.
* ``ADDITIONAL_COUNTRIES`` — rows Bridge's 168-country seed does not carry
  but the allowlist (or its neighbours) needs, so a checkbox exists to toggle.
  ``bridge_risk_tier`` is left empty where our copy of Bridge's table has no
  tier for the country.

Everything in this module is pure (no frappe import) so it can be unit-tested
under plain pytest, and so ``plan_reseed`` can be asserted idempotent.
"""

BRIDGE_KYC_ALLOWLIST = frozenset(
	{
		# Caribbean
		"JM",  # Jamaica
		"TT",  # Trinidad and Tobago
		"BB",  # Barbados
		"BS",  # Bahamas
		"DO",  # Dominican Republic
		"KY",  # Cayman Islands
		"AG",  # Antigua and Barbuda
		"DM",  # Dominica
		"GD",  # Grenada
		"KN",  # Saint Kitts and Nevis
		"LC",  # Saint Lucia
		"VC",  # Saint Vincent and the Grenadines
		"BZ",  # Belize
		"GY",  # Guyana
		"SR",  # Suriname
		"AW",  # Aruba
		"CW",  # Curaçao
		"SX",  # Sint Maarten
		"BM",  # Bermuda
		"TC",  # Turks and Caicos Islands
		"VG",  # British Virgin Islands
		"AI",  # Anguilla
		"MS",  # Montserrat
		# North America / UK
		"US",
		"CA",
		"GB",
		# Operator additions 2026-09-01
		"MX",  # Mexico
		"SV",  # El Salvador
		"SN",  # Senegal (Dakar)
		"KE",  # Kenya — see module docstring caveat
	}
)

# Rows missing from Bridge's 168-country seed. Same shape as
# seed.SUPPORTED_COUNTRIES minus flash_allowed (decided by the allowlist).
# Tiers come from Bridge's published table where our seed carries one for a
# comparable entry; "" = not published in our copy.
ADDITIONAL_COUNTRIES = [
	{"iso_code": "PAK", "alpha2_code": "PK", "country_name": "Pakistan", "bridge_risk_tier": "Restricted"},
	{"iso_code": "BGD", "alpha2_code": "BD", "country_name": "Bangladesh", "bridge_risk_tier": "Restricted"},
	{"iso_code": "HTI", "alpha2_code": "HT", "country_name": "Haiti", "bridge_risk_tier": "Restricted"},
	{"iso_code": "CYM", "alpha2_code": "KY", "country_name": "Cayman Islands", "bridge_risk_tier": ""},
	{
		"iso_code": "TCA",
		"alpha2_code": "TC",
		"country_name": "Turks and Caicos Islands",
		"bridge_risk_tier": "",
	},
	{
		"iso_code": "VGB",
		"alpha2_code": "VG",
		"country_name": "British Virgin Islands",
		"bridge_risk_tier": "",
	},
	{"iso_code": "AIA", "alpha2_code": "AI", "country_name": "Anguilla", "bridge_risk_tier": ""},
	{"iso_code": "MSR", "alpha2_code": "MS", "country_name": "Montserrat", "bridge_risk_tier": ""},
	{"iso_code": "BMU", "alpha2_code": "BM", "country_name": "Bermuda", "bridge_risk_tier": ""},
	{"iso_code": "ABW", "alpha2_code": "AW", "country_name": "Aruba", "bridge_risk_tier": ""},
	{"iso_code": "CUW", "alpha2_code": "CW", "country_name": "Curaçao", "bridge_risk_tier": ""},
	{"iso_code": "SXM", "alpha2_code": "SX", "country_name": "Sint Maarten", "bridge_risk_tier": ""},
	{"iso_code": "PRI", "alpha2_code": "PR", "country_name": "Puerto Rico", "bridge_risk_tier": ""},
	{"iso_code": "VIR", "alpha2_code": "VI", "country_name": "U.S. Virgin Islands", "bridge_risk_tier": ""},
]

DESCRIPTIVE_FIELDS = ("alpha2_code", "country_name", "bridge_risk_tier")


def flash_allowed_for(alpha2_code):
	"""1 if the country may start Bridge KYC, else 0."""
	return 1 if (alpha2_code or "").upper() in BRIDGE_KYC_ALLOWLIST else 0


def plan_reseed(existing_rows, seed_rows, apply_allowlist):
	"""Decide what a reseed must change, without touching the database.

	``existing_rows`` maps ``iso_code`` → dict with at least ``flash_allowed``
	plus the descriptive fields; ``seed_rows`` is the list of seed dicts
	(``SUPPORTED_COUNTRIES`` + ``ADDITIONAL_COUNTRIES``).

	Returns ``(inserts, updates)``:

	* ``inserts`` — seed rows with no existing row. Their ``flash_allowed`` is
	  set from the allowlist.
	* ``updates`` — ``{iso_code: {field: value}}`` for existing rows: the
	  descriptive fields are refreshed from the seed when they differ, and —
	  ONLY when ``apply_allowlist`` is true (the one-shot patch) — ``flash_allowed``
	  is set from the allowlist. The routine that runs on every migrate passes
	  ``apply_allowlist=False`` so an operator's later toggle is never undone
	  by a deploy.

	Applying the returned plan and planning again yields ``([], {})`` — the
	idempotency the contract test asserts.
	"""
	inserts = []
	updates = {}
	for row in seed_rows:
		iso = row["iso_code"]
		wanted = flash_allowed_for(row["alpha2_code"])
		current = existing_rows.get(iso)
		if current is None:
			inserts.append({**row, "flash_allowed": wanted})
			continue
		changes = {}
		for key in DESCRIPTIVE_FIELDS:
			if (current.get(key) or "") != (row.get(key) or ""):
				changes[key] = row.get(key) or ""
		if apply_allowlist and int(current.get("flash_allowed") or 0) != wanted:
			changes["flash_allowed"] = wanted
		if changes:
			updates[iso] = changes
	if apply_allowlist:
		# Rows an operator added by hand (not in any seed list) still have to
		# converge on the allowlist in the one-shot pass.
		seeded = {row["iso_code"] for row in seed_rows}
		for iso, current in existing_rows.items():
			if iso in seeded:
				continue
			wanted = flash_allowed_for(current.get("alpha2_code"))
			if int(current.get("flash_allowed") or 0) != wanted:
				updates.setdefault(iso, {})["flash_allowed"] = wanted
	return inserts, updates


def apply_plan_to_rows(existing_rows, inserts, updates):
	"""Pure in-memory application of a plan (used by the idempotency test)."""
	rows = {iso: dict(row) for iso, row in existing_rows.items()}
	for row in inserts:
		rows[row["iso_code"]] = dict(row)
	for iso, changes in updates.items():
		rows[iso].update(changes)
	return rows

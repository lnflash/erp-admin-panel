"""Seed the Allowed Country DocType from Bridge's supported-countries table.

168 rows from Bridge's table (33 Restricted, 135 Not High Risk) plus the
Caribbean territories / PK / BD / HT / PR / VI that the table does not carry
(see kyc_allowlist.ADDITIONAL_COUNTRIES).

``flash_allowed`` is the Bridge KYC country allowlist the Flash api reads
(``kyc_allowlist.py``). It is OPERATOR-MANAGED: this seed sets it only when it
inserts a new row (from ``BRIDGE_KYC_ALLOWLIST``) and never changes it on an
existing row, so a checkbox flipped in /app/allowed-country survives every
``bench migrate``. The one-shot narrowing of the column happened in
``admin_panel.patches.reseed_bridge_kyc_allowlist``.

Run via bench:
  bench --site flash.manage.getflash.io execute \
    admin_panel.admin_panel.doctype.allowed_country.seed.seed_allowed_countries

Or via after_migrate hook (auto-runs on bench migrate).
"""

import frappe

from admin_panel.admin_panel.doctype.allowed_country.kyc_allowlist import (
	ADDITIONAL_COUNTRIES,
	DESCRIPTIVE_FIELDS,
	plan_reseed,
)

SUPPORTED_COUNTRIES = [
    # --- Restricted (33) ---
    {"iso_code": "ALB", "alpha2_code": "AL", "country_name": "Albania", "bridge_risk_tier": "Restricted"},
    {"iso_code": "AGO", "alpha2_code": "AO", "country_name": "Angola", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BRB", "alpha2_code": "BB", "country_name": "Barbados", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BTN", "alpha2_code": "BT", "country_name": "Bhutan", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BIH", "alpha2_code": "BA", "country_name": "Bosnia and Herzegovina", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BWA", "alpha2_code": "BW", "country_name": "Botswana", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BFA", "alpha2_code": "BF", "country_name": "Burkina Faso", "bridge_risk_tier": "Restricted"},
    {"iso_code": "BDI", "alpha2_code": "BI", "country_name": "Burundi", "bridge_risk_tier": "Restricted"},
    {"iso_code": "CMR", "alpha2_code": "CM", "country_name": "Cameroon", "bridge_risk_tier": "Restricted"},
    {"iso_code": "CAF", "alpha2_code": "CF", "country_name": "Central African Republic", "bridge_risk_tier": "Restricted"},
    {"iso_code": "CIV", "alpha2_code": "CI", "country_name": "Côte d'Ivoire", "bridge_risk_tier": "Restricted"},
    {"iso_code": "HRV", "alpha2_code": "HR", "country_name": "Croatia", "bridge_risk_tier": "Restricted"},
    {"iso_code": "ERI", "alpha2_code": "ER", "country_name": "Eritrea", "bridge_risk_tier": "Restricted"},
    {"iso_code": "ETH", "alpha2_code": "ET", "country_name": "Ethiopia", "bridge_risk_tier": "Restricted"},
    {"iso_code": "JAM", "alpha2_code": "JM", "country_name": "Jamaica", "bridge_risk_tier": "Restricted"},
    {"iso_code": "KEN", "alpha2_code": "KE", "country_name": "Kenya", "bridge_risk_tier": "Restricted"},
    {"iso_code": "XKX", "alpha2_code": "XK", "country_name": "Kosovo", "bridge_risk_tier": "Restricted"},
    {"iso_code": "LAO", "alpha2_code": "LA", "country_name": "Laos", "bridge_risk_tier": "Restricted"},
    {"iso_code": "MCO", "alpha2_code": "MC", "country_name": "Monaco", "bridge_risk_tier": "Restricted"},
    {"iso_code": "NAM", "alpha2_code": "NA", "country_name": "Namibia", "bridge_risk_tier": "Restricted"},
    {"iso_code": "NIC", "alpha2_code": "NI", "country_name": "Nicaragua", "bridge_risk_tier": "Restricted"},
    {"iso_code": "NER", "alpha2_code": "NE", "country_name": "Niger", "bridge_risk_tier": "Restricted"},
    {"iso_code": "NGA", "alpha2_code": "NG", "country_name": "Nigeria", "bridge_risk_tier": "Restricted"},
    {"iso_code": "SEN", "alpha2_code": "SN", "country_name": "Senegal", "bridge_risk_tier": "Restricted"},
    {"iso_code": "ZAF", "alpha2_code": "ZA", "country_name": "South Africa", "bridge_risk_tier": "Restricted"},
    {"iso_code": "TZA", "alpha2_code": "TZ", "country_name": "Tanzania", "bridge_risk_tier": "Restricted"},
    {"iso_code": "TTO", "alpha2_code": "TT", "country_name": "Trinidad and Tobago", "bridge_risk_tier": "Restricted"},
    {"iso_code": "TUR", "alpha2_code": "TR", "country_name": "Turkey", "bridge_risk_tier": "Restricted"},
    {"iso_code": "UGA", "alpha2_code": "UG", "country_name": "Uganda", "bridge_risk_tier": "Restricted"},
    {"iso_code": "UKR", "alpha2_code": "UA", "country_name": "Ukraine", "bridge_risk_tier": "Restricted"},
    {"iso_code": "VUT", "alpha2_code": "VU", "country_name": "Vanuatu", "bridge_risk_tier": "Restricted"},
    {"iso_code": "VNM", "alpha2_code": "VN", "country_name": "Vietnam", "bridge_risk_tier": "Restricted"},
    {"iso_code": "ZWE", "alpha2_code": "ZW", "country_name": "Zimbabwe", "bridge_risk_tier": "Restricted"},

    # --- Not High Risk (135 — JPN and TUN excluded from Flash) ---
    {"iso_code": "AND", "alpha2_code": "AD", "country_name": "Andorra", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ATG", "alpha2_code": "AG", "country_name": "Antigua and Barbuda", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ARG", "alpha2_code": "AR", "country_name": "Argentina", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ARM", "alpha2_code": "AM", "country_name": "Armenia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "AUS", "alpha2_code": "AU", "country_name": "Australia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "AUT", "alpha2_code": "AT", "country_name": "Austria", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "AZE", "alpha2_code": "AZ", "country_name": "Azerbaijan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BHS", "alpha2_code": "BS", "country_name": "Bahamas", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BHR", "alpha2_code": "BH", "country_name": "Bahrain", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BEL", "alpha2_code": "BE", "country_name": "Belgium", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BLZ", "alpha2_code": "BZ", "country_name": "Belize", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BEN", "alpha2_code": "BJ", "country_name": "Benin", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BOL", "alpha2_code": "BO", "country_name": "Bolivia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BRA", "alpha2_code": "BR", "country_name": "Brazil", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BRN", "alpha2_code": "BN", "country_name": "Brunei", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "BGR", "alpha2_code": "BG", "country_name": "Bulgaria", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CPV", "alpha2_code": "CV", "country_name": "Cabo Verde", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KHM", "alpha2_code": "KH", "country_name": "Cambodia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CAN", "alpha2_code": "CA", "country_name": "Canada", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TCD", "alpha2_code": "TD", "country_name": "Chad", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CHL", "alpha2_code": "CL", "country_name": "Chile", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "COL", "alpha2_code": "CO", "country_name": "Colombia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "COM", "alpha2_code": "KM", "country_name": "Comoros", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "COG", "alpha2_code": "CG", "country_name": "Congo", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CRI", "alpha2_code": "CR", "country_name": "Costa Rica", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CYP", "alpha2_code": "CY", "country_name": "Cyprus", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CZE", "alpha2_code": "CZ", "country_name": "Czechia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "DNK", "alpha2_code": "DK", "country_name": "Denmark", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "DJI", "alpha2_code": "DJ", "country_name": "Djibouti", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "DMA", "alpha2_code": "DM", "country_name": "Dominica", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "DOM", "alpha2_code": "DO", "country_name": "Dominican Republic", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ECU", "alpha2_code": "EC", "country_name": "Ecuador", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "EGY", "alpha2_code": "EG", "country_name": "Egypt", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SLV", "alpha2_code": "SV", "country_name": "El Salvador", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GNQ", "alpha2_code": "GQ", "country_name": "Equatorial Guinea", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "EST", "alpha2_code": "EE", "country_name": "Estonia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SWZ", "alpha2_code": "SZ", "country_name": "Eswatini", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "FJI", "alpha2_code": "FJ", "country_name": "Fiji", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "FIN", "alpha2_code": "FI", "country_name": "Finland", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "FRA", "alpha2_code": "FR", "country_name": "France", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GAB", "alpha2_code": "GA", "country_name": "Gabon", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GMB", "alpha2_code": "GM", "country_name": "Gambia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GEO", "alpha2_code": "GE", "country_name": "Georgia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "DEU", "alpha2_code": "DE", "country_name": "Germany", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GHA", "alpha2_code": "GH", "country_name": "Ghana", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GRC", "alpha2_code": "GR", "country_name": "Greece", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GRD", "alpha2_code": "GD", "country_name": "Grenada", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GTM", "alpha2_code": "GT", "country_name": "Guatemala", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GIN", "alpha2_code": "GN", "country_name": "Guinea", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GUY", "alpha2_code": "GY", "country_name": "Guyana", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "VAT", "alpha2_code": "VA", "country_name": "Holy See (Vatican City)", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "HND", "alpha2_code": "HN", "country_name": "Honduras", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "HUN", "alpha2_code": "HU", "country_name": "Hungary", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ISL", "alpha2_code": "IS", "country_name": "Iceland", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "IND", "alpha2_code": "IN", "country_name": "India", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "IDN", "alpha2_code": "ID", "country_name": "Indonesia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "IRL", "alpha2_code": "IE", "country_name": "Ireland", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ISR", "alpha2_code": "IL", "country_name": "Israel", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ITA", "alpha2_code": "IT", "country_name": "Italy", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "JPN", "alpha2_code": "JP", "country_name": "Japan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "JOR", "alpha2_code": "JO", "country_name": "Jordan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KAZ", "alpha2_code": "KZ", "country_name": "Kazakhstan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KIR", "alpha2_code": "KI", "country_name": "Kiribati", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KOR", "alpha2_code": "KR", "country_name": "South Korea", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KWT", "alpha2_code": "KW", "country_name": "Kuwait", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KGZ", "alpha2_code": "KG", "country_name": "Kyrgyzstan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LVA", "alpha2_code": "LV", "country_name": "Latvia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LSO", "alpha2_code": "LS", "country_name": "Lesotho", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LBR", "alpha2_code": "LR", "country_name": "Liberia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LIE", "alpha2_code": "LI", "country_name": "Liechtenstein", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LTU", "alpha2_code": "LT", "country_name": "Lithuania", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LUX", "alpha2_code": "LU", "country_name": "Luxembourg", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MDG", "alpha2_code": "MG", "country_name": "Madagascar", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MWI", "alpha2_code": "MW", "country_name": "Malawi", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MYS", "alpha2_code": "MY", "country_name": "Malaysia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MDV", "alpha2_code": "MV", "country_name": "Maldives", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MLI", "alpha2_code": "ML", "country_name": "Mali", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MLT", "alpha2_code": "MT", "country_name": "Malta", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MHL", "alpha2_code": "MH", "country_name": "Marshall Islands", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MRT", "alpha2_code": "MR", "country_name": "Mauritania", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MUS", "alpha2_code": "MU", "country_name": "Mauritius", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MEX", "alpha2_code": "MX", "country_name": "Mexico", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "FSM", "alpha2_code": "FM", "country_name": "Micronesia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MDA", "alpha2_code": "MD", "country_name": "Moldova", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MNG", "alpha2_code": "MN", "country_name": "Mongolia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "MNE", "alpha2_code": "ME", "country_name": "Montenegro", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "NRU", "alpha2_code": "NR", "country_name": "Nauru", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "NLD", "alpha2_code": "NL", "country_name": "Netherlands", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "NZL", "alpha2_code": "NZ", "country_name": "New Zealand", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "NOR", "alpha2_code": "NO", "country_name": "Norway", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "OMN", "alpha2_code": "OM", "country_name": "Oman", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PLW", "alpha2_code": "PW", "country_name": "Palau", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PAN", "alpha2_code": "PA", "country_name": "Panama", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PNG", "alpha2_code": "PG", "country_name": "Papua New Guinea", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PRY", "alpha2_code": "PY", "country_name": "Paraguay", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PER", "alpha2_code": "PE", "country_name": "Peru", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PHL", "alpha2_code": "PH", "country_name": "Philippines", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "POL", "alpha2_code": "PL", "country_name": "Poland", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "PRT", "alpha2_code": "PT", "country_name": "Portugal", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ROU", "alpha2_code": "RO", "country_name": "Romania", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "RWA", "alpha2_code": "RW", "country_name": "Rwanda", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "KNA", "alpha2_code": "KN", "country_name": "Saint Kitts and Nevis", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LCA", "alpha2_code": "LC", "country_name": "Saint Lucia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "VCT", "alpha2_code": "VC", "country_name": "Saint Vincent and the Grenadines", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "WSM", "alpha2_code": "WS", "country_name": "Samoa", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SMR", "alpha2_code": "SM", "country_name": "San Marino", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "STP", "alpha2_code": "ST", "country_name": "São Tomé and Príncipe", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SAU", "alpha2_code": "SA", "country_name": "Saudi Arabia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SRB", "alpha2_code": "RS", "country_name": "Serbia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SYC", "alpha2_code": "SC", "country_name": "Seychelles", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SLE", "alpha2_code": "SL", "country_name": "Sierra Leone", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SGP", "alpha2_code": "SG", "country_name": "Singapore", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SVK", "alpha2_code": "SK", "country_name": "Slovakia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SVN", "alpha2_code": "SI", "country_name": "Slovenia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SLB", "alpha2_code": "SB", "country_name": "Solomon Islands", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ESP", "alpha2_code": "ES", "country_name": "Spain", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "LKA", "alpha2_code": "LK", "country_name": "Sri Lanka", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SUR", "alpha2_code": "SR", "country_name": "Suriname", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "SWE", "alpha2_code": "SE", "country_name": "Sweden", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "CHE", "alpha2_code": "CH", "country_name": "Switzerland", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TWN", "alpha2_code": "TW", "country_name": "Taiwan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TJK", "alpha2_code": "TJ", "country_name": "Tajikistan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "THA", "alpha2_code": "TH", "country_name": "Thailand", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TLS", "alpha2_code": "TL", "country_name": "Timor-Leste", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TGO", "alpha2_code": "TG", "country_name": "Togo", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TON", "alpha2_code": "TO", "country_name": "Tonga", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TUN", "alpha2_code": "TN", "country_name": "Tunisia", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TKM", "alpha2_code": "TM", "country_name": "Turkmenistan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "TUV", "alpha2_code": "TV", "country_name": "Tuvalu", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ARE", "alpha2_code": "AE", "country_name": "United Arab Emirates", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "GBR", "alpha2_code": "GB", "country_name": "United Kingdom", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "USA", "alpha2_code": "US", "country_name": "United States of America", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "URY", "alpha2_code": "UY", "country_name": "Uruguay", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "UZB", "alpha2_code": "UZ", "country_name": "Uzbekistan", "bridge_risk_tier": "Not High Risk"},
    {"iso_code": "ZMB", "alpha2_code": "ZM", "country_name": "Zambia", "bridge_risk_tier": "Not High Risk"},
]


def all_seed_rows():
	"""Bridge's table plus the rows it does not carry — one row per iso_code."""
	seen = set()
	rows = []
	for row in [*SUPPORTED_COUNTRIES, *ADDITIONAL_COUNTRIES]:
		if row["iso_code"] in seen:
			continue
		seen.add(row["iso_code"])
		rows.append(row)
	return rows


def load_existing_rows():
	"""iso_code → stored row, for plan_reseed."""
	return {
		row["iso_code"]: row
		for row in frappe.get_all(
			"Allowed Country",
			fields=["iso_code", "flash_allowed", *DESCRIPTIVE_FIELDS],
			limit_page_length=0,
		)
	}


def write_plan(inserts, updates):
	"""Apply a plan_reseed() result to the database."""
	for row in inserts:
		doc = frappe.new_doc("Allowed Country")
		doc.update(row)
		doc.flags.ignore_permissions = True
		doc.insert()
	for iso_code, changes in updates.items():
		doc = frappe.get_doc("Allowed Country", iso_code)
		for key, value in changes.items():
			doc.set(key, value)
		doc.flags.ignore_permissions = True
		doc.save()
	frappe.db.commit()


def seed_allowed_countries():
	"""Insert missing rows and refresh names/tiers. Never touches flash_allowed
	on an existing row — that column is the operator-managed KYC allowlist."""
	inserts, updates = plan_reseed(load_existing_rows(), all_seed_rows(), apply_allowlist=False)
	write_plan(inserts, updates)
	print(f"Allowed Country seed: {len(inserts)} inserted, {len(updates)} refreshed")

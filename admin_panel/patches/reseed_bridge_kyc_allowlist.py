import frappe

from admin_panel.admin_panel.doctype.allowed_country.kyc_allowlist import (
	BRIDGE_KYC_ALLOWLIST,
	plan_reseed,
)
from admin_panel.admin_panel.doctype.allowed_country.seed import (
	all_seed_rows,
	load_existing_rows,
	write_plan,
)

# One-shot reseed of Allowed Country as the Bridge KYC country allowlist.
#
# Until now flash_allowed was 1 for ~all 168 Bridge-supported countries (the
# PR #24 seed), and flash did not read it. From this deploy flash's
# bridgeInitiateKyc reads flash_allowed=1 rows every 60s and denies KYC for
# everyone else — so the column has to mean "the operator cleared this
# country", and the 2026-09-01 signup wave (IN/NG/PK/BD users approved by
# Bridge KYC and then refused a USD virtual account) is why it is being
# narrowed to the markets Bridge actually serves for Flash.
#
# What this does, once (patches.txt records it in tabPatch Log):
#   * inserts any seed row that is missing (Bridge's 168 + the Caribbean
#     territories, PK/BD/HT, PR/VI that the seed never carried), and
#   * sets flash_allowed = 1 for BRIDGE_KYC_ALLOWLIST and 0 for every other row,
#     including rows an operator added by hand.
#
# It is NOT re-applied by after_migrate: seed_allowed_countries() (which runs
# on every migrate) only inserts missing rows and refreshes the descriptive
# fields — it never touches flash_allowed on an existing row — so a checkbox an
# operator flips in /app/allowed-country after this deploy survives every
# later deploy. Re-running this patch by hand is safe; it converges to the same
# state.


def execute():
	existing = load_existing_rows()
	inserts, updates = plan_reseed(existing, all_seed_rows(), apply_allowlist=True)
	flipped_on = sum(1 for c in updates.values() if c.get("flash_allowed") == 1)
	flipped_off = sum(1 for c in updates.values() if c.get("flash_allowed") == 0)

	write_plan(inserts, updates)

	summary = (
		"Allowed Country reseeded as the Bridge KYC allowlist: "
		f"{len(inserts)} rows added, {flipped_on} flipped on, {flipped_off} flipped off, "
		f"{len(BRIDGE_KYC_ALLOWLIST)} countries allowed"
	)
	# print() reaches the `bench migrate` output; frappe.logger() is silent in
	# the production containers (level=ERROR, no stdout handler).
	print(summary)
	frappe.logger("admin_panel").info(summary)

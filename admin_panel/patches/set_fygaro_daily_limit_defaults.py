import frappe

# Seed the per-level daily top-up limits on the Fygaro Settings single.
#
# Field defaults in the doctype JSON only apply when the document is saved
# through the UI — a migrate alone leaves the new columns NULL in tabSingles.
# The flash webhook fails closed on a missing limit (every payment drops to
# manual review), so an operator forgetting to open-and-save the settings page
# after this deploy would silently disable auto-credit. Seeding here makes the
# deploy self-contained.
#
# Only NULL values are touched: an operator-set value — including a deliberate
# 0 meaning "no card top-ups for this level" — is never overwritten, so the
# patch stays safe to re-run.

DEFAULTS = {
    "l1_daily_limit": 125.00,
    "l2_daily_limit": 1000.00,
    "l3_daily_limit": 2500.00,
}


def execute():
    for fieldname, default in DEFAULTS.items():
        if frappe.db.get_single_value("Fygaro Settings", fieldname) is None:
            frappe.db.set_single_value("Fygaro Settings", fieldname, default)

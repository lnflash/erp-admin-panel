import frappe

# Seed rewards_enabled = 1 on the Referral Settings single.
#
# Field defaults in the doctype JSON only apply when the document is saved
# through the UI — a migrate alone leaves `rewards_enabled` NULL in
# tabSingles, and v15's get_single_value casts that NULL to 0 for a Check
# field. The flash side pays referral rewards only on an affirmative 1, so
# without this seed every payout would be silently deferred from the moment
# of deploy until an operator happens to open-and-save Referral Settings —
# contradicting the promise that deploying this changes nothing until
# someone flips it. Seeding here makes the deploy self-contained.
#
# Only a NULL (never-stored) value is touched: an operator-set value —
# including a deliberate 0 meaning "rewards off" — is never overwritten, so
# the patch stays safe to re-run.
#
# The raw tabSingles row is read via get_singles_dict, NOT get_single_value:
# get_single_value's Check cast collapses NULL to 0, making a missing value
# indistinguishable from a deliberate operator 0, so an `is None` guard on
# the cast value never fires. get_singles_dict returns the stored row uncast:
# a field with no row is simply absent (None), while an operator 0 is stored
# as "0" and correctly preserved. Same pattern as
# set_fygaro_daily_limit_defaults.py.


def execute():
	stored = frappe.db.get_singles_dict("Referral Settings")
	if stored.get("rewards_enabled") is None:
		frappe.db.set_single_value("Referral Settings", "rewards_enabled", 1)

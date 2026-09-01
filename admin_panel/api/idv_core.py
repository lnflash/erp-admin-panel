"""Pure constants and helpers for ID verification — no Frappe runtime.

Shared by the ID Verification / ID Verification Settings controllers and
``admin_api`` so the API never has to import a controller module (and its
``frappe.model.document`` dependency) just to learn a field list.
"""

ALLOWED_STATUSES = (
	"Checks pending",
	"Ready for review",
	"Checks unavailable",
	"Approved",
	"Rejected",
	"Resubmit requested",
)

# Statuses that are a reviewer decision and therefore need a reviewer stamp.
DECIDED_STATUSES = ("Approved", "Rejected")

DEFAULT_APPROVE_REASON = "APPROVE_VERIFIED"
DEFAULT_REJECT_REASON = "REJECT_OTHER"

SETTINGS_DOCTYPE = "ID Verification Settings"

# (fieldname, fieldtype) of every operator-tunable setting. get_idv_settings
# returns exactly these, and the settings controller diffs exactly these.
SETTINGS_FIELDS = (
	("auto_approve_enabled", "Check"),
	("auto_approve_levels", "Data"),
	("auto_approve_min_score", "Float"),
	("auto_approve_sampling_percent", "Int"),
	("bridge_kyc_satisfies_identity", "Check"),
	("retention_years", "Int"),
	("idv_service_url", "Data"),
)


def coerce(fieldtype, value):
	"""Normalise a value the way tabSingles round-trips it, so a diff between
	the form's "0.9" and the stored 0.9 is not reported as a change."""
	if fieldtype in ("Check", "Int"):
		try:
			return int(float(value))
		except (TypeError, ValueError):
			return 0
	if fieldtype == "Float":
		try:
			return float(value)
		except (TypeError, ValueError):
			return 0.0
	return value if value not in (None, "") else None


def settings_diff(before, after) -> dict:
	"""``{field: {"from", "to"}}`` for every tracked field that changed.

	``before`` may be ``None`` (first ever save): every non-empty value is
	then reported as a change from ``None``.
	"""
	changed = {}
	for fieldname, fieldtype in SETTINGS_FIELDS:
		old = coerce(fieldtype, before.get(fieldname) if before is not None else None)
		new = coerce(fieldtype, after.get(fieldname))
		if old != new:
			changed[fieldname] = {"from": old, "to": new}
	return changed

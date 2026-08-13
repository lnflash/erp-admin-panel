"""Pure interpretation of IBEX invoice settlement state.

IO-free (no frappe / requests / pymongo) so the money-critical "did THIS invoice
actually settle?" logic can be unit-tested against fixtures with plain pytest —
the same isolation census_core uses for the census join logic. system_accounts.py
imports invoice_settled for the funding receipt signal.
"""

# IBEX invoice states (LND-derived), verified against the flash backend's on-pay
# settlement verifier (src/services/ibex/webhook-server/routes/on-pay.ts):
#   0 OPEN / 1 SETTLED / 2 CANCELLED / 3 ACCEPTED
# Only SETTLED means the receive invoice was actually paid. ACCEPTED (a held
# HTLC) is NOT money in hand.
INVOICE_STATE_SETTLED = 1
INVOICE_STATE_CANCELLED = 2

_SETTLED_NAMES = {"SETTLED", "SUCCEEDED", "COMPLETE", "COMPLETED", "PAID"}
_FAILED_NAMES = {"CANCELLED", "CANCELED", "EXPIRED", "FAILED"}


def _state_id_and_name(invoice):
	"""(state_id, state_name) from either a nested {state:{id,name}} or a flat
	stateId shape. Returns (None, "") when neither is present."""
	state = invoice.get("state")
	if isinstance(state, dict):
		return state.get("id"), (state.get("name") or "")
	return invoice.get("stateId"), ""


def invoice_settled(invoice):
	"""Did THIS invoice affirmatively settle? True / False / None.

	Fail-safe by design (mirrors _payment_settled in system_accounts): an OPEN or
	ACCEPTED invoice, an unknown/ambiguous shape, or a not-yet-known payment hash
	all yield None — treated as "still waiting", never as receipt. Money is never
	reported received on a guess, and never on a mere balance change.
	"""
	if not isinstance(invoice, dict) or invoice.get("not_found"):
		return None
	state_id, name = _state_id_and_name(invoice)
	name = (name or "").upper()
	if state_id == INVOICE_STATE_SETTLED or name in _SETTLED_NAMES:
		return True
	if state_id == INVOICE_STATE_CANCELLED or name in _FAILED_NAMES:
		return False
	return None

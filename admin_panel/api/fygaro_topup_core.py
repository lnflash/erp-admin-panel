"""Pure eligibility logic for operator Complete / Cancel actions on card top-ups.

No frappe or IO imports — takes plain ``provider`` / ``status`` strings so the
allow/reject matrix can be unit-tested directly, mirroring transfer_identity_core
/ banking_core.

An operator status action (Complete or Cancel) is record-only: it stamps the
audit row after the top-up was credited (or declined) out of band. Only a Fygaro
row still sitting in ``Fiat Received`` is eligible. A Bridge row, an already
terminal Fygaro status (``Completed`` / ``Settled`` / ``Failed`` / ``Cancelled``),
or the pre-settlement ``Pending`` state must all be rejected so a stamp can never
contradict a real transfer.
"""

ACTIONABLE_PROVIDER = "Fygaro"
ACTIONABLE_STATUS = "Fiat Received"


def is_actionable(provider, status):
	"""True iff a top-up row can take an operator Complete/Cancel status action.

	The single source of truth for the guard: a Fygaro row in ``Fiat Received``,
	and nothing else.
	"""
	return provider == ACTIONABLE_PROVIDER and status == ACTIONABLE_STATUS


def rejection_reason(provider, status, action):
	"""Human-readable reason a row is not actionable, or ``None`` when it is.

	Keeps the provider check and the status check as two distinct messages so the
	operator sees which precondition failed. Stays in lock-step with
	``is_actionable`` — it returns ``None`` exactly when ``is_actionable`` is True.
	"""
	if provider != ACTIONABLE_PROVIDER:
		return f"Only a Fygaro card top-up can be {action}."
	if status != ACTIONABLE_STATUS:
		return f"Only a Fygaro top-up in 'Fiat Received' can be {action}."
	return None

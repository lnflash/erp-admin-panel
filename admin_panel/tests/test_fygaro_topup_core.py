"""Unit tests for the pure Fygaro top-up action eligibility logic.

These exercise the actual allow/reject decision the Complete / Cancel endpoints
rely on — not the way the source is spelled. A Fygaro row in ``Fiat Received`` is
the only actionable combination; every other provider or status must be rejected
so an operator can never stamp a status that contradicts a real transfer (e.g.
re-completing an already-``Completed`` row, or acting on a Bridge row).
"""

import pytest

from admin_panel.api.fygaro_topup_core import (
	ACTIONABLE_PROVIDER,
	ACTIONABLE_STATUS,
	is_actionable,
	rejection_reason,
)

# Every status the Bridge Transfer Request DocType can carry (mirrors the
# doctype ``status`` options), plus the non-Fygaro provider.
ALL_STATUSES = ("Pending", "Fiat Received", "Settled", "Completed", "Failed", "Cancelled")
NON_ACTIONABLE_STATUSES = tuple(s for s in ALL_STATUSES if s != ACTIONABLE_STATUS)


def test_only_fygaro_fiat_received_is_actionable():
	assert is_actionable("Fygaro", "Fiat Received") is True


def test_constants_define_the_single_allowed_combination():
	assert (ACTIONABLE_PROVIDER, ACTIONABLE_STATUS) == ("Fygaro", "Fiat Received")
	assert is_actionable(ACTIONABLE_PROVIDER, ACTIONABLE_STATUS) is True


@pytest.mark.parametrize("status", NON_ACTIONABLE_STATUSES)
def test_fygaro_in_any_other_status_is_rejected(status):
	# Completed / Settled / Failed / Cancelled are terminal; Pending is
	# pre-settlement. None may be re-stamped by an operator action.
	assert is_actionable("Fygaro", status) is False


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_bridge_rows_are_rejected_in_every_status(status):
	# A Bridge transfer is never an operator-record-only card top-up, even when
	# it happens to be sitting in Fiat Received.
	assert is_actionable("Bridge", status) is False


def test_unknown_or_empty_provider_and_status_are_rejected():
	assert is_actionable(None, None) is False
	assert is_actionable("", "") is False
	assert is_actionable("fygaro", "Fiat Received") is False  # case-sensitive on purpose
	assert is_actionable("Fygaro", "fiat received") is False


def test_rejection_reason_is_none_exactly_when_actionable():
	assert rejection_reason("Fygaro", "Fiat Received", "completed") is None
	# rejection_reason and is_actionable must never disagree.
	for provider in ("Fygaro", "Bridge", "", None):
		for status in (*ALL_STATUSES, "", None):
			assert (rejection_reason(provider, status, "completed") is None) == is_actionable(
				provider, status
			)


def test_rejection_reason_names_the_failed_precondition():
	# Wrong provider -> provider message, regardless of status.
	assert rejection_reason("Bridge", "Fiat Received", "completed") == (
		"Only a Fygaro card top-up can be completed."
	)
	# Right provider but wrong status -> status message, carrying the action verb.
	assert rejection_reason("Fygaro", "Completed", "cancelled") == (
		"Only a Fygaro top-up in 'Fiat Received' can be cancelled."
	)

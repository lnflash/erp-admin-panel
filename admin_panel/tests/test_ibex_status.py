"""Unit tests for the pure IBEX invoice-settlement interpretation.

This is the money-critical receipt signal for treasury funding: it decides
whether the UI may tell an operator "the invoice was paid". It replaces the old
wallet-balance-delta heuristic, which on an actively-transacting treasury wallet
(bankowner's float grows with every cashout) would falsely read routine inflow
as the funding payment. The logic is IO-free, so it is tested directly here
rather than only grepped for in the source.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from admin_panel.api.ibex_status import invoice_settled


def test_settled_state_is_receipt():
	# state.id == 1 is the authoritative SETTLED signal (verified against the
	# flash backend's on-pay verifier); the flat stateId and the name both work.
	assert invoice_settled({"state": {"id": 1, "name": "SETTLED"}}) is True
	assert invoice_settled({"stateId": 1}) is True
	assert invoice_settled({"state": {"name": "SETTLED"}}) is True


def test_open_invoice_is_never_receipt():
	# The whole point of the fix: an OPEN (unpaid) invoice must NOT read as
	# settled, even though the wallet's balance may have risen from other traffic.
	assert invoice_settled({"state": {"id": 0, "name": "OPEN"}}) is None


def test_accepted_htlc_is_not_settled():
	# ACCEPTED (id 3) is a held HTLC, not money in hand — must stay ambiguous.
	assert invoice_settled({"state": {"id": 3, "name": "ACCEPTED"}}) is None


def test_cancelled_or_expired_is_affirmative_failure():
	assert invoice_settled({"state": {"id": 2, "name": "CANCELLED"}}) is False
	assert invoice_settled({"state": {"name": "EXPIRED"}}) is False


def test_unknown_or_missing_shape_is_ambiguous_not_success():
	# Fail-safe: a not-yet-known hash, an empty/odd shape, or None all yield None
	# so receipt is never claimed on a guess.
	assert invoice_settled({"not_found": True}) is None
	assert invoice_settled({}) is None
	assert invoice_settled(None) is None
	assert invoice_settled({"state": {"id": 99, "name": "WEIRD"}}) is None

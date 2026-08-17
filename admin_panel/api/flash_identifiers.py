"""Shape guards for flash identifiers.

Deliberately stdlib-only: doctype controllers import this to screen operator
input before spending a flash lookup on it, and must not drag in requests /
jwt / pymongo (or the rest of the API layer) to do so.
"""

import re

# Mirror of flash's Username scalar — /^(?!^(1|3|bc1|lnbc1))[\p{L}0-9_]{3,50}$/iu
# in src/domain/accounts/index.ts (note the ASCII-only variant one line above it
# there is deliberately commented out; usernames are Unicode). Python's ``\w`` is
# Unicode-aware for str patterns, so it stands in for [\p{L}0-9_]; ``\Z`` rather
# than ``$`` so a trailing newline cannot sneak through. The lookahead is flash's
# own: a username may not be mistaken for a bitcoin address or a BOLT11 invoice.
# (``\w`` is a hair wider than [\p{L}0-9_]: it also admits non-ASCII digits and
# number-letters — ٣, Ⅻ — which flash refuses. That direction is harmless; see
# below.)
#
# What this guard buys is a saved round trip and a precise error string — NOT
# protection from a fail-open. Flash answers a non-Username argument with an
# INVALID_INPUT GraphQL error, and GraphQLClient._is_not_found_error
# (graphql_client.py:80) already classifies INVALID_INPUT as "no such account",
# so a malformed identifier comes back as None and every caller rejects it
# either way. The guard only means the operator who pasted an email address, a
# phone number or an account UUID is told it is not a username at all, instead
# of being told flash has no such account.
FLASH_USERNAME_PATTERN = r"^(?!(?:1|3|bc1|lnbc1))\w{3,50}\Z"

_FLASH_USERNAME_RE = re.compile(FLASH_USERNAME_PATTERN, re.IGNORECASE)


def is_flash_username_candidate(value):
	"""True when ``value`` is shaped like a flash username.

	Shape only — says nothing about whether the account exists.
	"""
	return bool(value and _FLASH_USERNAME_RE.match(str(value).strip()))

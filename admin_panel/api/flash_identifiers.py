"""Shape guards for flash identifiers.

Deliberately stdlib-only: doctype controllers import this to screen operator
input before spending a flash lookup on it, and must not drag in requests /
jwt / pymongo (or the rest of the API layer) to do so.
"""

import re

# flash's Username scalar: letters, digits, underscore and hyphen, 3+ chars.
# Anything else — an email address, a phone number, a display name with a
# space — is rejected by the API as invalid input (HTTP 400) rather than
# answering a clean "no such account", so the caller gets an exception where
# it expected a None and any fail-open branch behind the lookup misfires.
FLASH_USERNAME_PATTERN = r"^[a-zA-Z0-9_-]{3,}$"


def is_flash_username_candidate(value):
	"""True when ``value`` is shaped like a flash username.

	Shape only — says nothing about whether the account exists.
	"""
	return bool(value and re.match(FLASH_USERNAME_PATTERN, str(value).strip()))

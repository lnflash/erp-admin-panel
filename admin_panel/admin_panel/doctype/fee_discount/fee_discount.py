import frappe
from frappe.model.document import Document

from admin_panel.api.flash_identifiers import is_flash_username_candidate

# before_rename resolves the new username against flash, but rename_doc throws
# the resolution away: it never saves the doc that before_rename ran on, and
# after_rename receives a freshly fetched document instead. The verification
# state is handed between the two hooks through this request-local flag so it
# is persisted only once the rename has actually landed — writing it from
# before_rename would stamp the row even when validate_rename then rejects the
# new name (e.g. a row for that username already exists).
_RENAME_RESOLUTION_FLAG = "fee_discount_rename_resolution"


class FeeDiscount(Document):
	def before_insert(self):
		# Resolve the username against flash BEFORE set_new_name runs, so the
		# document name (autoname field:username) is built from the canonical
		# spelling — _sync_autoname_field would otherwise revert a validate()-
		# time correction back to the typo'd name on save.
		self._sync_username_with_flash()

	def validate(self):
		# Defense-in-depth at the point of entry. The flash backend re-validates
		# (and fails open to a 0% discount on malformed rows), but this row
		# directly changes what a named user pays without further review, so
		# refuse obviously-wrong values here.
		self.username = (self.username or "").strip()
		if not self.username:
			frappe.throw("Username is required.")

		# In-place username edits on a saved row can NEVER work with autoname
		# field:username: Frappe v15's _sync_autoname_field reverts the field
		# to self.name BEFORE validate_set_only_once compares, so a scripted /
		# REST edit would "succeed" while the username silently snaps back —
		# the caller believes the discount moved; the old user keeps it.
		# (set_only_once's real effect is only making the field read-only in
		# Desk.) Reject loudly and point at the one path that actually works.
		if not self.is_new() and self.has_value_changed("username"):
			frappe.throw(
				"Username cannot be edited in place — use the Rename dialog, "
				"which verifies the new username against flash."
			)

		value = frappe.utils.flt(self.discount_percent)
		if value < 0 or value > 100:
			frappe.throw("Flash Fee Discount (%) must be between 0 and 100.")

		if not (self.applies_to_topup or self.applies_to_cashout):
			frappe.throw(
				"The discount must apply to at least one flow "
				"(Card Top-Ups and/or Bank Cashouts) — uncheck Active to suspend it instead."
			)

		# Re-run the check on a row that went in unverified, so verified=0 has
		# a clearing path instead of decaying into noise the first time it
		# fires in bulk. Nothing else can clear it: before_insert only fires on
		# create, rename-to-itself is refused outright (frappe/model/
		# rename_doc.py — `if old == new: frappe.throw`), and no scheduler
		# event is enabled. Without this, a rotated admin_api_key strands every
		# row created while it was broken and delete-and-recreate is the only
		# exit. The username is provably unchanged here (the throw above
		# guarantees it), so re-resolving is idempotent and re-saving the row
		# IS the re-check the field description points at. Last in validate()
		# on purpose: a row that fails the cheap local checks should not cost a
		# round trip to flash.
		if not self.is_new() and not self.verified:
			self._recheck_flash_verification()

	def before_rename(self, old, new, merge=False):
		# The Rename dialog is the documented path for changing the username
		# (set_only_once blocks direct edits, and the field description points
		# operators here) — but rename_doc writes both the document name and
		# the username column raw, bypassing before_insert/validate entirely.
		# Without this hook a typo'd rename would succeed silently and the
		# flash reader would fail open to a 0% discount. Same resolution as
		# create: unknown username → block the rename; found → rename to
		# flash's canonical spelling (rename_doc honors the returned "new"
		# override); flash unreachable → warn but allow, flagged unverified.
		resolution = self._resolve_flash_username(new)
		frappe.flags[_RENAME_RESOLUTION_FLAG] = resolution
		return {"new": resolution["username"]}

	def after_rename(self, old, new, merge=False):
		# The rename landed; persist what before_rename learned. A rename can
		# move the discount to a different person, so a carried-over
		# account_uuid / verified flag from the previous occupant would be
		# worse than none — _resolve_flash_username always returns both.
		resolution = frappe.flags.pop(_RENAME_RESOLUTION_FLAG, None)
		if not resolution or resolution.get("username") != new:
			# Not our resolution (rename_doc(validate=False) skips
			# before_rename entirely) — leave the row's flags alone.
			return
		self.db_set(
			{
				"verified": resolution["verified"],
				"account_uuid": resolution["account_uuid"],
			},
			update_modified=False,
		)

	def _sync_username_with_flash(self):
		resolution = self._resolve_flash_username(self.username)
		self.username = resolution["username"]
		self.verified = resolution["verified"]
		self.account_uuid = resolution["account_uuid"]

	def _recheck_flash_verification(self):
		"""Re-resolve a saved row that had gone in unverified.

		Only ``verified`` / ``account_uuid`` are written back. The username
		cannot move on this path — _sync_autoname_field reverts the field to
		the document name on save — so adopting flash's canonical spelling
		here would be a no-op at best and a misleading in-memory diff at
		worst; the Rename dialog is what actually re-keys the row.

		Non-strict on purpose: an unknown username warns and leaves
		verified=0 instead of throwing. Throwing here would reject the save
		over a field the operator never touched and make a bad row
		impossible to SUSPEND — unchecking Active (the documented way to
		neutralize a row without deleting it) would hit the re-check and
		fail on exactly the rows that need it most. The row is already
		harmless: flash fails open to a 0% discount for a username it does
		not know. Creation and rename stay strict, so a typo can never
		enter or move this way.
		"""
		resolution = self._resolve_flash_username(self.username, strict=False)
		self.verified = resolution["verified"]
		self.account_uuid = resolution["account_uuid"]

	def _resolve_flash_username(self, username, strict=True):
		"""Resolve a username against flash.

		Returns ``{"username", "verified", "account_uuid"}``.

		The flash reader matches case-insensitively (both sides lowercased)
		but fails open to a 0% discount for unknown usernames — a typo'd
		entry would save cleanly and silently never discount, which is why
		existence is verified here. Unknown username → block the save;
		found → return flash's canonical spelling (keeps the row name
		matching what the admin pages display) plus the account's immutable
		uuid; flash unreachable → warn and return the trimmed input with
		verified=0, so a flash outage never bricks the admin panel but the
		unchecked row stays visible instead of evaporating with the toast.

		``strict=False`` downgrades the unknown-username throw to the same
		warn-and-flag treatment as an outage — see
		_recheck_flash_verification for why the update path must never
		block a save. A blank or malformed username still throws in both
		modes: those are operator input errors on a field being set, not
		verdicts about flash's state.
		"""
		username = (username or "").strip()
		if not username:
			frappe.throw("Username is required.")

		# Screen the shape before spending a lookup. This is not what keeps a
		# malformed identifier out: flash answers a non-Username argument with
		# an INVALID_INPUT error, which GraphQLClient._is_not_found_error
		# (graphql_client.py:80) already reads as "no such account", so the
		# lookup returns None and the throw at the bottom fires anyway. What
		# the guard buys is one saved round trip and a precise error string —
		# the operator who pasted an email, a phone number or an account uuid
		# is told it is not a username, not that flash has no such account.
		if not is_flash_username_candidate(username):
			frappe.throw(
				f"'{username}' is not a valid flash username. Usernames are 3 to 50 "
				"characters of letters, digits or underscore — no hyphens, dots or "
				"spaces, and never starting with 1, 3, bc1 or lnbc1. An email "
				"address, a phone number, an account uuid or a display name is not "
				"a username."
			)

		try:
			from admin_panel.api.graphql_client import GraphQLClient

			account = GraphQLClient().get_account_by_username(username)
		except Exception:
			frappe.log_error(
				title="Fee Discount: flash username check failed",
				message=frappe.get_traceback(),
			)
			# A toast is not a record: it is invisible to REST callers (it
			# arrives in _server_messages, which scripts do not read) and gone
			# the moment it is dismissed. The durable signal is verified=0 on
			# the row, so a misconfigured API key — which fails every check
			# from then on, not just this one — shows up in the list view
			# instead of being rediscovered through a customer complaint.
			frappe.msgprint(
				msg=(
					f"Could not verify username '{username}' against flash "
					"(API unreachable or not configured). Saving anyway, flagged "
					"Verified Against Flash = No — double-check the spelling, or "
					"the discount will silently never apply."
				),
				title="Username not verified",
				indicator="orange",
			)
			return {"username": username, "verified": 0, "account_uuid": None}

		if not account:
			if not strict:
				frappe.msgprint(
					msg=(
						f"Flash still has no account named '{username}'. Saving "
						"anyway, left at Verified Against Flash = No — this row "
						"will never discount until the username is corrected via "
						"the Rename dialog."
					),
					title="Username not verified",
					indicator="orange",
				)
				return {"username": username, "verified": 0, "account_uuid": None}
			frappe.throw(
				f"No flash account found with username '{username}'. "
				"An unknown username would save cleanly and silently never "
				"apply (matching is case-insensitive — existence is what's "
				"being verified). Check the spelling against the flash account."
			)

		canonical = (account.get("username") or "").strip()
		return {
			"username": canonical or username,
			"verified": 1,
			"account_uuid": account.get("uuid"),
		}

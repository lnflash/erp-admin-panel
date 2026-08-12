import time
from typing import TypeVar

import frappe
import jwt
import requests

T = TypeVar("T")


class GraphQLError(Exception):
	"""GraphQL-specific error"""

	pass


# Module-level session for connection pooling
_session = None


def _get_session():
	"""Get or create a shared requests session for connection pooling"""
	global _session
	if _session is None:
		_session = requests.Session()
	return _session


class GraphQLClient:
	"""GraphQL client for admin API operations with JWT authentication"""

	def __init__(self):
		self.url = frappe.conf.get("flash_admin_api_url")
		self.api_key = frappe.conf.get("admin_api_key")
		self._session = _get_session()

		if not self.url:
			raise ValueError("flash_admin_api_url is not configured in site_config.json")
		if not self.api_key:
			raise ValueError("admin_api_key is not configured in site_config.json")

	def _create_jwt_token(self) -> str:
		"""Create JWT token with user context and expiration"""
		user = frappe.session.user
		user_roles = frappe.get_roles(user) if user else []
		now = int(time.time())
		payload = {
			"userId": user,
			"roles": user_roles,
			"iat": now,
			"exp": now + 3600,
			"iss": "frappe-admin-panel",
		}
		return jwt.encode(payload, self.api_key, algorithm="HS256")

	def _get_headers(self) -> dict:
		"""Get headers with JWT authentication context"""
		return {
			"Content-Type": "application/json",
			"Authorization": f"Bearer {self._create_jwt_token()}",
		}

	def _check_errors(self, response: dict, allow_not_found: bool = False) -> None:
		"""Check for GraphQL errors and raise exception if found"""
		errors = response.get("errors")
		if not errors:
			return
		if allow_not_found and any(self._is_not_found_error(e) for e in errors):
			return
		raise GraphQLError(f"GraphQL errors: {errors}")

	@staticmethod
	def _is_not_found_error(error: dict) -> bool:
		"""Errors that mean "no such account", not an API failure.

		Flash surfaces a malformed / unknown account id from the by-id lookup as
		UNEXPECTED_CLIENT_ERROR wrapping InvalidAccountIdError (not NOT_FOUND).
		Smart search probes usernames against the by-id lookup as a fallback, so
		that shape must read as "no match" — otherwise every not-found search
		503s instead of returning the friendly 404 (seen on TEST 2026-07-10).
		"""
		if error.get("code") in ("NOT_FOUND", "INVALID_INPUT"):
			return True
		return error.get("code") == "UNEXPECTED_CLIENT_ERROR" and "InvalidAccountIdError" in str(
			error.get("message", "")
		)

	def execute_query(self, query: str, variables: dict | None = None) -> dict:
		"""Execute a GraphQL query and return the response"""
		payload: dict = {"query": query}
		if variables:
			payload["variables"] = variables

		response = self._session.post(url=self.url, json=payload, headers=self._get_headers(), timeout=30)
		response.raise_for_status()
		return response.json()

	def execute_and_extract(
		self,
		query: str,
		variables: dict,
		data_key: str,
		allow_not_found: bool = False,
		*,
		result_type: type[T],
	) -> T | None:
		"""Execute query, check errors, and extract data by key.

		result_type parameterizes the return type: callers declare the shape
		they expect back (e.g. ``result_type=dict``) and get ``T | None``
		instead of ``Any``. The extracted payload is isinstance-checked
		against it, so an API shape drift raises GraphQLError instead of
		leaking a mistyped value into the caller.

		allow_not_found selects LOOKUP semantics, which also tolerate PARTIAL
		responses: when the requested node resolved, field-level resolver
		errors (e.g. owner.email failing with a Kratos 404 on a dangling
		identity, seen on TEST 2026-07-11) must not void the whole account —
		the admin panel exists precisely to inspect broken accounts. The
		errors are logged and the failed fields arrive as null.

		Without the flag (mutations, strict reads) semantics stay
		all-or-nothing: any GraphQL error raises.
		"""
		resp = self.execute_query(query, variables)
		if allow_not_found:
			data = (resp.get("data") or {}).get(data_key)
			errors = resp.get("errors")
			if data is not None:
				if errors:
					frappe.logger().warning(
						f"GraphQL partial response for {data_key} (using data, "
						f"failed fields are null): {errors}"
					)
				return self._checked_result(data, data_key, result_type)
			self._check_errors(resp, allow_not_found=True)
			return None
		self._check_errors(resp)
		data = resp.get("data", {}).get(data_key)
		if data is None:
			return None
		return self._checked_result(data, data_key, result_type)

	@staticmethod
	def _checked_result(data: object, data_key: str, result_type: type[T]) -> T:
		"""Runtime guard backing the parameterized return type"""
		if not isinstance(data, result_type):
			raise GraphQLError(
				f"GraphQL data for {data_key!r} has type {type(data).__name__}, "
				f"expected {result_type.__name__}"
			)
		return data

	# GraphQL query constants
	# Reusable fragment for account detail fields
	ACCOUNT_DETAIL_FRAGMENT = """
	fragment AccountDetail on AuditedAccount {
		id
		uuid
		username
		npub
		level
		statusHeadline
		capabilities {
			verified
			bankPayout
			business
			usdAccount
		}
		status
		title
		erpParty
		owner {
			id
			phone
			language
			email {
				address
				verified
			}
			createdAt
		}
		coordinates {
			latitude
			longitude
		}
		wallets {
			id
			walletCurrency
			accountId
			balance
			pendingIncomingBalance
		}
		merchants {
			id
			title
			coordinates {
				latitude
				longitude
			}
			validated
			username
			createdAt
		}
		createdAt
	}
	"""

	ACCOUNT_BY_PHONE_QUERY = (
		"""
		query accountDetailsByUserPhone($phone: Phone!) {
			accountDetailsByUserPhone(phone: $phone) {
				...AccountDetail
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	UPDATE_LEVEL_MUTATION = (
		"""
		mutation accountUpdateLevel($input: AccountUpdateLevelInput!) {
			accountUpdateLevel(input: $input) {
				errors {
					message
				}
				accountDetails {
					...AccountDetail
				}
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	ID_DOCUMENT_URL_QUERY = """
		query IdDocumentReadUrl($fileKey: String!) {
			idDocumentReadUrl(fileKey: $fileKey) {
				readUrl
				errors {
					message
				}
			}
		}
	"""

	NOTIFICATION_TOPICS_QUERY = """
		query {
			notificationTopics
		}
	"""

	SEND_NOTIFICATION_MUTATION = """
		mutation SendNotification($input: SendNotificationInput!) {
			sendNotification(input: $input) {
				errors {
					message
				}
				success
			}
		}
	"""

	CASHOUT_NOTIFICATION_SEND_MUTATION = """
		mutation CashoutNotificationSend($input: CashoutNotificationSendInput!) {
			cashoutNotificationSend(input: $input) {
				errors {
					message
				}
				success
			}
		}
	"""

	ACCOUNT_BY_USERNAME_QUERY = (
		"""
		query accountDetailsByUsername($username: Username!) {
			accountDetailsByUsername(username: $username) {
				...AccountDetail
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	ACCOUNT_BY_EMAIL_QUERY = (
		"""
		query accountDetailsByEmail($email: EmailAddress!) {
			accountDetailsByEmail(email: $email) {
				...AccountDetail
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	ACCOUNT_BY_ID_QUERY = (
		"""
		query accountDetailsByAccountId($accountId: ID!) {
			accountDetailsByAccountId(accountId: $accountId) {
				...AccountDetail
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	UPDATE_STATUS_MUTATION = (
		"""
		mutation accountUpdateStatus($input: AccountUpdateStatusInput!) {
			accountUpdateStatus(input: $input) {
				errors {
					message
				}
				accountDetails {
					...AccountDetail
				}
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	USER_UPDATE_PHONE_MUTATION = (
		"""
		mutation userUpdatePhone($input: UserUpdatePhoneInput!) {
			userUpdatePhone(input: $input) {
				errors {
					message
				}
				accountDetails {
					...AccountDetail
				}
			}
		}
	"""
		+ ACCOUNT_DETAIL_FRAGMENT
	)

	MERCHANT_MAP_VALIDATE_MUTATION = """
		mutation merchantMapValidate($input: MerchantMapValidateInput!) {
			merchantMapValidate(input: $input) {
				errors {
					message
				}
				merchant {
					id
					title
					coordinates {
						latitude
						longitude
					}
					validated
					username
				}
			}
		}
	"""

	MERCHANT_MAP_DELETE_MUTATION = """
		mutation merchantMapDelete($input: MerchantMapDeleteInput!) {
			merchantMapDelete(input: $input) {
				errors {
					message
				}
			}
		}
	"""

	def get_account_by_phone(self, phone: str) -> dict | None:
		"""Get account details by phone number"""
		return self.execute_and_extract(
			self.ACCOUNT_BY_PHONE_QUERY,
			{"phone": phone},
			"accountDetailsByUserPhone",
			allow_not_found=True,
			result_type=dict,
		)

	def update_account_level(self, uid: str, level: str, erp_party: str | None = None) -> dict:
		"""Update account level"""
		variables = {"input": {"uid": uid, "level": level}}
		if erp_party:
			variables["input"]["erpParty"] = erp_party
		return (
			self.execute_and_extract(
				self.UPDATE_LEVEL_MUTATION, variables, "accountUpdateLevel", result_type=dict
			)
			or {}
		)

	def get_id_document_read_url(self, file_key: str) -> dict:
		"""Get pre-signed URL for ID document from Digital Ocean Spaces"""
		return (
			self.execute_and_extract(
				self.ID_DOCUMENT_URL_QUERY, {"fileKey": file_key}, "idDocumentReadUrl", result_type=dict
			)
			or {}
		)

	def get_notification_topics(self) -> list:
		"""Fetch available notification topics from Flash API"""
		resp = self.execute_query(self.NOTIFICATION_TOPICS_QUERY)
		self._check_errors(resp)
		return resp.get("data", {}).get("notificationTopics", [])

	def send_alert(self, topic: str, title: str, body: str) -> dict:
		"""Send alert to Flash app users via topic"""
		return (
			self.execute_and_extract(
				self.SEND_NOTIFICATION_MUTATION,
				{"input": {"topic": topic, "title": title, "body": body}},
				"sendNotification",
				result_type=dict,
			)
			or {}
		)

	def send_cashout_notification(self, account_id: str, amount: int, currency: str) -> dict:
		"""Notify a Flash user that their cashout has been settled."""
		return (
			self.execute_and_extract(
				self.CASHOUT_NOTIFICATION_SEND_MUTATION,
				{"input": {"accountId": account_id, "amount": int(amount), "currency": currency}},
				"cashoutNotificationSend",
				result_type=dict,
			)
			or {}
		)

	def get_account_by_username(self, username: str) -> dict | None:
		"""Get account details by username"""
		return self.execute_and_extract(
			self.ACCOUNT_BY_USERNAME_QUERY,
			{"username": username},
			"accountDetailsByUsername",
			allow_not_found=True,
			result_type=dict,
		)

	def get_account_by_email(self, email: str) -> dict | None:
		"""Get account details by email address"""
		return self.execute_and_extract(
			self.ACCOUNT_BY_EMAIL_QUERY,
			{"email": email},
			"accountDetailsByEmail",
			allow_not_found=True,
			result_type=dict,
		)

	def get_account_by_id(self, account_id: str) -> dict | None:
		"""Get account details by account ID"""
		return self.execute_and_extract(
			self.ACCOUNT_BY_ID_QUERY,
			{"accountId": account_id},
			"accountDetailsByAccountId",
			allow_not_found=True,
			result_type=dict,
		)

	def update_account_status(self, uid: str, status: str, comment: str | None = None) -> dict:
		"""Change account status via admin mutation"""
		variables = {"input": {"uid": uid, "status": status}}
		if comment:
			variables["input"]["comment"] = comment
		return (
			self.execute_and_extract(
				self.UPDATE_STATUS_MUTATION, variables, "accountUpdateStatus", result_type=dict
			)
			or {}
		)

	def update_user_phone(self, account_uuid: str, phone: str) -> dict:
		"""Update phone number for a user"""
		return (
			self.execute_and_extract(
				self.USER_UPDATE_PHONE_MUTATION,
				{"input": {"accountUuid": account_uuid, "phone": phone}},
				"userUpdatePhone",
				result_type=dict,
			)
			or {}
		)

	def validate_merchant(self, merchant_id: str) -> dict:
		"""Approve a merchant map entry"""
		return (
			self.execute_and_extract(
				self.MERCHANT_MAP_VALIDATE_MUTATION,
				{"input": {"id": merchant_id}},
				"merchantMapValidate",
				result_type=dict,
			)
			or {}
		)

	def delete_merchant(self, merchant_id: str) -> dict:
		"""Delete a merchant map entry"""
		return (
			self.execute_and_extract(
				self.MERCHANT_MAP_DELETE_MUTATION,
				{"input": {"id": merchant_id}},
				"merchantMapDelete",
				result_type=dict,
			)
			or {}
		)

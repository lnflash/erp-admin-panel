import re
from decimal import ROUND_HALF_UP, Decimal

import frappe
import requests as requests_lib

from .auth import audit_log, require_admin, require_financial, require_roles
from .common import handle_api_errors
from .graphql_client import GraphQLClient, GraphQLError


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_account_by_phone(phone):
	"""Get account details by phone number"""
	client = GraphQLClient()
	account = client.get_account_by_phone(phone)

	if account is None:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return account


@frappe.whitelist()
@require_admin()
@handle_api_errors
def update_account_level(uid, level, erp_party=None):
	"""Update account level.

	Flash requires an erpParty for level TWO/THREE accounts. Existing Pro/
	Merchant accounts already have one, so the Account Hub passes it back to
	avoid stripping it on a re-level. Creating a brand-new party is the
	upgrade-request approval flow's job (see _create_erp_records)."""
	client = GraphQLClient()
	return client.update_account_level(uid, level, erp_party=erp_party)


@frappe.whitelist()
@handle_api_errors
def get_user_alerts(limit=10):
	"""Return latest User Alerts"""
	logs = frappe.get_all(
		"User Alerts",
		fields=["title", "message", "tag", "sent_by", "sent_on"],
		order_by="sent_on desc",
		limit_page_length=int(limit),
	)
	return {"logs": logs}


@frappe.whitelist()
@handle_api_errors
def get_alert_types():
	"""Fetch available notification topics from Flash API"""
	client = GraphQLClient()
	topics = client.get_notification_topics()
	return {"topics": topics}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def send_alert(alert_type, title, message):
	"""Send push notification via Flash sendNotification API"""
	if not title or not message or not alert_type:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Alert type, title, and message are required"}

	# Bound input lengths to avoid oversized/abusive push payloads.
	title = str(title).strip()
	message = str(message).strip()
	alert_type = str(alert_type).strip()
	if len(title) > 140 or len(message) > 1000 or len(alert_type) > 64:
		frappe.response["http_status_code"] = 400
		return {
			"success": False,
			"error": "Alert exceeds length limits (title<=140, message<=1000, type<=64)",
		}

	client = GraphQLClient()
	result = client.send_alert(alert_type, title, message)

	if result.get("errors"):
		error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
		frappe.logger().error(f"Send alert errors: {error_messages}")
		frappe.response["http_status_code"] = 400
		return {"success": False, "errors": error_messages}

	if not result.get("success"):
		frappe.response["http_status_code"] = 500
		return {"success": False, "error": "Failed to send notification"}

	frappe.get_doc(
		{
			"doctype": "User Alerts",
			"title": title,
			"message": message,
			"tag": alert_type,
			"sent_by": frappe.session.user,
			"sent_on": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "message": f"Notification sent successfully: {title}"}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_upgrade_requests(status=None, requested_level=None, page=1, page_size=10):
	"""Get paginated upgrade requests from Account Upgrade Request doctype"""
	filters = {}
	if status:
		filters["status"] = status
	if requested_level:
		filters["requested_level"] = requested_level

	page = int(page)
	page_size = min(int(page_size), 100)
	offset = (page - 1) * page_size

	total_count = frappe.db.count("Account Upgrade Request", filters=filters)
	upgrade_requests = frappe.get_all(
		"Account Upgrade Request",
		filters=filters,
		fields=["*"],
		order_by="creation desc",
		limit_start=offset,
		limit_page_length=page_size,
	)

	return {
		"data": upgrade_requests,
		"total": total_count,
		"page": page,
		"page_size": page_size,
		"total_pages": (total_count + page_size - 1) // page_size,
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def search_account(id: str):
	"""Search account by phone number or username"""
	if not id:
		frappe.response["http_status_code"] = 400
		return {"error": "Phone number or Username is required"}

	# Determine search field based on input type
	search_field = "phone_number" if len(re.sub(r"\D", "", id)) >= 10 else "username"

	results = frappe.get_all(
		"Account Upgrade Request",
		filters=[[search_field, "like", f"%{id}%"]],
		fields=["*"],
		order_by="creation desc",
		limit_page_length=50,
	)

	if not results:
		frappe.response["http_status_code"] = 404
		return {"error": "Account not found"}

	return results


def _create_erp_records(req):
	"""Create Customer, Address, and Bank Account synchronously from upgrade request data.
	Returns (errors, customer_name) — errors is empty list on full success.
	"""
	errors = []
	customer_name = None

	# 1. Create Customer
	try:
		existing = frappe.db.get_value("Customer", {"mobile_no": req.phone_number}, "name")
		if existing:
			customer_name = existing
		else:
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": req.full_name,
					"customer_type": "Company" if req.address_title else "Individual",
					"mobile_no": req.phone_number,
					"email_id": req.email or "",
				}
			)
			customer.insert(ignore_permissions=True)
			customer_name = customer.name
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Customer creation failed for request {req.name}")
		errors.append(f"Customer: {e}")
		return errors, None  # Address and Bank Account depend on Customer — skip them

	# 2. Create Address (requires at minimum address_line1, city, country)
	if req.address_line1 and req.city and req.country:
		try:
			existing_addresses = frappe.get_all(
				"Address",
				filters=[
					["Dynamic Link", "link_doctype", "=", "Customer"],
					["Dynamic Link", "link_name", "=", customer_name],
				],
				fields=["address_line1", "address_line2", "city", "state", "pincode", "country"],
			)
			address_unchanged = any(
				(a.address_line1 or "") == (req.address_line1 or "")
				and (a.address_line2 or "") == (req.address_line2 or "")
				and (a.city or "") == (req.city or "")
				and (a.state or "") == (req.state or "")
				and (a.pincode or "") == (req.pincode or "")
				and (a.country or "") == (req.country or "")
				for a in existing_addresses
			)
			if not address_unchanged:
				address = frappe.get_doc(
					{
						"doctype": "Address",
						"address_title": req.address_title or req.full_name,
						"address_type": "Billing",
						"address_line1": req.address_line1,
						"address_line2": req.address_line2 or "",
						"city": req.city,
						"state": req.state or "",
						"pincode": req.pincode or "",
						"country": req.country,
						"links": [
							{
								"link_doctype": "Customer",
								"link_name": customer_name,
							}
						],
					}
				)
				address.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Address creation failed for request {req.name}")
			errors.append(f"Address: {e}")

	# 3. Create Bank Account (requires bank_name and account_number)
	if req.bank_name and req.account_number:
		try:
			if not frappe.db.exists("Bank", req.bank_name):
				frappe.get_doc(
					{
						"doctype": "Bank",
						"bank_name": req.bank_name,
					}
				).insert(ignore_permissions=True)

			if not frappe.db.exists("Bank Account", {"bank_account_no": req.account_number}):
				bank_account = frappe.get_doc(
					{
						"doctype": "Bank Account",
						"account_name": req.address_title or req.full_name,
						"bank": req.bank_name,
						"bank_account_no": req.account_number,
						"branch_code": req.bank_branch or "",
						"account_type": req.account_type or "",
						"currency": req.currency or "",
						"is_company_account": 0,
						"party_type": "Customer",
						"party": customer_name,
					}
				)
				bank_account.insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Bank Account creation failed for request {req.name}")
			errors.append(f"Bank Account: {e}")

	return errors, customer_name


@frappe.whitelist()
@require_admin()
@handle_api_errors
def approve_upgrade_request(request_id):
	"""Approve an account upgrade request and update account level via GraphQL"""
	req = frappe.get_doc("Account Upgrade Request", request_id, for_update=True)

	if req.status != "Pending":
		return {"success": False, "error": f"Request has already been {req.status.lower()}"}

	# Get account details to retrieve the UID
	client = GraphQLClient()
	account = client.get_account_by_phone(req.phone_number)
	if not account:
		return {"success": False, "error": "Account not found in external system"}

	# Create ERP records (Customer, Address, Bank Account) before mutation
	erp_party = None
	if req.requested_level in ("TWO", "THREE"):
		erp_errors, erp_party = _create_erp_records(req)
		if erp_errors:
			return {"success": False, "error": f"ERP record creation failed: {'; '.join(erp_errors)}"}

	# Update account level via GraphQL (ZERO, ONE, TWO, THREE)
	result = client.update_account_level(
		uid=account["id"],
		level=req.requested_level,
		erp_party=erp_party,
	)

	if result.get("errors"):
		error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
		return {"success": False, "errors": error_messages}

	# Update local request record
	req.status = "Approved"
	req.save()
	frappe.db.commit()

	audit_log(
		"approve_upgrade",
		"Account Upgrade Request",
		request_id,
		{"phone": req.phone_number, "level": req.requested_level},
	)

	return {
		"success": True,
		"message": "Request approved and account level updated.",
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def reject_upgrade_request(request_id, reason=None):
	"""Reject an account upgrade request (local record only, no level change)"""
	req = frappe.get_doc("Account Upgrade Request", request_id, for_update=True)

	if req.status != "Pending":
		return {"success": False, "error": f"Request has already been {req.status.lower()}"}

	# Update local request record only - rejection doesn't change account level
	req.status = "Rejected"
	req.support_note = reason or "No reason provided"
	req.save()

	frappe.db.commit()
	audit_log(
		"reject_upgrade", "Account Upgrade Request", request_id, {"reason": reason or "No reason provided"}
	)
	return {"success": True, "message": "Request rejected."}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def approve_bank_account_update_request(request_id):
	"""Approve a bank account update request by patching the Bank Account in place.

	The Bank Account document's `name` (and its `is_default` flag) are preserved so
	that in-flight cashout offers and Cashout documents that reference the account
	by name keep resolving. Currency is never changed (it is locked at request time).
	"""
	req = frappe.get_doc("Bank Account Update Request", request_id, for_update=True)

	if req.status != "Pending":
		return {"success": False, "error": f"Request has already been {req.status.lower()}"}

	if not req.bank_name or not req.bank_branch or not req.account_type or not req.account_number:
		return {"success": False, "error": "Request is missing required bank details."}

	bank_account = frappe.get_doc("Bank Account", req.bank_account, for_update=True)

	# Re-verify ownership at approval time (mirror of Cashout.validate).
	if bank_account.party_type != "Customer" or bank_account.party != req.party:
		return {"success": False, "error": "Bank Account does not belong to the requesting customer."}

	# Reject a collision with a different account's number (mirror of create-time dedupe).
	if req.account_number and frappe.db.exists(
		"Bank Account",
		{"bank_account_no": req.account_number, "name": ["!=", bank_account.name]},
	):
		return {"success": False, "error": "Another bank account already uses that account number."}

	old_values = {
		"bank": bank_account.bank,
		"branch_code": bank_account.branch_code,
		"account_type": bank_account.account_type,
		"bank_account_no": bank_account.bank_account_no,
	}

	# Ensure the Bank master exists before linking to it (mirror of _create_erp_records).
	if req.bank_name and not frappe.db.exists("Bank", req.bank_name):
		frappe.get_doc({"doctype": "Bank", "bank_name": req.bank_name}).insert(ignore_permissions=True)

	# Patch in place. `name` and `is_default` are intentionally left untouched.
	bank_account.bank = req.bank_name
	bank_account.branch_code = req.bank_branch or ""
	bank_account.account_type = req.account_type or ""
	bank_account.bank_account_no = req.account_number
	bank_account.save(ignore_permissions=True)

	req.status = "Approved"
	req.save()

	# Supersede any other still-open requests for the same account so a stale
	# duplicate can't later be approved and revert the account to old details.
	siblings = frappe.get_all(
		"Bank Account Update Request",
		filters={"bank_account": req.bank_account, "status": "Pending", "name": ["!=", req.name]},
		pluck="name",
	)
	for sibling in siblings:
		frappe.db.set_value("Bank Account Update Request", sibling, "status", "Closed")

	frappe.db.commit()

	audit_log(
		"approve_bank_account_update",
		"Bank Account Update Request",
		request_id,
		{
			"bank_account": req.bank_account,
			"old": old_values,
			"new": {
				"bank": req.bank_name,
				"branch_code": req.bank_branch,
				"account_type": req.account_type,
				"bank_account_no": req.account_number,
			},
		},
	)

	return {"success": True, "message": "Bank account details updated."}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def reject_bank_account_update_request(request_id, reason=None):
	"""Reject a bank account update request (local record only; account unchanged)."""
	req = frappe.get_doc("Bank Account Update Request", request_id, for_update=True)

	if req.status != "Pending":
		return {"success": False, "error": f"Request has already been {req.status.lower()}"}

	req.status = "Rejected"
	req.support_note = reason or "No reason provided"
	req.save()

	frappe.db.commit()
	audit_log(
		"reject_bank_account_update",
		"Bank Account Update Request",
		request_id,
		{"reason": reason or "No reason provided"},
	)
	return {"success": True, "message": "Request rejected."}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_id_document_url(file_key):
	"""Get pre-signed URL for ID document from Digital Ocean Spaces"""
	if not file_key:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "File key is required"}

	client = GraphQLClient()
	result = client.get_id_document_read_url(file_key)

	if result.get("errors"):
		error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
		frappe.logger().error(f"ID document URL errors: {error_messages}")
		frappe.response["http_status_code"] = 400
		return {"success": False, "errors": error_messages}

	return {"success": True, "url": result.get("readUrl")}


@frappe.whitelist()
def get_customer_bank_accounts(customer):
	accounts = frappe.get_all(
		"Bank Account",
		filters={"party_type": "Customer", "party": customer},
		fields=["name", "account_name", "bank", "bank_account_no", "account"],
	)
	for acct in accounts:
		acct["currency"] = frappe.get_value("Account", acct["account"], "account_currency")
	return accounts


# ── Account Hub helpers ──────────────────────────────────────────


def _update_local_upgrade_request_phone(username, phone):
	"""Best-effort local sync after Flash GraphQL phone update succeeds."""
	if not username or not phone:
		return 0

	records = frappe.get_all(
		"Account Upgrade Request",
		filters={"username": username},
		pluck="name",
		limit_page_length=50,
	)
	for name in records:
		doc = frappe.get_doc("Account Upgrade Request", name)
		doc.phone_number = phone
		doc.save(ignore_permissions=True)

	if records:
		frappe.db.commit()

	return len(records)


# ── Account Hub API ───────────────────────────────────────────────


@frappe.whitelist()
@require_admin()
@handle_api_errors
def search_account_smart(query):
	"""Smart search: auto-detect phone, email, username, or account ID.

	Account Hub should show Flash account data from the GraphQL API only. Local
	Account Upgrade Request rows can be stale and should not be returned as
	account-shaped fallback data.
	"""
	if not query or not str(query).strip():
		frappe.response["http_status_code"] = 400
		return {"error": "Search query is required"}

	query = str(query).strip()

	try:
		client = GraphQLClient()

		if query.startswith("+") or re.match(r"^\d{7,}$", query):
			account = client.get_account_by_phone(query)
		elif "@" in query:
			account = client.get_account_by_email(query)
		elif re.match(r"^[a-zA-Z0-9_-]{3,}$", query):
			account = client.get_account_by_username(query)
			if account is None:
				account = client.get_account_by_id(query)
		else:
			account = client.get_account_by_id(query)

		if account is not None:
			return account

		frappe.response["http_status_code"] = 404
		return {
			"error": "Account not found in Flash. Try searching by phone (+1...), email, username, or account ID."
		}

	except (ValueError, requests_lib.exceptions.RequestException, GraphQLError) as e:
		frappe.logger().error(f"Flash API unavailable for search_account_smart ('{query}'): {e}")
		frappe.response["http_status_code"] = 503
		return {"error": "Flash API unavailable. Account search could not be completed."}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_upgrade_requests_by_account(username):
	"""Get upgrade request records for a specific account by username."""
	if not username:
		return {"data": [], "total": 0}

	records = frappe.get_all(
		"Account Upgrade Request",
		filters={"username": username},
		fields=["*"],
		order_by="creation desc",
		limit_page_length=50,
	)

	return {"data": records, "total": len(records)}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def update_account_status_api(uid=None, account_uuid=None, username=None, status=None, comment=None):
	"""Update account status in Flash GraphQL.

	Account Hub should mutate Flash as the source of truth. Local Account Upgrade
	Request rows do not have the same account status semantics, so this endpoint
	intentionally does not write ACTIVE/LOCKED into request status fields.
	"""
	if not status:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Status is required"}

	account_uid = uid or account_uuid
	client = GraphQLClient()

	if not account_uid and username:
		account = client.get_account_by_username(username)
		if account:
			account_uid = account.get("id") or account.get("uuid")

	if not account_uid:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Account UID is required to update status in Flash"}

	result = client.update_account_status(account_uid, status, comment)
	audit_log("update_status", "Flash Account", account_uid, {"status": status, "comment": comment})
	return result or {"success": True}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def update_user_phone_api(account_uuid=None, phone=None, username=None):
	"""Update user phone in Flash GraphQL, then best-effort sync local request rows."""
	if not phone:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Phone is required"}

	client = GraphQLClient()

	if not account_uuid and username:
		account = client.get_account_by_username(username)
		if account:
			account_uuid = account.get("uuid")

	if not account_uuid:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Account UUID is required to update phone in Flash"}

	result = client.update_user_phone(account_uuid, phone)
	if result and result.get("errors"):
		return result

	local_updates = _update_local_upgrade_request_phone(username, phone)
	if isinstance(result, dict):
		result["local_updates"] = local_updates
		return result

	return {"success": True, "local_updates": local_updates}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def validate_merchant_api(merchant_id=None):
	"""Validate a merchant map entry in Flash GraphQL."""
	if not merchant_id:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Merchant ID is required"}

	client = GraphQLClient()
	return client.validate_merchant(merchant_id)


@frappe.whitelist()
@require_admin()
@handle_api_errors
def delete_merchant_api(merchant_id=None):
	"""Delete a merchant map entry in Flash GraphQL."""
	if not merchant_id:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Merchant ID is required"}

	client = GraphQLClient()
	return client.delete_merchant(merchant_id)


# ── Dashboard ────────────────────────────────────────────────────


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_dashboard_stats():
	"""Get summary stats for the admin dashboard."""
	pending = frappe.db.count("Account Upgrade Request", {"status": "Pending"})
	approved = frappe.db.count("Account Upgrade Request", {"status": "Approved"})
	rejected = frappe.db.count("Account Upgrade Request", {"status": "Rejected"})

	today = frappe.utils.nowdate()
	approved_today = frappe.db.count(
		"Account Upgrade Request",
		{
			"status": "Approved",
			"modified": [">=", today],
		},
	)

	all_records = frappe.get_all(
		"Account Upgrade Request",
		fields=[
			"name",
			"username",
			"full_name",
			"phone_number",
			"email",
			"requested_level",
			"current_level",
			"status",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=500,
	)

	return {
		"upgrade_requests": {
			"pending": pending,
			"approved": approved,
			"rejected": rejected,
			"approved_today": approved_today,
		},
		"recent_requests": all_records[:8],
		"all_requests": all_records,
		"total_requests": pending + approved + rejected,
	}


# ── Cashout Requests API ──────────────────────────────────────────


CASHOUT_STATUS_DISPLAY_MAP = {
	"Pending": "Pending",
	"Draft": "Pending",
	"In Progress": "In Progress",
	"Completed": "Paid",
	"Canceled": "Canceled",
}


def _enrich_cashout(cashout_doc) -> dict:
	"""Enrich a Cashout doctype record with Customer and Bank Account fields."""
	row = dict(cashout_doc)

	# Resolve Customer display fields
	customer_info = {}
	if row.get("customer"):
		customer_info = (
			frappe.db.get_value(
				"Customer",
				row["customer"],
				["customer_name", "mobile_no", "email_id"],
				as_dict=True,
			)
			or {}
		)
	row["username"] = row.get("customer", "")
	row["full_name"] = customer_info.get("customer_name", "")
	row["phone_number"] = customer_info.get("mobile_no", "")
	row["email"] = customer_info.get("email_id", "")

	# Resolve Bank Account display fields
	bank_info = {}
	if row.get("bank_account"):
		bank_info = (
			frappe.db.get_value(
				"Bank Account",
				row["bank_account"],
				["bank", "bank_account_no", "account_type", "account_name"],
				as_dict=True,
			)
			or {}
		)
	# Mask account number for display
	raw_no = bank_info.get("bank_account_no") or ""
	row["bank_name"] = bank_info.get("bank", "")
	row["account_number"] = f"****{raw_no[-4:]}" if len(raw_no) >= 4 else raw_no
	row["account_type"] = bank_info.get("account_type", "")
	row["bank_label"] = bank_info.get("account_name", "")

	# Map fields to match JS expectations
	row["send"] = row.get("user_pays")
	row["flash_fee"] = row.get("flash_fee")
	row["exchange_rate"] = row.get("exchange_rate")
	row["offer_id"] = row.get("transaction_id", "")
	row["journal_entry"] = row.get("journal_entry", "")
	row["payment_entry"] = row.get("payment_journal_entry", "")

	# Derive receive amounts by currency
	currency = row.get("currency", "USD")
	receives = row.get("user_receives", 0)
	rate = row.get("exchange_rate", 1) or 1
	if currency == "JMD":
		row["receive_jmd"] = receives
		row["receive_usd"] = round(row.get("user_pays", 0) - row.get("flash_fee", 0), 2)
	else:
		row["receive_jmd"] = round(receives * rate, 2) if receives else 0
		row["receive_usd"] = receives

	# Payment entry fields (populated when payment_journal_entry exists)
	if row.get("payment_journal_entry"):
		pe = frappe.db.get_value(
			"Journal Entry",
			row["payment_journal_entry"],
			["total_debit", "posting_date"],
			as_dict=True,
		)
		if pe:
			row["pe_paid_amount"] = pe.get("total_debit")
			row["pe_posting_date"] = str(pe.get("posting_date", ""))
			row["pe_currency"] = currency
			row["pe_mode_of_payment"] = "Bank Transfer"

	# Display status
	original_status = row.get("status", "Pending")
	row["display_status"] = CASHOUT_STATUS_DISPLAY_MAP.get(original_status, "Pending")

	return row


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_cashout_requests(status=None, page=1, page_size=10):
	"""Get paginated cashout requests from the Cashout doctype."""
	page = int(page)
	page_size = min(int(page_size), 100)
	offset = (page - 1) * page_size

	# Map JS statuses back to doctype statuses
	status_map = {
		"Pending": ["Pending", "Draft", "In Progress"],
		"Paid": ["Completed"],
		"Canceled": ["Canceled"],
		"Cancelled": ["Canceled"],  # JS spelling variant from PR
	}

	doc_filters = []
	if status:
		mapped = status_map.get(status, [status])
		doc_filters = [["status", "in", mapped]]

	total_count = frappe.db.count("Cashout", filters=doc_filters or None)
	records = frappe.get_all(
		"Cashout",
		filters=doc_filters or None,
		fields=["*"],
		order_by="creation desc",
		limit_start=offset,
		limit_page_length=page_size,
	)

	data = [_enrich_cashout(r) for r in records]

	return {
		"data": data,
		"total": total_count,
		"page": page,
		"page_size": page_size,
		"total_pages": max(1, (total_count + page_size - 1) // page_size),
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def search_cashout_account(id: str):
	"""Search cashout requests by customer name or phone number."""
	if not id:
		frappe.response["http_status_code"] = 400
		return {"error": "Phone number or Username is required"}

	# Find Customer doctypes matching the query
	import re as _re

	has_digits = len(_re.sub(r"\D", "", id)) >= 3

	digits_only = _re.sub(r"\D", "", id) if has_digits else ""
	customer_filters = []
	if has_digits:
		customer_filters.append(["mobile_no", "like", f"%{digits_only}%"])
	customer_filters.append(["customer_name", "like", f"%{id}%"])

	matching_customers = frappe.get_all(
		"Customer",
		filters=customer_filters,
		pluck="name",
		limit_page_length=50,
	)

	if not matching_customers:
		frappe.response["http_status_code"] = 404
		return {"error": "No cashout requests found for this customer"}

	records = frappe.get_all(
		"Cashout",
		filters=[["customer", "in", matching_customers]],
		fields=["*"],
		order_by="creation desc",
		limit_page_length=50,
	)

	if not records:
		frappe.response["http_status_code"] = 404
		return {"error": "No cashout requests found for this customer"}

	return [_enrich_cashout(r) for r in records]


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_bridge_transfer_requests(
	status=None, transaction_type=None, provider=None, query=None, page=1, page_size=10
):
	"""Get paginated provider transfer audit records for the Transfer Requests page."""
	page = max(int(page or 1), 1)
	page_size = min(max(int(page_size or 10), 1), 100)
	offset = (page - 1) * page_size

	filters = {}
	if status:
		filters["status"] = status
	if transaction_type:
		filters["transaction_type"] = transaction_type
	if provider:
		filters["provider"] = provider

	or_filters = None
	if query:
		like_query = f"%{query}%"
		or_filters = [
			["request_id", "like", like_query],
			["bridge_transfer_id", "like", like_query],
			["bridge_customer_id", "like", like_query],
			["account_id", "like", like_query],
			["wallet_id", "like", like_query],
			["ibex_tx_hash", "like", like_query],
			["source_event_id", "like", like_query],
		]

	fields = [
		"name",
		"request_id",
		"transaction_type",
		"status",
		"provider",
		"asset",
		"network",
		"amount",
		"currency",
		"developer_fee",
		"initial_amount",
		"subtotal_amount",
		"final_amount",
		"account_id",
		"wallet_id",
		"bridge_customer_id",
		"bridge_transfer_id",
		"ibex_tx_hash",
		"address",
		"source_event_id",
		"source_event_type",
		"source_systems_seen",
		"first_seen_at",
		"last_seen_at",
		"raw_payload_json",
		"failure_reason",
		"creation",
		"modified",
	]

	count_rows = frappe.get_all(
		"Bridge Transfer Request",
		filters=filters or None,
		or_filters=or_filters,
		fields=["name"],
	)
	records = frappe.get_all(
		"Bridge Transfer Request",
		filters=filters or None,
		or_filters=or_filters,
		fields=fields,
		order_by="modified desc",
		limit_start=offset,
		limit_page_length=page_size,
	)

	total_count = len(count_rows)
	return {
		"data": [dict(record) for record in records],
		"total": total_count,
		"page": page,
		"page_size": page_size,
		"total_pages": max(1, (total_count + page_size - 1) // page_size),
	}


def _get_cashout_for_action(cashout_id):
	if not cashout_id:
		frappe.response["http_status_code"] = 400
		return None, {"success": False, "error": "Cashout ID is required"}

	try:
		return frappe.get_doc("Cashout", cashout_id), None
	except frappe.DoesNotExistError:
		frappe.response["http_status_code"] = 404
		return None, {"success": False, "error": "Cashout request not found"}


def _submit_cashout_if_needed(doc):
	if doc.docstatus == 2 or doc.status == "Canceled":
		return {"success": False, "error": "Canceled cashout requests cannot be modified"}

	if doc.status == "Completed":
		return {"success": False, "error": "Completed cashout requests cannot be modified"}

	if doc.docstatus == 0:
		doc.submit()
		doc.reload()

	return None


def _append_cashout_confirmation_code(doc, confirmation_code):
	code = (confirmation_code or "").strip()
	if not code:
		return

	timestamp = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
	line = f"Bank confirmation code: {code} ({frappe.session.user}, {timestamp})"
	remarks = (doc.remarks or "").strip()
	updated_remarks = f"{remarks}\n{line}" if remarks else line
	doc.db_set("remarks", updated_remarks, update_modified=True)
	doc.remarks = updated_remarks


def _cashout_notification_amount_cents(doc):
	amount = Decimal(str(doc.user_receives or 0)) * Decimal("100")
	return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _is_flash_username_candidate(value):
	return bool(value and re.match(r"^[a-zA-Z0-9_-]{3,}$", str(value).strip()))


def _first_cashout_account_match(client, doc):
	customer_info = {}
	if doc.customer:
		customer_info = (
			frappe.db.get_value(
				"Customer",
				doc.customer,
				["customer_name", "mobile_no", "email_id"],
				as_dict=True,
			)
			or {}
		)

	username_candidates = []
	for value in (doc.customer, customer_info.get("customer_name")):
		if value and value not in username_candidates:
			username_candidates.append(value)

	for username in username_candidates:
		if not _is_flash_username_candidate(username):
			continue
		account = client.get_account_by_username(username)
		if account:
			return account

	phone = customer_info.get("mobile_no")
	if phone:
		account = client.get_account_by_phone(phone)
		if account:
			return account

	email = customer_info.get("email_id")
	if email:
		account = client.get_account_by_email(email)
		if account:
			return account

	return None


def _get_cashout_completion_notification_context(doc):
	client = GraphQLClient()
	account = _first_cashout_account_match(client, doc)
	if not account:
		return {"success": False, "error": "Flash account not found for this Cashout customer"}

	account_uuid = account.get("uuid") or account.get("id")
	if not account_uuid:
		return {"success": False, "error": "Flash account is missing UUID"}

	return {
		"success": True,
		"client": client,
		"account_id": account_uuid,
		"amount": _cashout_notification_amount_cents(doc),
		"currency": doc.currency,
	}


def _send_cashout_completion_notification(notification_context):
	result = notification_context["client"].send_cashout_notification(
		account_id=notification_context["account_id"],
		amount=notification_context["amount"],
		currency=notification_context["currency"],
	)

	if result.get("errors"):
		error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
		return {"success": False, "error": "; ".join(error_messages)}

	if not result.get("success"):
		return {"success": False, "error": "Flash cashout notification mutation returned success=false"}

	return {
		"success": True,
		"account_id": notification_context["account_id"],
		"amount": notification_context["amount"],
		"currency": notification_context["currency"],
	}


def _notify_cashout_completion(doc):
	"""Best-effort Flash notification. Never blocks settlement: by the time an
	operator confirms here the bank transfer has already happened out-of-band,
	so a failed account lookup or send must not prevent recording the payment
	(it used to hard-block settlement when the customer couldn't be matched to
	a Flash account)."""
	try:
		context = _get_cashout_completion_notification_context(doc)
		if not context.get("success"):
			return {"success": False, "error": context.get("error")}
		return _send_cashout_completion_notification(context)
	except Exception as e:
		return {"success": False, "error": str(e)}


def _settle_cashout(doc, confirmation_code=None):
	submit_error = _submit_cashout_if_needed(doc)
	if submit_error:
		return submit_error

	_append_cashout_confirmation_code(doc, confirmation_code)

	# Row-lock and re-read before deciding to pay: two concurrent confirms
	# (double-click, second operator, retry racing a slow request) otherwise
	# both observe an empty payment_journal_entry and post duplicate journal
	# entries. The second request blocks here until the first commits, then
	# sees the entry and takes the already-paid path.
	existing_payment_entry = frappe.db.get_value(
		"Cashout", doc.name, "payment_journal_entry", for_update=True
	)
	if existing_payment_entry:
		doc.reload()
		if doc.status != "Completed":
			doc.db_set("status", "Completed", update_modified=True)
			doc.status = "Completed"
		settled_message = f"Cashout already has payment journal entry {doc.payment_journal_entry}"
	else:
		doc.create_payment_journal_entry(reference_no=confirmation_code, reference_date=frappe.utils.today())
		doc.reload()
		settled_message = f"Payment recorded successfully. Journal Entry {doc.payment_journal_entry} created"

	notification = _notify_cashout_completion(doc)
	notification_sent = bool(notification.get("success"))

	result = {
		"success": True,
		"status": doc.status,
		"payment_entry": doc.payment_journal_entry,
		"notification_sent": notification_sent,
	}
	if notification_sent:
		result["message"] = f"{settled_message}; Flash notification sent."
	else:
		result["notification_error"] = notification.get("error")
		result["message"] = (
			f"{settled_message}. Flash notification NOT sent: {notification.get('error')} — "
			"the cashout is settled; re-run the action to retry the notification."
		)
	return result


@frappe.whitelist()
@require_financial()
@handle_api_errors
def create_cashout_request(cashout_id):
	"""Submit a draft cashout so it is ready for out-of-band bank settlement."""
	doc, error = _get_cashout_for_action(cashout_id)
	if error:
		return error

	if doc.status in ("Completed", "Canceled") or doc.docstatus == 2:
		return {"success": False, "error": f"Cashout request status is '{doc.status}'; cannot create"}

	if doc.docstatus == 0:
		doc.submit()
		doc.reload()

	return {
		"success": True,
		"status": doc.status,
		"journal_entry": doc.journal_entry,
		"message": f"Cashout request {doc.name} is ready for settlement.",
	}


@frappe.whitelist()
@require_financial()
@handle_api_errors
def confirm_cashout_payment(cashout_id, confirmation_code=None):
	"""Record a bank confirmation code and settle the cashout payment."""
	confirmation_code = (confirmation_code or "").strip()
	if not confirmation_code:
		frappe.response["http_status_code"] = 400
		return {"success": False, "error": "Confirmation code is required"}

	doc, error = _get_cashout_for_action(cashout_id)
	if error:
		return error

	result = _settle_cashout(doc, confirmation_code=confirmation_code)
	if result.get("success"):
		audit_log(
			"confirm_cashout_payment",
			"Cashout",
			doc.name,
			{"confirmation_code": confirmation_code, "payment_entry": result.get("payment_entry")},
		)
		# Keep _settle_cashout's message — it states truthfully whether the
		# Flash notification went out; just prefix the confirmation context.
		result["message"] = f"Payment confirmed with code {confirmation_code}. {result.get('message', '')}"
	return result


@frappe.whitelist()
@require_financial()
@handle_api_errors
def complete_cashout(cashout_id):
	"""Settle a cashout without requiring a bank confirmation code."""
	doc, error = _get_cashout_for_action(cashout_id)
	if error:
		return error

	result = _settle_cashout(doc)
	if result.get("success"):
		audit_log(
			"complete_cashout",
			"Cashout",
			doc.name,
			{"payment_entry": result.get("payment_entry")},
		)
	return result


@frappe.whitelist()
@require_financial()
@handle_api_errors
def record_cashout_payment(cashout_id):
	"""Record payment for a cashout by calling create_payment_journal_entry."""
	return complete_cashout(cashout_id)

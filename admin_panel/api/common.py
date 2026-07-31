"""Shared helpers for admin_panel API endpoints."""

import functools

import frappe
import requests

from .bridge_client import BridgeApiError
from .graphql_client import GraphQLError
from .ibex_client import IbexError


def handle_api_errors(func):
	"""Decorator to handle common API errors consistently"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		try:
			return func(*args, **kwargs)
		except (frappe.ValidationError, frappe.PermissionError):
			# Deliberate frappe.throw() calls are user-facing by design —
			# let frappe's normal messaging surface them instead of masking
			# them as a generic internal error.
			raise
		except (GraphQLError, IbexError, BridgeApiError) as e:
			frappe.logger().error(f"Upstream API error in {func.__name__}: {e}")
			frappe.response["http_status_code"] = 500
			return {"success": False, "error": str(e)}
		except requests.exceptions.RequestException as e:
			frappe.logger().error(f"Request error in {func.__name__}: {e}")
			frappe.response["http_status_code"] = 500
			return {"success": False, "error": str(e)}
		except ValueError as e:
			frappe.logger().error(f"Configuration error in {func.__name__}: {e}")
			frappe.response["http_status_code"] = 500
			return {"success": False, "error": str(e)}
		except Exception as e:
			frappe.logger().error(f"Unexpected error in {func.__name__}: {e}")
			frappe.response["http_status_code"] = 500
			return {"success": False, "error": "An internal error occurred"}

	return wrapper

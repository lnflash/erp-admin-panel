"""Append-only, hash-chained compliance ledger (Compliance Audit Event).

Every reviewer decision, evidence view and settings change lands here as one
row whose ``hash`` covers the row's own content AND the previous row's hash,
so a row cannot be edited, removed or inserted out of order without breaking
every hash after it. ``verify_chain`` recomputes the whole chain;
``latest_anchor`` exposes the current head so it can be published somewhere
this database cannot reach (``post_daily_anchor`` posts it to the ops Discord
webhook once a day).

The doctype grants nobody create/write/delete — rows are inserted only from
``record_event`` with ``ignore_permissions=True`` — and its controller refuses
updates and deletes even for Administrator. The existing ``auth.audit_log``
Comment remains as a traceability aid; this ledger is the audit of record.
"""

import hashlib
import json
from datetime import datetime

import frappe
import requests

from .auth import require_admin
from .common import handle_api_errors

DOCTYPE = "Compliance Audit Event"
GENESIS = "GENESIS"

# Columns verify_chain needs to recompute a row's hash, in chain order.
CHAIN_FIELDS = (
	"name",
	"event_type",
	"actor",
	"reference_doctype",
	"reference_name",
	"payload_json",
	"payload_sha256",
	"prev_hash",
	"hash",
	"created_at",
)
CHAIN_ORDER = "created_at asc, creation asc"
HEAD_ORDER = "created_at desc, creation desc"


def canonical_json(payload) -> str:
	"""Key-order independent, whitespace-free JSON — the hashed form."""
	return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def created_at_iso(value) -> str:
	"""Canonical ``created_at`` string for hashing.

	Frappe hands the value back as a naive ``datetime`` on read and accepts
	either a ``datetime`` or a string on write, so the hash input is pinned
	to one representation (``YYYY-MM-DDTHH:MM:SS.ffffff``, microseconds
	always present) regardless of which side of the round trip we are on.
	"""
	if isinstance(value, datetime):
		parsed = value
	else:
		parsed = datetime.fromisoformat(str(value))
	return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _text(value) -> str:
	"""Hash material: None → "", everything else its str()."""
	return "" if value is None else str(value)


def compute_hash(prev_hash, event_type, actor, reference_doctype, reference_name, payload_sha256, created_at):
	"""The row hash. ``None`` reference fields hash as empty strings so a row
	written with ``reference_doctype=None`` verifies identically once the
	database hands it back as NULL."""
	material = "|".join(
		[
			prev_hash or GENESIS,
			_text(event_type),
			_text(actor),
			_text(reference_doctype),
			_text(reference_name),
			_text(payload_sha256),
			created_at_iso(created_at),
		]
	)
	return sha256_hex(material)


def _head_hash():
	"""Hash of the newest row, or GENESIS.

	Read with ``FOR UPDATE`` so two concurrent writers serialise on the head
	row instead of both chaining onto it — see ``record_event``.
	"""
	try:
		value = frappe.db.get_value(DOCTYPE, {}, "hash", order_by=HEAD_ORDER, for_update=True)
	except TypeError:
		# Older frappe.db.get_value without for_update: fall back to a plain
		# read (the unique index on `hash` and verify_chain still catch a
		# fork; it just is not prevented).
		value = frappe.db.get_value(DOCTYPE, {}, "hash", order_by=HEAD_ORDER)
	return value or GENESIS


def record_event(event_type, reference_doctype, reference_name, payload) -> str:
	"""Append one event and return its ``hash``.

	``actor`` is ``frappe.session.user``. The payload is stored as canonical
	JSON and hashed; the row hash chains onto the current head row.

	Concurrency: two requests appending at the same instant both read the
	head, so both could chain onto the same ``prev_hash`` and the second
	would be a fork that ``verify_chain`` reports as ``first_bad``. The head
	read is a ``SELECT ... FOR UPDATE``, which makes a second writer wait for
	the first transaction to commit on InnoDB and then re-read the new
	head, so under the default REPEATABLE READ this is prevented in
	practice — but only while every writer goes through this function in
	its own transaction. A writer that batches several events in one
	transaction chains correctly by construction (the head it wrote is
	visible to its own next read). The unique index on ``hash`` rejects an
	exact duplicate outright.
	"""
	if not event_type:
		raise ValueError("event_type is required")
	payload_json = canonical_json(payload)
	payload_sha256 = sha256_hex(payload_json)
	actor = frappe.session.user
	created_at = frappe.utils.now_datetime()
	prev_hash = _head_hash()
	row_hash = compute_hash(
		prev_hash,
		event_type,
		actor,
		reference_doctype,
		reference_name,
		payload_sha256,
		created_at,
	)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"event_type": event_type,
			"actor": actor,
			"reference_doctype": reference_doctype,
			"reference_name": str(reference_name) if reference_name is not None else None,
			"payload_json": payload_json,
			"payload_sha256": payload_sha256,
			"prev_hash": prev_hash,
			"hash": row_hash,
			"created_at": created_at,
		}
	)
	doc.insert(ignore_permissions=True)
	return row_hash


def _chain_rows(limit=None):
	kwargs = {"limit_page_length": limit} if limit else {}
	return frappe.get_all(DOCTYPE, fields=list(CHAIN_FIELDS), order_by=CHAIN_ORDER, **kwargs)


def _row_is_consistent(row, prev_hash) -> bool:
	try:
		payload = json.loads(row.get("payload_json") or "{}")
	except ValueError:
		return False
	if sha256_hex(canonical_json(payload)) != row.get("payload_sha256"):
		return False
	if (row.get("prev_hash") or GENESIS) != prev_hash:
		return False
	expected = compute_hash(
		prev_hash,
		row.get("event_type"),
		row.get("actor"),
		row.get("reference_doctype"),
		row.get("reference_name"),
		row.get("payload_sha256"),
		row.get("created_at"),
	)
	return row.get("hash") == expected


def verify_chain(limit=None) -> dict:
	"""Recompute every hash in created order.

	Returns ``{"ok", "checked", "first_bad"}`` — ``first_bad`` is the name
	of the first row whose payload, prev_hash or hash does not verify, and
	``checked`` the number of rows that verified before it.
	"""
	prev_hash = GENESIS
	checked = 0
	for row in _chain_rows(limit):
		if not _row_is_consistent(row, prev_hash):
			return {"ok": False, "checked": checked, "first_bad": row.get("name")}
		prev_hash = row.get("hash")
		checked += 1
	return {"ok": True, "checked": checked, "first_bad": None}


def latest_anchor() -> dict:
	"""The chain head: ``{"hash", "created_at", "count"}``."""
	count = frappe.db.count(DOCTYPE)
	head = frappe.get_all(DOCTYPE, fields=["hash", "created_at"], order_by=HEAD_ORDER, limit_page_length=1)
	if not head:
		return {"hash": GENESIS, "created_at": None, "count": count}
	return {
		"hash": head[0].get("hash"),
		"created_at": created_at_iso(head[0].get("created_at")),
		"count": count,
	}


@frappe.whitelist()
@require_admin()
@handle_api_errors
def verify_audit_chain(limit=None):
	return verify_chain(int(limit) if limit else None)


@frappe.whitelist()
@require_admin()
@handle_api_errors
def get_audit_anchor():
	return latest_anchor()


def post_daily_anchor():
	"""Scheduler job (hooks.scheduler_events["daily"]): publish the chain head.

	Posts ``{count, hash, created_at}`` to ``ops_discord_webhook_url`` from
	site config so the head lives somewhere a database edit cannot reach.
	No-op when the key is not configured. Requires a scheduler worker.
	"""
	url = frappe.conf.get("ops_discord_webhook_url")
	if not url:
		return None
	anchor = latest_anchor()
	body = {
		"content": (
			f"Compliance audit anchor: count={anchor['count']} "
			f"hash={anchor['hash']} created_at={anchor['created_at']}"
		),
		"embeds": [
			{
				"title": "Compliance audit chain anchor",
				"fields": [
					{"name": "count", "value": str(anchor["count"]), "inline": True},
					{"name": "created_at", "value": str(anchor["created_at"]), "inline": True},
					{"name": "hash", "value": str(anchor["hash"])},
				],
			}
		],
	}
	response = requests.post(url, json=body, timeout=10)
	response.raise_for_status()
	return anchor

"""Shared no-Frappe-runtime stubs for the ID-verification test modules.

Same approach as the other behavioral tests in this suite: install functional
stand-ins for ``frappe`` (and the ``requests`` / ``jwt`` imports the api
package drags in) into ``sys.modules`` BEFORE importing the module under
test, then patch the call-time surfaces per test via ``monkeypatch``.

``FakeFrappe`` is an in-memory stand-in for the slice of the frappe API the
ledger, the decision endpoints and the seeders touch: ``get_doc`` /
``new_doc`` / ``get_all`` / ``db.get_value`` / ``db.exists`` / ``db.count``
with real (if naive) filter and ``order_by`` semantics, so the hash chain is
exercised against ordered rows rather than canned return values.
"""

import copy
import sys
import types
from datetime import datetime, timedelta

import pytest


def ensure_module(name):
	try:
		__import__(name)
	except ImportError:
		sys.modules.setdefault(name, types.ModuleType(name))
	return sys.modules[name]


frappe = ensure_module("frappe")
frappe_utils = ensure_module("frappe.utils")
if not hasattr(frappe, "utils"):
	frappe.utils = frappe_utils
frappe_model = ensure_module("frappe.model")
frappe_document = ensure_module("frappe.model.document")
if not hasattr(frappe_document, "Document"):

	class _Document:  # stand-in for frappe.model.document.Document
		pass

	frappe_document.Document = _Document
if not hasattr(frappe_model, "document"):
	frappe_model.document = frappe_document

if not hasattr(frappe, "whitelist"):
	frappe.whitelist = lambda *args, **kwargs: lambda func: func
if not hasattr(frappe, "session"):
	# "Administrator" short-circuits require_roles' role lookup.
	frappe.session = types.SimpleNamespace(user="Administrator")
if not hasattr(frappe, "get_roles"):
	frappe.get_roles = lambda user=None: ["System Manager"]
if not hasattr(frappe, "ValidationError"):
	frappe.ValidationError = type("ValidationError", (Exception,), {})
if not hasattr(frappe, "PermissionError"):
	frappe.PermissionError = type("PermissionError", (Exception,), {})
if not hasattr(frappe, "DoesNotExistError"):
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
if not hasattr(frappe, "response"):
	frappe.response = {}

_requests = ensure_module("requests")
if not hasattr(_requests, "exceptions"):
	_requests.exceptions = types.SimpleNamespace(RequestException=type("RequestException", (Exception,), {}))
ensure_module("jwt")


class AttrDict(dict):
	"""Stand-in for frappe._dict: rows support both row["x"] and row.x."""

	def __getattr__(self, name):
		if name.startswith("_"):
			raise AttributeError(name)
		return self.get(name)


class Thrown(Exception):
	"""What the stubbed frappe.throw raises."""


class FakeDoc:
	"""Attribute-bag document backed by a FakeFrappe store."""

	def __init__(self, store, data):
		object.__setattr__(self, "_store", store)
		object.__setattr__(self, "_inserted", "name" in data and data.get("name") is not None)
		object.__setattr__(self, "flags", types.SimpleNamespace())
		for key, value in data.items():
			object.__setattr__(self, key, value)

	def __getattr__(self, name):
		# Unknown fields read as None, like a Document field that was never set.
		if name.startswith("_"):
			raise AttributeError(name)
		return None

	def get(self, key, default=None):
		value = getattr(self, key, None)
		return default if value is None else value

	def set(self, key, value):
		setattr(self, key, value)

	def update(self, values):
		for key, value in values.items():
			setattr(self, key, value)
		return self

	def is_new(self):
		return not self._inserted

	def as_dict(self):
		return {k: v for k, v in vars(self).items() if not k.startswith("_") and k != "flags"}

	def get_doc_before_save(self):
		return getattr(self, "_doc_before_save", None)

	def insert(self, ignore_permissions=False):
		self._store.insert(self, ignore_permissions=ignore_permissions)
		object.__setattr__(self, "_inserted", True)
		return self

	def save(self, ignore_permissions=False):
		if not self._inserted:
			return self.insert(ignore_permissions=ignore_permissions)
		self._store.update(self)
		return self


def _matches(row, filters):
	if filters is None:
		return True
	if isinstance(filters, str):
		return row.get("name") == filters
	for key, expected in filters.items():
		actual = row.get(key)
		if isinstance(expected, list | tuple):
			op, operand = expected
			if op == "in":
				if actual not in operand:
					return False
			elif op == ">=":
				if actual is None or actual < operand:
					return False
			elif op == "is":
				if (operand == "set") != (actual is not None):
					return False
			else:
				raise NotImplementedError(op)
		elif actual != expected:
			return False
	return True


def _ordered(rows, order_by):
	if not order_by:
		return list(rows)
	ordered = list(rows)
	for clause in reversed([c.strip() for c in order_by.split(",") if c.strip()]):
		parts = clause.split()
		field = parts[0].strip("`")
		descending = len(parts) > 1 and parts[1].lower() == "desc"
		ordered.sort(key=lambda r: (r.get(field) is None, r.get(field)), reverse=descending)
	return ordered


class FakeFrappe:
	"""In-memory frappe: tables of dict rows, a monotonic clock, a session."""

	def __init__(self, user="reviewer@getflash.io"):
		self.tables = {}
		self.singles = {}
		self.user = user
		self.clock = datetime(2026, 9, 1, 12, 0, 0)
		self.counter = 0
		self.commits = 0
		self.rollbacks = 0
		self.warnings = []
		self.errors = []
		self.conf = {}
		self.response = {}
		self.autoname = {}
		# Writes are applied to `self.tables` immediately (there is no
		# pending-vs-flushed distinction like a real DB transaction), so
		# `rollback()` needs its own undo log: a deep-copied checkpoint taken
		# on every `commit()`, restored wholesale on `rollback()`. This lets
		# tests exercise "a write made after the last commit must not survive
		# an exception" the same way frappe's real request-cycle commit/
		# rollback would.
		self._checkpoint = self._snapshot()

	# -- clock --------------------------------------------------------------
	def now_datetime(self):
		self.clock = self.clock + timedelta(microseconds=1)
		return self.clock

	def now(self):
		return self.now_datetime().strftime("%Y-%m-%d %H:%M:%S.%f")

	# -- rows ---------------------------------------------------------------
	def rows(self, doctype):
		return self.tables.setdefault(doctype, [])

	def seed(self, doctype, *rows):
		for row in rows:
			doc = FakeDoc(self, {"doctype": doctype, **row})
			doc.insert(ignore_permissions=True)
		return self

	def insert(self, doc, ignore_permissions=False):
		self.counter += 1
		doctype = doc.doctype
		# (Compliance Audit Event has no create permission for anyone.)
		if doctype == "Compliance Audit Event" and not ignore_permissions:
			raise self.PermissionError("no create permission")
		if doc.get("name") is None:
			naming = self.autoname.get(doctype)
			object.__setattr__(doc, "name", naming(doc) if naming else f"{doctype}-{self.counter:04d}")
		object.__setattr__(doc, "creation", self.counter)
		self.rows(doctype).append(doc.as_dict())

	def update(self, doc):
		for row in self.rows(doc.doctype):
			if row.get("name") == doc.name:
				row.update(doc.as_dict())
				return
		raise KeyError(doc.name)

	# -- frappe.* surfaces --------------------------------------------------
	def get_doc(self, *args, **kwargs):
		if isinstance(args[0], dict):
			return FakeDoc(self, dict(args[0]))
		doctype = args[0]
		if len(args) == 1 or args[1] == doctype:
			# Single
			data = self.singles.setdefault(doctype, {"doctype": doctype, "name": doctype})
			return FakeDoc(self, dict(data))
		name = args[1]
		for row in self.rows(doctype):
			if row.get("name") == name:
				return FakeDoc(self, dict(row))
		raise frappe.DoesNotExistError(f"{doctype} {name} not found")

	def new_doc(self, doctype):
		return FakeDoc(self, {"doctype": doctype})

	def get_all(
		self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None, limit=None, **kwargs
	):
		rows = [r for r in self.rows(doctype) if _matches(r, filters)]
		rows = _ordered(rows, order_by)
		limit_page_length = limit_page_length or limit
		if limit_page_length:
			rows = rows[:limit_page_length]
		if fields:
			return [AttrDict({f: r.get(f) for f in fields}) for r in rows]
		return [AttrDict(r) for r in rows]

	# frappe.db.*
	def get_value(
		self,
		doctype,
		filters=None,
		fieldname="name",
		as_dict=False,
		order_by=None,
		for_update=False,
		**kwargs,
	):
		rows = _ordered([r for r in self.rows(doctype) if _matches(r, filters)], order_by)
		if not rows:
			return None
		row = rows[0]
		if isinstance(fieldname, list | tuple):
			if as_dict:
				return AttrDict({f: row.get(f) for f in fieldname})
			return tuple(row.get(f) for f in fieldname)
		return row.get(fieldname)

	def set_value(self, doctype, name, fieldname, value):
		for row in self.rows(doctype):
			if row.get("name") == name:
				row[fieldname] = value
				return
		raise KeyError(name)

	def exists(self, doctype, name):
		if isinstance(name, dict):
			return any(_matches(r, name) for r in self.rows(doctype))
		return any(r.get("name") == name for r in self.rows(doctype))

	def count(self, doctype, filters=None):
		return len([r for r in self.rows(doctype) if _matches(r, filters)])

	def commit(self):
		self.commits += 1
		self._checkpoint = self._snapshot()

	def rollback(self):
		self.rollbacks += 1
		# Restore from a fresh deep copy, not the checkpoint's own objects —
		# otherwise a write made after this rollback would mutate the
		# checkpoint in place and corrupt the next rollback.
		tables, singles, counter = self._checkpoint
		self.tables = copy.deepcopy(tables)
		self.singles = copy.deepcopy(singles)
		self.counter = counter

	def _snapshot(self):
		return copy.deepcopy(self.tables), copy.deepcopy(self.singles), self.counter

	def throw(self, msg, *args, **kwargs):
		raise Thrown(msg)

	def logger(self):
		return types.SimpleNamespace(
			warning=self.warnings.append, error=self.errors.append, info=lambda *a, **k: None
		)

	PermissionError = frappe.PermissionError


@pytest.fixture()
def fake(monkeypatch):
	"""Install a FakeFrappe onto the frappe stub for one test."""
	store = FakeFrappe()
	db = types.SimpleNamespace(
		get_value=store.get_value,
		set_value=store.set_value,
		exists=store.exists,
		count=store.count,
		commit=store.commit,
		rollback=store.rollback,
	)
	monkeypatch.setattr(frappe, "db", db, raising=False)
	monkeypatch.setattr(frappe, "get_doc", store.get_doc, raising=False)
	monkeypatch.setattr(frappe, "new_doc", store.new_doc, raising=False)
	monkeypatch.setattr(frappe, "get_all", store.get_all, raising=False)
	monkeypatch.setattr(frappe, "throw", store.throw, raising=False)
	monkeypatch.setattr(frappe, "logger", store.logger, raising=False)
	monkeypatch.setattr(frappe, "conf", store.conf, raising=False)
	monkeypatch.setattr(frappe, "response", store.response, raising=False)
	monkeypatch.setattr(frappe, "session", types.SimpleNamespace(user=store.user), raising=False)
	monkeypatch.setattr(frappe, "get_roles", lambda user=None: ["System Manager"], raising=False)
	monkeypatch.setattr(frappe_utils, "now_datetime", store.now_datetime, raising=False)
	monkeypatch.setattr(frappe_utils, "now", store.now, raising=False)
	return store

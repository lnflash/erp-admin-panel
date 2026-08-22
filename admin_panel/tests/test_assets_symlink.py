"""Tests for the runtime assets-symlink self-heal.

Why this exists: nginx serves ``/assets`` from ``sites/`` (``try_files``),
and in k8s ``sites/`` is a PVC mounted over the image's own sites dir — so
the symlink ``bench build`` bakes into the image is shadowed and the app's
public JS 404'd on every environment (found live on v1.23.0: frappe assets
200, admin_panel assets 404, both envs). The branch logic is a pure helper;
these run it against real tmp paths.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

import importlib.util
import os

# setup.py imports frappe at module level; load just the pure helper's source
# the way the other contract tests read text, then exec the single function.
SETUP_SRC = (REPO_ROOT / "admin_panel" / "admin_panel" / "setup.py").read_text()


def load_helper():
	import ast

	tree = ast.parse(SETUP_SRC)
	fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_ensure_symlink")
	ns = {}
	exec(compile(ast.Module(body=[fn], type_ignores=[]), "setup.py", "exec"), ns)
	return ns["_ensure_symlink"]


ensure = load_helper()


def test_creates_the_link_when_absent(tmp_path):
	target = tmp_path / "public"
	target.mkdir()
	link = tmp_path / "assets" / "admin_panel"
	link.parent.mkdir()

	assert ensure(str(link), str(target)) == "created"
	assert os.readlink(link) == str(target)


def test_correct_link_is_a_no_op(tmp_path):
	target = tmp_path / "public"
	target.mkdir()
	link = tmp_path / "admin_panel"
	os.symlink(str(target), str(link))

	assert ensure(str(link), str(target)) == "ok"


def test_wrong_link_is_repointed(tmp_path):
	"""A stale link (e.g. a bench moved between paths) must heal, not 404."""
	old = tmp_path / "old-public"
	new = tmp_path / "public"
	old.mkdir()
	new.mkdir()
	link = tmp_path / "admin_panel"
	os.symlink(str(old), str(link))

	assert ensure(str(link), str(new)) == "repointed"
	assert os.readlink(link) == str(new)


def test_dangling_link_is_repointed_not_crashed(tmp_path):
	"""islink is true and isdir false for a dangling link — the exists()
	shortcut would miss it and leave the 404 in place."""
	target = tmp_path / "public"
	target.mkdir()
	link = tmp_path / "admin_panel"
	os.symlink(str(tmp_path / "gone"), str(link))

	assert ensure(str(link), str(target)) == "repointed"
	assert os.readlink(link) == str(target)


def test_a_real_directory_is_left_alone(tmp_path):
	"""Setups that copy assets instead of symlinking keep their copy."""
	target = tmp_path / "public"
	target.mkdir()
	link = tmp_path / "admin_panel"
	link.mkdir()
	(link / "keep.js").write_text("x")

	assert ensure(str(link), str(target)) == "kept-dir"
	assert (link / "keep.js").exists()


def test_after_migrate_runs_the_self_heal():
	assert "ensure_public_assets_symlink()" in SETUP_SRC.split("def ensure_roles")[0]
	assert 'os.path.join(bench_path, "sites", "assets", "admin_panel")' in SETUP_SRC

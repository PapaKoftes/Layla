"""A file tool that fails must say WHERE it looked, and name an empty sandbox as the cause.

On the operator's machine every filesystem tool sat at or near a 0% success rate — read_file 0/13,
file_info 0/7, run_skill_pack 0/5, list_dir 2/26 — while every tool that does not touch the disk was
healthy (search_memories 22/22, list_tools 6/6, text_stats 4/4, count_tokens 3/3). One cause explained
all of it: `sandbox_root` pointed at ~/layla-workspace, a directory that exists and is completely
empty, so every relative path resolved somewhere with no files in it.

What the model received, 13 times, was `{"ok": false, "error": "File not found"}` — true, and
impossible to act on. Nothing anywhere reported that the assistant's entire reachable filesystem was
an empty folder while the operator's real code sat outside it. That is a silent failure wearing an
error message.

These tests pin the diagnostic, not the fix that prompted it: an empty sandbox must be named as the
cause, a populated one must NOT be blamed, and the diagnostics must never turn a clean failure into
an exception.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from layla.tools.impl import file_ops


@pytest.fixture
def empty_sandbox(tmp_path, monkeypatch):
    root = tmp_path / "empty-workspace"
    root.mkdir()
    monkeypatch.setattr(file_ops, "_get_sandbox", lambda: root)
    monkeypatch.setattr(file_ops, "inside_sandbox", lambda t: True)
    monkeypatch.setattr(file_ops._effective_sandbox, "path", str(root), raising=False)
    return root


@pytest.fixture
def populated_sandbox(tmp_path, monkeypatch):
    root = tmp_path / "real-workspace"
    root.mkdir()
    (root / "main.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_get_sandbox", lambda: root)
    monkeypatch.setattr(file_ops, "inside_sandbox", lambda t: True)
    monkeypatch.setattr(file_ops._effective_sandbox, "path", str(root), raising=False)
    return root


def test_empty_sandbox_is_named_as_the_cause(empty_sandbox):
    r = file_ops.read_file("README.md")
    assert r["ok"] is False
    assert r.get("sandbox_is_empty") is True
    assert "EMPTY" in r["error"], "the operator must be told the sandbox itself is the problem"
    assert str(empty_sandbox) in r["error"], "the error must name the directory that was searched"
    assert r.get("remedy"), "an unactionable error is a silent failure with extra steps"
    assert "sandbox_root" in r["remedy"], "the remedy must name the setting to change"


def test_the_error_says_where_it_looked(empty_sandbox):
    r = file_ops.read_file("src/app.py")
    assert r["looked_for"].endswith("app.py")
    assert str(empty_sandbox) in r["looked_for"], (
        "'File not found' without the resolved path cannot be debugged by the person reading it"
    )


def test_a_populated_sandbox_is_not_blamed(populated_sandbox):
    """The diagnostic must not cry wolf: a real workspace with a genuine typo is a plain not-found."""
    r = file_ops.read_file("no_such_file.py")
    assert r["ok"] is False
    assert not r.get("sandbox_is_empty"), "the sandbox has files in it; it is not the cause here"
    assert "EMPTY" not in r["error"]
    assert r.get("remedy") is None, "no remedy should be offered when the sandbox is fine"
    assert r["looked_for"].endswith("no_such_file.py"), "but it should still say where it looked"


def test_a_real_file_still_reads(populated_sandbox):
    """Guard against the diagnostic accidentally intercepting the success path."""
    r = file_ops.read_file("main.py")
    assert r["ok"] is True
    assert "print" in r["content"]


def test_list_dir_reports_an_empty_sandbox_too(empty_sandbox):
    """read_file was not the only 0% tool — the helper is shared by every not-found site."""
    r = file_ops.list_dir("some/missing/dir")
    assert r["ok"] is False
    assert r.get("sandbox_is_empty") is True
    assert str(empty_sandbox) in r["error"]


def test_diagnostics_never_raise(monkeypatch, tmp_path):
    """Sandbox introspection touches the disk; it must degrade to a plain error, never an exception."""
    def _boom():
        raise OSError("disk gone")

    monkeypatch.setattr(file_ops, "_get_sandbox", _boom)
    monkeypatch.setattr(file_ops, "inside_sandbox", lambda t: True)
    monkeypatch.setattr(file_ops._effective_sandbox, "path", str(tmp_path), raising=False)

    r = file_ops.read_file("anything.txt")
    assert r["ok"] is False
    assert r["error"] == "File not found", "must fall back to the plain error, not propagate"
    assert "sandbox_root" not in r

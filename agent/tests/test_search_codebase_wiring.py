"""BL-302: search_codebase must not report a symbol absent when it is present.

THE BUG. `search_codebase` was wired to services.workspace.code_intelligence.search_symbols — the
tree-sitter backend. tree-sitter is commented out of requirements.txt:127 and installed in neither venv,
so the backend matched nothing and the tool returned:

    {"ok": True, "matches": []}          for select_aspect, which exists twice

Measured on this tree before the fix:
    search_codebase('select_aspect') -> 0     code_intelligence, ok=True, error=None
    grep_code('select_aspect')       -> 50+
    repo_indexer.search_symbols(...)  -> 2

`ok: True` plus an empty list is not a missing feature, it is a POSITIVE CLAIM OF ABSENCE. Layla
concluded the symbol did not exist and went on to reason about the operator's real code from a false
negative. An exception would have been strictly better — it would have been visible.

WHY THESE TESTS AND NOT A GREP. A source-grep for "repo_indexer" in code.py would pass forever while the
function returned nothing: the import is not the behaviour. These call search_codebase() and assert on
the MATCHES, so they fail if the wiring is reverted, if the adapter's key mapping drifts, or if the
backend stops finding things for any other reason. Verified by reverting the wiring: both
test_finds_a_symbol_that_exists and test_zero_matches_is_never_reported_from_an_empty_index fail.

WHY NOT test_code_intelligence.py. That file opens with `pytest.importorskip("tree_sitter")`, so it has
never executed a single line on this machine — it could not have caught this and never will.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


_FIXTURE = '''
class WidgetFactory:
    """A class the index must find."""

    def assemble_widget(self, spec):
        return spec


def uniquely_named_helper(alpha, beta=2):
    return alpha + beta
'''


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A real temp workspace + a temp index. Never touches agent/.layla/repo_index.db (operator state)."""
    from layla.tools import sandbox_core
    from services.workspace import repo_indexer

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "widgets.py").write_text(_FIXTURE, encoding="utf-8")

    # raising=True (the default) on the module attrs: if either is renamed these blow up loudly instead
    # of silently patching nothing and leaving the test to pass while exercising the real paths.
    monkeypatch.setattr(repo_indexer, "_DB_PATH", tmp_path / "repo_index.db")
    monkeypatch.setattr(repo_indexer, "_MIGRATED", False)

    # `_effective_sandbox` is a thread-local and `.path` genuinely does not exist until something sets
    # it (_get_sandbox reads it with getattr(..., None)), so raising=False is correct here rather than
    # sloppy. But an unverified raising=False is exactly how a test ends up exercising nothing, so the
    # patch is not trusted — the assert below proves it actually took effect.
    monkeypatch.setattr(sandbox_core._effective_sandbox, "path", str(ws), raising=False)
    assert sandbox_core._get_sandbox() == ws.resolve(), (
        "the sandbox override did not take — this fixture would be testing the REAL sandbox, not the "
        "temp workspace, and every assertion below would be meaningless"
    )
    return ws


def test_finds_a_symbol_that_exists(workspace):
    """The whole bug in one assertion: a symbol that is right there must not come back as 0 matches."""
    from layla.tools.impl.code import search_codebase

    res = search_codebase("uniquely_named_helper")

    assert res["ok"] is True, res
    assert res["count"] > 0, (
        "search_codebase reported ZERO matches for a function that is plainly in the workspace. "
        "This is BL-302 again: the tool is answering out of a backend that cannot see the code, and "
        "'ok: True, matches: []' tells Layla the symbol does not exist."
    )
    names = [m["name"] for m in res["matches"]]
    assert "uniquely_named_helper" in names, names


def test_finds_classes_and_methods_too(workspace):
    from layla.tools.impl.code import search_codebase

    assert search_codebase("WidgetFactory")["count"] > 0
    assert search_codebase("assemble_widget")["count"] > 0


def test_matches_carry_file_and_line(workspace):
    """The adapter remaps repo_indexer's rows (file_path/kind/name/line). If those keys drift, callers
    get Nones and the tool becomes useless without failing."""
    from layla.tools.impl.code import search_codebase

    m = next(m for m in search_codebase("uniquely_named_helper")["matches"]
             if m["name"] == "uniquely_named_helper")
    assert m["file"].endswith("widgets.py"), m
    assert isinstance(m["line"], int) and m["line"] > 0, m
    assert m["kind"] == "function", m


def test_genuinely_absent_symbol_reports_no_matches(workspace):
    """The other half of honesty: once the index IS populated, absent must mean absent.

    Without this, 'always return matches' would satisfy the test above.
    """
    from layla.tools.impl.code import search_codebase

    search_codebase("uniquely_named_helper")  # force the index to build
    res = search_codebase("zzz_no_such_symbol_anywhere")
    assert res["ok"] is True
    assert res["count"] == 0


def test_zero_matches_is_never_reported_from_an_empty_index(workspace, monkeypatch):
    """A cold index answers every query with zero rows — indistinguishable from 'absent'.

    That is the same false negative wearing a different hat, so an empty index must NOT produce a
    confident `ok: True, matches: []`. Here the on-demand build is forced to fail, leaving the index
    empty; the tool must refuse to claim absence.
    """
    from layla.tools.impl import code as code_impl
    from services.workspace import repo_indexer

    def _boom(*a, **kw):
        raise RuntimeError("indexing unavailable")

    monkeypatch.setattr(repo_indexer, "index_workspace_repo", _boom)

    res = code_impl.search_codebase("uniquely_named_helper")
    assert res["ok"] is False, (
        "an EMPTY index must never yield 'ok: True, matches: []' — that is a claim of absence made "
        f"from no evidence at all. Got: {res}"
    )
    assert "index" in (res.get("error") or "").lower()

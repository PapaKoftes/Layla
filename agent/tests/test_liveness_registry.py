"""CP-3: the runtime liveness registry — catches "correct component, nobody drives it".

The registry's whole value is that it never lies and never harms: an effect that fires shows up, an
effect that does not fire shows up at 0, and a broken counter can never break the turn it observes.
These tests pin exactly those three properties.
"""
from __future__ import annotations

import importlib

import pytest

from services.observability import liveness


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the memory DB at a throwaway file so counts do not touch the operator's real DB."""
    import layla.memory.db_connection as dbc

    db_file = tmp_path / "liveness_test.db"
    monkeypatch.setattr(dbc, "DB_PATH", db_file, raising=False)
    # _conn() reads module state; force a fresh connection factory that uses the temp path.
    import sqlite3

    def _fresh_conn():
        con = sqlite3.connect(db_file)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(dbc, "_conn", _fresh_conn)
    return db_file


class TestFireAndSnapshot:
    def test_a_fired_effect_is_counted(self, temp_db):
        liveness.fire("tool_executed")
        liveness.fire("tool_executed")
        snap = liveness.snapshot()
        assert snap["tool_executed"]["count"] == 2
        assert snap["tool_executed"]["last_fired_at"] is not None

    def test_every_known_effect_appears_even_at_zero(self, temp_db):
        """An effect that never fires must be VISIBLE at 0 — that is the entire point."""
        snap = liveness.snapshot()
        for effect in liveness.KNOWN_EFFECTS:
            assert effect in snap, f"{effect} vanished from the snapshot"
            assert snap[effect]["count"] == 0
        assert snap["tool_executed"]["count"] == 0

    def test_counts_are_monotonic(self, temp_db):
        for _ in range(5):
            liveness.fire("turn_committed")
        assert liveness.snapshot()["turn_committed"]["count"] == 5


class TestNeverBreaksATurn:
    def test_fire_never_raises_even_when_the_db_is_broken(self, monkeypatch):
        """A liveness counter is never load-bearing for a reply. If the DB is gone, fire() is a no-op."""
        import layla.memory.db_connection as dbc

        monkeypatch.setattr(dbc, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
        # Must not raise:
        liveness.fire("tool_executed")

    def test_snapshot_never_raises_when_broken(self, monkeypatch):
        import layla.memory.db_connection as dbc

        monkeypatch.setattr(dbc, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
        snap = liveness.snapshot()
        # Degrades to all-known-at-zero rather than exploding.
        assert set(snap) >= set(liveness.KNOWN_EFFECTS)


def test_the_four_effects_are_actually_instrumented():
    """A registry nobody calls is the very defect this checkpoint exists to detect. Assert, by AST,
    that each named effect has a real fire() site in product code — not just an entry in the dict."""
    import ast
    from pathlib import Path

    agent_dir = Path(__file__).resolve().parent.parent
    fired: set[str] = set()
    for py in agent_dir.rglob("*.py"):
        s = str(py)
        if "venv" in s or "site-packages" in s or "test" in py.name.lower() or "liveness.py" in py.name:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace").lstrip("﻿"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and (getattr(n.func, "attr", None) == "fire")
                    and n.args and isinstance(n.args[0], ast.Constant)):
                fired.add(n.args[0].value)

    missing = set(liveness.KNOWN_EFFECTS) - fired
    assert not missing, (
        f"these registered effects have NO fire() call site in product code: {sorted(missing)} — "
        "a named effect that nothing fires is a dashboard line that can never light up"
    )

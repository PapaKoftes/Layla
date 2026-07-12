"""Regression tests for the shared `isolated_db` conftest fixture.

The shared fixture patches the DB path to a fresh tmp file and calls migrate().
migrate() runs at most once per process (guarded by _MIGRATED). If any prior
DB-touching test flipped that guard True, migrate() short-circuits and the
freshly-patched tmp DB would be left with ZERO tables. The fixture must reset
the guard first so the isolated DB is genuinely migrated.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def _pretend_prior_test_migrated():
    """Simulate a prior DB-touching test having flipped the process-level guard.

    Requested BEFORE `isolated_db` in the test signature so it is set up first.
    """
    import layla.memory.db as db_mod
    import layla.memory.migrations as mig

    if hasattr(db_mod, "_MIGRATED"):
        db_mod._MIGRATED = True  # type: ignore[attr-defined]
    mig._MIGRATED = True
    yield


def test_shared_isolated_db_has_tables_even_after_prior_migration(
    _pretend_prior_test_migrated, isolated_db
):
    from layla.memory.db_connection import _conn

    with _conn() as db:
        tables = {
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    # Before the fix, migrate() short-circuited on the True guard and these
    # tables were never created in the tmp DB.
    assert "timeline_events" in tables
    assert "operator_journal" in tables


def test_shared_isolated_db_usable_for_real_writes(
    _pretend_prior_test_migrated, isolated_db
):
    """End-to-end: a real memory helper must work against the isolated DB."""
    from layla.memory import user_profile

    # Would raise sqlite3.OperationalError 'no such table' if the DB were empty.
    user_profile.add_timeline_event("regression-check")

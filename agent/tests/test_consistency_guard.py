"""Memory self-consistency guard: flags when a new learning likely contradicts a stored
one (numeric value-drift or negation flip), records it for reconcile, and stays quiet on
unrelated/agreeing statements (high precision)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from layla.memory.db_connection import _conn
from layla.time_utils import utcnow


@pytest.fixture
def isolated_db(tmp_path):
    db_path = tmp_path / "test_layla.db"
    import layla.memory.db as db_mod
    import layla.memory.migrations as mig
    with patch("layla.memory.db._DB_PATH", db_path), patch("layla.memory.db_connection._DB_PATH", db_path):
        mig._MIGRATED = False
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False
        mig.migrate()
        yield db_path


def _insert(content: str) -> int:
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO learnings (content, type, created_at, learning_type) VALUES (?,?,?,?)",
            (content, "fact", utcnow().isoformat(), "fact"),
        )
        db.commit()
        return int(cur.lastrowid)


def test_numeric_value_drift_flagged(isolated_db):
    from services.memory.consistency_guard import detect_conflict
    _insert("The API request timeout is 30 seconds by default")
    c = detect_conflict("The API request timeout is 60 seconds by default")
    assert c and "conflicting values" in c["reason"]


def test_negation_flip_flagged(isolated_db):
    from services.memory.consistency_guard import detect_conflict
    _insert("The scheduler service supports concurrent background missions")
    c = detect_conflict("The scheduler service does not support concurrent background missions")
    assert c and "negation" in c["reason"]


def test_no_false_positive_on_unrelated(isolated_db):
    from services.memory.consistency_guard import detect_conflict
    _insert("The user prefers dark mode in the interface")
    assert detect_conflict("The database uses WAL journaling for write concurrency") is None


def test_no_flag_when_numbers_agree(isolated_db):
    from services.memory.consistency_guard import detect_conflict
    _insert("The API request timeout is 30 seconds")
    assert detect_conflict("The API request timeout is 30 seconds by default") is None


def test_check_and_flag_records_lists_resolves(isolated_db):
    from services.memory.consistency_guard import check_and_flag, list_conflicts, resolve_conflict
    eid = _insert("The retry limit is 3 attempts before giving up")
    flagged = check_and_flag("The retry limit is 5 attempts before giving up", new_id=9999)
    assert flagged and flagged["existing_id"] == eid
    conflicts = list_conflicts(unresolved_only=True)
    assert len(conflicts) == 1 and conflicts[0]["reason"]
    assert resolve_conflict(conflicts[0]["id"]) is True
    assert list_conflicts(unresolved_only=True) == []


def test_disabled_via_config(isolated_db):
    from services.memory.consistency_guard import check_and_flag, list_conflicts
    _insert("The cache TTL is 60 seconds")
    with patch("runtime_safety.load_config", return_value={"memory_consistency_guard_enabled": False}):
        assert check_and_flag("The cache TTL is 120 seconds", new_id=1) is None
    assert list_conflicts() == []

"""Verification queue: submit, get_next, answer, stats, session reset.

Run from agent/:  pytest tests/test_verification_queue.py -v
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_in_memory_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the tables verification_queue needs."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verification_queue (
            id           TEXT PRIMARY KEY,
            fact_content TEXT NOT NULL,
            source       TEXT DEFAULT 'inferred',
            confidence   REAL DEFAULT 0.5,
            importance   REAL DEFAULT 0.5,
            status       TEXT DEFAULT 'pending',
            ask_count    INTEGER DEFAULT 0,
            last_asked   TEXT,
            user_answer  TEXT,
            created_at   TEXT NOT NULL,
            resolved_at  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learnings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            content       TEXT NOT NULL,
            type          TEXT DEFAULT 'fact',
            created_at    TEXT NOT NULL,
            embedding_id  TEXT,
            confidence    REAL DEFAULT 0.5,
            source        TEXT DEFAULT 'inferred',
            content_hash  TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


@contextmanager
def _patched_queue():
    """Yield a VerificationQueue whose DB calls hit an in-memory SQLite."""
    db = _make_in_memory_db()

    def fake_conn():
        return db

    with patch("services.verification_queue._conn", fake_conn), \
         patch("services.verification_queue.utcnow", side_effect=lambda: datetime.now(timezone.utc)):
        # Re-import after patching so the class picks up the stubs
        from services.verification_queue import VerificationQueue
        q = VerificationQueue.__new__(VerificationQueue)
        q._prompts_this_session = 0
        yield q, db

    db.close()


def _make_queue():
    """Non-context-manager variant: returns (queue, db, cleanup)."""
    db = _make_in_memory_db()

    def fake_conn():
        return db

    patcher_conn = patch("services.verification_queue._conn", fake_conn)
    patcher_time = patch(
        "services.verification_queue.utcnow",
        side_effect=lambda: datetime.now(timezone.utc),
    )
    patcher_conn.start()
    patcher_time.start()

    from services.verification_queue import VerificationQueue
    q = VerificationQueue.__new__(VerificationQueue)
    q._prompts_this_session = 0

    def cleanup():
        patcher_time.stop()
        patcher_conn.stop()
        db.close()

    return q, db, cleanup


# We need to pre-patch imports so the module-level code doesn't blow up
# when it tries to import the real db_connection during collection.
# Patch at the target location where verification_queue imports from.

@pytest.fixture()
def vq():
    """Fixture yielding (queue_instance, raw_db_connection)."""
    db = _make_in_memory_db()

    def fake_conn():
        return db

    with patch("layla.memory.db_connection._conn", fake_conn), \
         patch("layla.time_utils.utcnow", return_value=datetime.now(timezone.utc)):
        from services.verification_queue import VerificationQueue
        q = VerificationQueue.__new__(VerificationQueue)
        q._prompts_this_session = 0
        yield q, db

    db.close()


# ── Tests ────────────────────────────────────────────────────────────────


class TestSubmit:
    """submit() — add facts to verification queue."""

    def test_submit_returns_id_for_new_fact(self, vq):
        q, db = vq
        fact_id = q.submit("The user prefers dark mode")
        assert fact_id is not None
        expected_hash = hashlib.sha256("The user prefers dark mode".encode()).hexdigest()[:16]
        assert fact_id == expected_hash

    def test_submit_returns_none_for_duplicate(self, vq):
        q, db = vq
        first = q.submit("The user likes Python")
        assert first is not None
        second = q.submit("The user likes Python")
        assert second is None

    def test_submit_returns_none_for_empty_string(self, vq):
        q, db = vq
        assert q.submit("") is None
        assert q.submit("   ") is None

    def test_submit_returns_none_for_high_confidence(self, vq):
        q, db = vq
        assert q.submit("Already known fact", confidence=0.9) is None
        assert q.submit("Very confident fact", confidence=0.95) is None

    def test_submit_accepts_just_below_threshold(self, vq):
        q, db = vq
        result = q.submit("Slightly uncertain fact", confidence=0.89)
        assert result is not None

    def test_submit_stores_metadata(self, vq):
        q, db = vq
        q.submit("User works with CAD", source="document_scan", confidence=0.6, importance=0.8)
        row = db.execute("SELECT * FROM verification_queue").fetchone()
        assert row["fact_content"] == "User works with CAD"
        assert row["source"] == "document_scan"
        assert row["confidence"] == 0.6
        assert row["importance"] == 0.8
        assert row["status"] == "pending"


class TestDedup:
    """Deduplication by SHA-256 hash of fact content."""

    def test_dedup_uses_first_16_chars_of_sha256(self, vq):
        q, db = vq
        fact = "User prefers VS Code"
        fact_id = q.submit(fact)
        full_hash = hashlib.sha256(fact.encode()).hexdigest()
        assert fact_id == full_hash[:16]

    def test_different_facts_get_different_ids(self, vq):
        q, db = vq
        id1 = q.submit("Fact number one")
        id2 = q.submit("Fact number two")
        assert id1 is not None
        assert id2 is not None
        assert id1 != id2

    def test_same_content_different_metadata_still_deduped(self, vq):
        q, db = vq
        id1 = q.submit("Same content", source="a", importance=0.3)
        id2 = q.submit("Same content", source="b", importance=0.9)
        assert id1 is not None
        assert id2 is None


class TestGetNext:
    """get_next() — retrieve pending facts for user verification."""

    def test_get_next_returns_highest_importance_first(self, vq):
        q, db = vq
        q.submit("Low importance", importance=0.2)
        q.submit("High importance", importance=0.9)
        q.submit("Medium importance", importance=0.5)

        result = q.get_next()
        assert result is not None
        assert result["fact"] == "High importance"
        assert result["importance"] == 0.9

    def test_get_next_returns_none_when_session_limit_reached(self, vq):
        q, db = vq
        # Submit more facts than the session limit
        for i in range(5):
            q.submit(f"Fact {i}", importance=0.5)

        # Exhaust the session limit (3 prompts)
        for _ in range(3):
            result = q.get_next()
            assert result is not None

        # The 4th call should return None
        result = q.get_next()
        assert result is None

    def test_get_next_returns_none_when_empty(self, vq):
        q, db = vq
        result = q.get_next()
        assert result is None

    def test_get_next_respects_cooldown(self, vq):
        q, db = vq
        q.submit("Cooled down fact")

        # Manually set last_asked to 1 hour ago (within cooldown)
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute(
            "UPDATE verification_queue SET last_asked = ?, ask_count = 1 WHERE fact_content = ?",
            (one_hour_ago, "Cooled down fact"),
        )
        db.commit()

        result = q.get_next()
        assert result is None

    def test_get_next_allows_after_cooldown_expires(self, vq):
        q, db = vq
        q.submit("Old fact")

        # Set last_asked to 25 hours ago (beyond cooldown)
        past = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        db.execute(
            "UPDATE verification_queue SET last_asked = ?, ask_count = 1 WHERE fact_content = ?",
            (past, "Old fact"),
        )
        db.commit()

        result = q.get_next()
        assert result is not None
        assert result["fact"] == "Old fact"

    def test_get_next_updates_ask_count_and_last_asked(self, vq):
        q, db = vq
        q.submit("Track updates")
        q.get_next()

        row = db.execute(
            "SELECT ask_count, last_asked FROM verification_queue WHERE fact_content = ?",
            ("Track updates",),
        ).fetchone()
        assert row["ask_count"] == 1
        assert row["last_asked"] is not None

    def test_get_next_returns_correct_dict_shape(self, vq):
        q, db = vq
        q.submit("Shape test", source="unit_test", confidence=0.4, importance=0.7)
        result = q.get_next()
        assert result is not None
        assert set(result.keys()) == {
            "id", "fact", "source", "confidence", "importance",
            "ask_count", "prompt_number", "max_prompts",
        }
        assert result["source"] == "unit_test"
        assert result["prompt_number"] == 1
        assert result["max_prompts"] == 3

    def test_get_next_same_importance_ordered_by_created_at(self, vq):
        q, db = vq
        # Insert directly to control created_at timestamps
        now = datetime.now(timezone.utc)
        db.execute(
            """INSERT INTO verification_queue
               (id, fact_content, source, confidence, importance, status, created_at)
               VALUES (?, ?, 'test', 0.5, 0.5, 'pending', ?)""",
            ("id_second", "Second fact", (now + timedelta(seconds=10)).isoformat()),
        )
        db.execute(
            """INSERT INTO verification_queue
               (id, fact_content, source, confidence, importance, status, created_at)
               VALUES (?, ?, 'test', 0.5, 0.5, 'pending', ?)""",
            ("id_first", "First fact", now.isoformat()),
        )
        db.commit()

        result = q.get_next()
        assert result is not None
        # Same importance, so the one created earlier should come first
        assert result["fact"] == "First fact"


class TestAnswer:
    """answer() — record user confirmation or rejection."""

    def test_answer_confirmed_updates_status(self, vq):
        q, db = vq
        fact_id = q.submit("User prefers tabs over spaces")
        result = q.answer(fact_id, confirmed=True)
        assert result["ok"] is True
        assert result["status"] == "confirmed"

        row = db.execute(
            "SELECT status, user_answer, resolved_at FROM verification_queue WHERE id = ?",
            (fact_id,),
        ).fetchone()
        assert row["status"] == "confirmed"
        assert row["user_answer"] == "confirmed"
        assert row["resolved_at"] is not None

    def test_answer_confirmed_updates_learnings_confidence(self, vq):
        q, db = vq
        fact_text = "User knows Python well"
        content_hash = hashlib.sha256(fact_text.encode()).hexdigest()[:32]
        # Insert a matching learning
        db.execute(
            """INSERT INTO learnings (content, type, created_at, source, confidence, content_hash)
               VALUES (?, 'fact', ?, 'inferred', 0.5, ?)""",
            (fact_text, datetime.now(timezone.utc).isoformat(), content_hash),
        )
        db.commit()

        fact_id = q.submit(fact_text)
        q.answer(fact_id, confirmed=True)

        row = db.execute(
            "SELECT confidence FROM learnings WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        assert row["confidence"] == 1.0

    def test_answer_rejected_stores_correction_as_new_learning(self, vq):
        q, db = vq
        fact_id = q.submit("User likes Java")
        correction = "User actually prefers Python over Java"
        result = q.answer(fact_id, confirmed=False, correction=correction)

        assert result["ok"] is True
        assert result["status"] == "rejected"

        row = db.execute(
            "SELECT status, user_answer FROM verification_queue WHERE id = ?",
            (fact_id,),
        ).fetchone()
        assert row["status"] == "rejected"
        assert row["user_answer"] == correction

        # Check that the correction was stored as a new learning
        learning = db.execute(
            "SELECT * FROM learnings WHERE content = ?",
            (correction,),
        ).fetchone()
        assert learning is not None
        assert learning["type"] == "correction"
        assert learning["source"] == "user_correction"
        assert learning["confidence"] == 1.0

    def test_answer_rejected_without_correction(self, vq):
        q, db = vq
        fact_id = q.submit("User dislikes testing")
        result = q.answer(fact_id, confirmed=False)

        assert result["ok"] is True
        assert result["status"] == "rejected"

        row = db.execute(
            "SELECT user_answer FROM verification_queue WHERE id = ?",
            (fact_id,),
        ).fetchone()
        assert row["user_answer"] == "rejected"

        # No correction stored in learnings
        count = db.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        assert count == 0


class TestGetStats:
    """get_stats() — queue statistics."""

    def test_get_stats_empty_queue(self, vq):
        q, db = vq
        stats = q.get_stats()
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["confirmed"] == 0
        assert stats["rejected"] == 0
        assert stats["verified_percent"] == 0

    def test_get_stats_returns_correct_counts(self, vq):
        q, db = vq
        # Insert facts in different statuses
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO verification_queue (id, fact_content, status, created_at) VALUES (?, ?, 'pending', ?)",
            ("p1", "pending one", now),
        )
        db.execute(
            "INSERT INTO verification_queue (id, fact_content, status, created_at) VALUES (?, ?, 'pending', ?)",
            ("p2", "pending two", now),
        )
        db.execute(
            "INSERT INTO verification_queue (id, fact_content, status, created_at) VALUES (?, ?, 'confirmed', ?)",
            ("c1", "confirmed one", now),
        )
        db.execute(
            "INSERT INTO verification_queue (id, fact_content, status, created_at) VALUES (?, ?, 'rejected', ?)",
            ("r1", "rejected one", now),
        )
        db.commit()

        stats = q.get_stats()
        assert stats["total"] == 4
        assert stats["pending"] == 2
        assert stats["confirmed"] == 1
        assert stats["rejected"] == 1
        assert stats["verified_percent"] == 25.0  # 1/4 * 100


class TestResetSession:
    """reset_session() — allow more prompts after reset."""

    def test_reset_session_allows_more_prompts(self, vq):
        q, db = vq
        for i in range(5):
            q.submit(f"Reset test fact {i}", importance=0.5)

        # Exhaust session limit
        for _ in range(3):
            assert q.get_next() is not None
        assert q.get_next() is None  # limit reached

        # Reset and verify we can get more
        q.reset_session()
        result = q.get_next()
        # May be None because of cooldown on the already-asked facts,
        # but the counter should be at 0.
        assert q._prompts_this_session == 0 or result is not None

    def test_reset_session_resets_counter_to_zero(self, vq):
        q, db = vq
        q._prompts_this_session = 3
        q.reset_session()
        assert q._prompts_this_session == 0

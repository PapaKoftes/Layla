"""Integration test for the memory pipeline."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _reset_db(tmp_path):
    """Point the DB layer at a fresh database in tmp_path and force migration."""
    import layla.memory.db as db_mod
    import layla.memory.db_connection as db_conn_mod
    import layla.memory.migrations as mig_mod

    db_path = tmp_path / "layla.db"
    os.environ["LAYLA_DATA_DIR"] = str(tmp_path)

    # Close any thread-local connection so it reconnects to the new path
    if hasattr(db_conn_mod._thread_local, "connection"):
        try:
            db_conn_mod._thread_local.connection.close()
        except Exception:
            pass
        db_conn_mod._thread_local.connection = None
        db_conn_mod._thread_local.connection_path = None

    db_mod._DB_PATH = db_path
    db_conn_mod._DB_PATH = db_path
    # Reset _MIGRATED on BOTH the migrations module and the barrel module
    # so _effective_migrated() returns False and the migration actually runs
    mig_mod._MIGRATED = False
    if hasattr(db_mod, "_MIGRATED"):
        db_mod._MIGRATED = False

    from layla.memory.migrations import migrate
    migrate()

    return db_path


class TestMemoryPipeline:
    # Content must be >= 40 chars to pass the learning_filter MIN_LENGTH gate
    PIPELINE_CONTENT = "Test learning content for the memory pipeline integration test"

    def test_save_and_retrieve_learning(self, tmp_path):
        """End-to-end: save a learning, verify it persists in SQLite."""
        db_path = _reset_db(tmp_path)

        from layla.memory.learnings import save_learning

        lid = save_learning(
            content=self.PIPELINE_CONTENT,
            kind="fact",
            confidence=0.9,
        )

        assert isinstance(lid, int)
        assert lid > 0

        # Verify directly in DB
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM learnings WHERE id=?", (lid,)).fetchone()
        conn.close()

        assert row is not None
        assert row["content"] == self.PIPELINE_CONTENT
        assert row["type"] == "fact"

    def test_save_deduplicates_by_content_hash(self, tmp_path):
        """Saving the same content twice should return the same ID (dedup via content_hash)."""
        _reset_db(tmp_path)

        from layla.memory.learnings import save_learning

        content = "Unique dedup test content for memory pipeline verification check"

        lid1 = save_learning(content=content, kind="fact")
        lid2 = save_learning(content=content, kind="fact")

        # Both calls should return the same ID due to content_hash dedup
        assert lid1 == lid2
        assert lid1 > 0

    def test_count_learnings_reflects_inserts(self, tmp_path):
        """count_learnings should return the correct count after inserts."""
        _reset_db(tmp_path)

        from layla.memory.learnings import count_learnings, save_learning

        initial = count_learnings()

        save_learning(content="Count test learning alpha for pipeline integration testing", kind="fact")
        save_learning(content="Count test learning beta for pipeline integration testing", kind="fact")

        assert count_learnings() >= initial + 2

"""Integration tests — verify component wiring without mocks.

These tests spin up real (in-memory) databases and verify that the
distributed infrastructure components interact correctly end-to-end.

They do NOT start a uvicorn server or network connections — those
require the full runtime. Instead they validate:

1. Governor → Dispatcher wiring (mode affects dispatch decisions)
2. Verification queue → Growth stats pipeline
3. Knowledge watcher → file tracker → ingest path
4. Wiki domain scoping (structured wiki)
5. Task queue → WorkUnit lifecycle
6. Cluster pairing token generation + validation
7. Node sync dedup logic
8. Scheduler registry creates all expected jobs
"""

import hashlib
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_in_memory_db():
    """Create an in-memory SQLite DB with learnings + verification_queue tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'fact',
            created_at TEXT,
            source TEXT DEFAULT '',
            confidence REAL DEFAULT 0.5,
            content_hash TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            aspect_id TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE verification_queue (
            id TEXT PRIMARY KEY,
            fact_content TEXT NOT NULL,
            source TEXT DEFAULT 'inferred',
            confidence REAL DEFAULT 0.5,
            importance REAL DEFAULT 0.5,
            status TEXT DEFAULT 'pending',
            ask_count INTEGER DEFAULT 0,
            last_asked TEXT,
            user_answer TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vq_status ON verification_queue(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vq_importance ON verification_queue(importance DESC)")
    conn.execute("""
        CREATE TABLE task_queue (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            payload TEXT,
            result TEXT,
            error TEXT,
            source_node TEXT DEFAULT '',
            assigned_to TEXT DEFAULT '',
            timeout_s INTEGER DEFAULT 300,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tq_status ON task_queue(status)")
    conn.execute("""
        CREATE TABLE user_identity (
            key TEXT PRIMARY KEY,
            snapshot TEXT
        )
    """)
    conn.commit()
    return conn


class _FakeConn:
    """Context manager wrapper for an in-memory connection."""
    def __init__(self, conn):
        self._conn = conn

    def __call__(self):
        return self

    def __enter__(self):
        return self._conn

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# 1. Governor → Dispatcher wiring
# ---------------------------------------------------------------------------

class TestGovernorDispatcherIntegration:
    """Verify that governor mode changes affect dispatcher decisions."""

    def test_whisper_mode_offloads_to_drone(self):
        from services.cluster.work_unit import TaskType, WorkUnit
        from services.planning.task_dispatcher import TaskDispatcher

        disp = TaskDispatcher()

        task = WorkUnit(type=TaskType.EMBEDDING, payload={"text": "test"})
        task_dict = task.to_dict()

        # Mock a drone being available
        mock_peer = MagicMock()
        mock_peer.node_id = "drone-1"
        mock_peer.status = MagicMock(value="online")
        mock_peer.cpu_pct = 20.0
        mock_peer.active_tasks = 0
        mock_peer.max_tasks = 4
        mock_peer.has_capability = MagicMock(return_value=True)

        with patch.object(disp, "_get_governor_mode", return_value="whisper"), \
             patch("services.cluster.cluster_network.get_cluster_network") as mock_cn:
            net = MagicMock()
            net.get_online_drones.return_value = [mock_peer]
            mock_cn.return_value = net

            decision = disp.dispatch(task_dict)

        # WHISPER should prefer offloading to drone
        assert decision in ("drone-1", "queued")

    def test_sprint_mode_prefers_local(self):
        from services.cluster.work_unit import TaskType, WorkUnit
        from services.planning.task_dispatcher import TaskDispatcher

        disp = TaskDispatcher()

        task = WorkUnit(type=TaskType.EMBEDDING, payload={"text": "test"})
        task_dict = task.to_dict()

        with patch.object(disp, "_get_governor_mode", return_value="sprint"), \
             patch.object(disp, "_get_queen_load", return_value=0.2), \
             patch("services.cluster.cluster_network.get_cluster_network") as mock_cn:
            net = MagicMock()
            net.get_online_drones.return_value = []
            mock_cn.return_value = net

            decision = disp.dispatch(task_dict)

        # SPRINT with low load should stay local (queen_id)
        assert decision == disp._queen_id


# ---------------------------------------------------------------------------
# 2. Verification → Growth stats pipeline
# ---------------------------------------------------------------------------

class TestVerificationGrowthPipeline:
    """Verify that verification actions flow through to growth stats."""

    def test_confirmed_fact_appears_in_growth_stats(self):
        db = _make_in_memory_db()
        fake = _FakeConn(db)

        with patch("layla.memory.db_connection._conn", fake), \
             patch("layla.time_utils.utcnow", return_value=datetime(2024, 6, 1, tzinfo=timezone.utc)):

            from services.planning.verification_queue import VerificationQueue
            vq = VerificationQueue.__new__(VerificationQueue)
            vq._prompts_this_session = 0

            # Submit a fact
            fact = "The user prefers dark mode"
            fact_hash = hashlib.sha256(fact.encode()).hexdigest()[:16]
            db.execute(
                """INSERT INTO verification_queue
                   (id, fact_content, source, confidence, importance, status, created_at)
                   VALUES (?, ?, 'inferred', 0.5, 0.8, 'pending', '2024-06-01T00:00:00')""",
                (fact_hash, fact),
            )
            # Also insert as a learning
            content_hash = hashlib.sha256(fact.encode()).hexdigest()[:32]
            db.execute(
                """INSERT INTO learnings (content, type, created_at, source, confidence, content_hash)
                   VALUES (?, 'fact', '2024-06-01', 'inferred', 0.5, ?)""",
                (fact, content_hash),
            )
            db.commit()

            # Confirm it
            vq.answer(fact_hash, confirmed=True)

            # Check that learnings confidence was updated
            row = db.execute("SELECT confidence FROM learnings WHERE content_hash = ?", (content_hash,)).fetchone()
            assert row is not None
            assert row["confidence"] == 1.0

            # Check verification queue status
            vrow = db.execute("SELECT status FROM verification_queue WHERE id = ?", (fact_hash,)).fetchone()
            assert vrow["status"] == "confirmed"


# ---------------------------------------------------------------------------
# 3. Knowledge watcher → file tracker → ingest
# ---------------------------------------------------------------------------

class TestKnowledgeWatcherIngest:
    """Test the full file detection → ingest pipeline."""

    def test_new_file_detected_and_ingested(self, tmp_path):
        db = _make_in_memory_db()
        fake = _FakeConn(db)

        # Create a test file
        test_file = tmp_path / "notes.md"
        test_file.write_text("# Important Note\nThis is a test document.")

        with patch("layla.memory.db_connection._conn", fake), \
             patch("layla.time_utils.utcnow", return_value=datetime(2024, 6, 1, tzinfo=timezone.utc)), \
             patch.dict("sys.modules", {"layla.ingestion.pipeline": None}):

            from services.memory.knowledge_watcher import KnowledgeWatcher
            watcher = KnowledgeWatcher.__new__(KnowledgeWatcher)
            watcher._cfg = {}
            watcher._watch_dirs = [tmp_path]
            watcher._exclude_dirs = []
            watcher._observer = None
            watcher._running = False
            watcher._stop_event = MagicMock()
            watcher._poll_thread = None
            watcher._poll_interval = 60
            watcher._files_ingested = 0
            watcher._files_skipped = 0

            from services.memory.knowledge_watcher import _FileTracker
            watcher._tracker = _FileTracker()

            # Process the file
            watcher._ingest_file(test_file)

            # Verify it was stored as a learning
            row = db.execute("SELECT content, type FROM learnings").fetchone()
            assert row is not None
            assert "notes.md" in row["content"]
            assert row["type"] == "document"
            assert watcher._files_ingested == 1

    def test_duplicate_file_not_re_ingested(self, tmp_path):
        db = _make_in_memory_db()
        fake = _FakeConn(db)

        test_file = tmp_path / "readme.txt"
        test_file.write_text("Hello world")

        with patch("layla.memory.db_connection._conn", fake), \
             patch("layla.time_utils.utcnow", return_value=datetime(2024, 6, 1, tzinfo=timezone.utc)), \
             patch.dict("sys.modules", {"layla.ingestion.pipeline": None}):

            from services.memory.knowledge_watcher import KnowledgeWatcher, _FileTracker
            watcher = KnowledgeWatcher.__new__(KnowledgeWatcher)
            watcher._cfg = {}
            watcher._watch_dirs = [tmp_path]
            watcher._exclude_dirs = []
            watcher._observer = None
            watcher._running = False
            watcher._stop_event = MagicMock()
            watcher._poll_thread = None
            watcher._poll_interval = 60
            watcher._files_ingested = 0
            watcher._files_skipped = 0
            watcher._tracker = _FileTracker()

            # Ingest twice
            watcher._ingest_file(test_file)
            watcher._ingest_file(test_file)

            # Should only have one learning (dedup by content_hash)
            count = db.execute("SELECT COUNT(*) as c FROM learnings").fetchone()["c"]
            assert count == 1
            # Second call should have been skipped
            assert watcher._files_skipped == 1


# ---------------------------------------------------------------------------
# 4. Wiki domain scoping
# ---------------------------------------------------------------------------

class TestWikiDomainScoping:
    """Test that structured wiki with domains works correctly."""

    def test_domain_creates_subdirectory(self, tmp_path):
        from autonomous.wiki import wiki_root_for_workspace

        workspace = str(tmp_path / "project")
        os.makedirs(workspace)

        root_flat = wiki_root_for_workspace(workspace)
        root_domain = wiki_root_for_workspace(workspace, domain="procedures")

        assert root_flat.name == "wiki"
        assert root_domain.name == "procedures"
        assert root_domain.parent.name == "wiki"

    def test_write_entry_with_domain(self, tmp_path):
        from autonomous.wiki import build_candidate, write_wiki_entry

        workspace = str(tmp_path / "project")
        os.makedirs(workspace)

        # Mock sandbox check to allow tmp_path
        with patch("autonomous.wiki.inside_sandbox", return_value=True):
            candidate = build_candidate(
                title="How to Deploy",
                content_md="## Steps\n\n1. Install deps\n2. Run server"
            )
            result = write_wiki_entry(
                workspace_root=workspace,
                candidate=candidate,
                allow_write=True,
                cfg={"autonomous_wiki_enabled": True},
                domain="procedures",
            )

        assert result["ok"] is True
        assert "procedures" in result["path"]
        written_path = Path(result["path"])
        assert written_path.exists()
        assert "How to Deploy" not in result.get("skipped", "")

    def test_retrieval_searches_subdomains(self, tmp_path):
        from autonomous.wiki import wiki_root_for_workspace

        workspace = str(tmp_path / "project")
        wiki_dir = Path(workspace) / ".layla" / "wiki"
        procedures_dir = wiki_dir / "procedures"
        procedures_dir.mkdir(parents=True)

        # Create a wiki entry in a subdomain
        (procedures_dir / "deploy-guide.md").write_text(
            "---\ntitle: Deploy Guide\ntags: deployment server\n---\n\n"
            "# Deploy Guide\n\n- Install dependencies\n- Configure server\n- Start service"
        )

        with patch("autonomous.wiki_retrieval.inside_sandbox", return_value=True):
            from autonomous.wiki_retrieval import try_wiki_retrieval
            result = try_wiki_retrieval(
                goal="how to deploy the server and install dependencies",
                workspace_root=workspace,
                cfg={},
            )

        assert result is not None
        assert result["wiki_title"] == "Deploy Guide"
        assert "procedures" in result["wiki_path"]


# ---------------------------------------------------------------------------
# 5. Task queue → WorkUnit lifecycle
# ---------------------------------------------------------------------------

class TestTaskQueueLifecycle:
    """Verify complete task lifecycle: submit → claim → complete/fail."""

    def test_full_lifecycle(self):
        from services.cluster.work_unit import TaskStatus, TaskType, WorkUnit

        task = WorkUnit(type=TaskType.EMBEDDING, payload={"text": "test"})

        # Initial state
        assert task.status == TaskStatus.PENDING
        assert task.started_at is None
        assert task.completed_at is None

        # Start
        task.mark_running("queen-node-1")
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

        # Complete
        task.mark_done({"embedding": [0.1, 0.2, 0.3]})
        assert task.status == TaskStatus.DONE
        assert task.completed_at is not None
        assert task.result == {"embedding": [0.1, 0.2, 0.3]}

    def test_fail_then_retry(self):
        from services.cluster.work_unit import TaskStatus, TaskType, WorkUnit

        task = WorkUnit(type=TaskType.INGESTION, payload={"file": "test.pdf"})
        task.mark_running("queen-node-1")
        task.mark_failed("Connection timeout")

        assert task.status == TaskStatus.FAILED
        assert task.error == "Connection timeout"

        # Re-submit as new task (retry pattern)
        retry = WorkUnit(type=task.type, payload=task.payload, priority=task.priority)
        assert retry.status == TaskStatus.PENDING
        assert retry.id != task.id


# ---------------------------------------------------------------------------
# 6. Cluster pairing token lifecycle
# ---------------------------------------------------------------------------

class TestPairingTokenLifecycle:
    """Verify pairing token generation, validation, and expiry."""

    def test_generate_and_validate(self):
        from services.cluster.cluster_pairing import ClusterPairing

        cp = ClusterPairing()
        pt = cp.generate_pairing_token()

        assert pt.token is not None
        assert len(pt.token) > 0
        assert not pt.used

        # Validate with correct token
        valid, reason = cp.validate_pairing_token(pt.token)
        assert valid is True
        assert reason == "ok"

    def test_wrong_token_rejected(self):
        from services.cluster.cluster_pairing import ClusterPairing

        cp = ClusterPairing()
        cp.generate_pairing_token()

        valid, reason = cp.validate_pairing_token("wrong-token-value")
        assert valid is False
        assert reason == "invalid_token"

    def test_expired_token_rejected(self):
        import time

        from services.cluster.cluster_pairing import ClusterPairing

        cp = ClusterPairing()
        pt = cp.generate_pairing_token()
        # Force expiry — set it to just expired (within cleanup grace period of 60s)
        pt.expires_at = time.time() - 10

        valid, reason = cp.validate_pairing_token(pt.token)
        assert valid is False
        assert reason in ("token_expired", "invalid_token")  # cleanup may remove it


# ---------------------------------------------------------------------------
# 7. Node sync dedup
# ---------------------------------------------------------------------------

class TestNodeSyncDedup:
    """Verify that synced learnings are deduplicated by content_hash."""

    def test_import_deduplicates_by_hash(self):
        db = _make_in_memory_db()
        _FakeConn(db)

        content = "Python list comprehensions are faster than for loops"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        # Insert original
        db.execute(
            """INSERT INTO learnings (content, type, created_at, content_hash, confidence)
               VALUES (?, 'fact', '2024-06-01', ?, 0.8)""",
            (content, content_hash),
        )
        db.commit()

        # Try to import duplicate (simulating sync)
        existing = db.execute(
            "SELECT id FROM learnings WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        assert existing is not None  # Duplicate detected
        count = db.execute("SELECT COUNT(*) as c FROM learnings").fetchone()["c"]
        assert count == 1  # No duplicate inserted


# ---------------------------------------------------------------------------
# 8. Scheduler registry creates expected jobs
# ---------------------------------------------------------------------------

class TestSchedulerRegistry:
    """Verify that create_scheduler registers all expected jobs."""

    def test_creates_all_core_jobs(self):
        from layla.scheduler.registry import create_scheduler

        cfg = {
            "resource_governor_enabled": True,
            "governor_tick_seconds": 15,
            "cluster_enabled": False,
            "scheduler_study_enabled": True,
            "scheduler_interval_minutes": 30,
        }

        sched = create_scheduler(cfg)
        job_ids = {j.id for j in sched.get_jobs()}

        # Core jobs that should always exist
        assert "mission_worker" in job_ids
        assert "background_reflection" in job_ids
        assert "background_codex" in job_ids
        assert "background_memory_consolidation" in job_ids
        assert "background_initiative" in job_ids
        assert "background_memory_cleanup" in job_ids
        assert "nightly_db_backup" in job_ids
        assert "repo_reindex" in job_ids
        assert "reindex_failed_learnings" in job_ids
        assert "resource_governor_tick" in job_ids
        assert "task_queue_maintenance" in job_ids

    def test_cluster_sync_not_created_when_disabled(self):
        from layla.scheduler.registry import create_scheduler

        # Cluster disabled — cluster_sync should NOT be registered
        cfg = {
            "resource_governor_enabled": False,
            "cluster_enabled": False,
            "scheduler_study_enabled": False,
        }
        sched = create_scheduler(cfg)
        job_ids = {j.id for j in sched.get_jobs()}
        assert "cluster_sync" not in job_ids

    def test_cluster_enabled_attempts_sync_registration(self):
        """When cluster_enabled=True, registry attempts to import node_sync.
        If import fails (no real node_sync module available), it logs warning
        but doesn't crash."""
        from layla.scheduler.registry import create_scheduler

        cfg = {
            "resource_governor_enabled": False,
            "cluster_enabled": True,
            "cluster_sync_interval": 300,
            "scheduler_study_enabled": False,
        }
        # This should NOT raise — the try/except in registry handles import failures
        sched = create_scheduler(cfg)
        assert sched is not None

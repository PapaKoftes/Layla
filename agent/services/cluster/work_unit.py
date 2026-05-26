"""WorkUnit + TaskQueue — distributed task abstraction for Layla cluster.

A WorkUnit is the atomic unit of work that can be dispatched to any node
in the cluster (QUEEN or DRONE).  The TaskQueue is a durable, SQLite-backed
queue that survives restarts and allows claim-based processing.

Phase 2E of the distributed infrastructure plan.
"""
from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("layla")


# ── Enums ────────────────────────────────────────────────────────────────

class TaskType(enum.Enum):
    """Kind of work a node can perform."""
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    INGESTION = "ingestion"
    STUDY = "study"
    BACKUP = "backup"
    CONSOLIDATION = "consolidation"
    WIKI_BUILD = "wiki_build"


class TaskStatus(enum.Enum):
    """Lifecycle of a WorkUnit."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority:
    """Named priority levels (lower = higher priority)."""
    CRITICAL = 0   # Interactive chat — always run locally
    NORMAL = 1     # Standard background work
    LOW = 2        # Deferred/batch work (run in SPRINT only)


# ── WorkUnit dataclass ───────────────────────────────────────────────────

@dataclass
class WorkUnit:
    """A single distributable unit of work."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    type: TaskType = TaskType.INFERENCE
    priority: int = TaskPriority.NORMAL
    payload: dict = field(default_factory=dict)
    timeout_seconds: int = 300
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assigned_to: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    source_node: Optional[str] = None  # node that submitted this task

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API transport / DB storage."""
        d = asdict(self)
        d["type"] = self.type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkUnit:
        """Deserialize from API / DB."""
        d = dict(d)  # shallow copy
        if "type" in d and isinstance(d["type"], str):
            d["type"] = TaskType(d["type"])
        if "status" in d and isinstance(d["status"], str):
            d["status"] = TaskStatus(d["status"])
        # Parse JSON payload/result if stored as strings
        import json
        for key in ("payload", "result"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def mark_running(self, node_id: str) -> None:
        self.status = TaskStatus.RUNNING
        self.assigned_to = node_id
        self.started_at = datetime.now(timezone.utc).isoformat()

    def mark_done(self, result: dict | None = None) -> None:
        self.status = TaskStatus.DONE
        self.result = result
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_cancelled(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.now(timezone.utc).isoformat()


# ── TaskQueue (SQLite-backed) ────────────────────────────────────────────

class TaskQueue:
    """Durable task queue backed by the ``task_queue`` SQLite table.

    Design notes
    ------------
    * Uses the existing ``layla.memory.db_connection._conn()`` context manager
      so it shares the same DB file and WAL mode.
    * All methods are synchronous (the scheduler and governor tick on threads).
    * Claim-based: a node *claims* a pending task (status → running) then
      completes or fails it.  This avoids double-processing.
    """

    def __init__(self):
        self._ensure_table()

    # ── DDL ───────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_table() -> None:
        """Idempotent table creation (also done in migrations.py)."""
        try:
            from layla.memory.db_connection import _conn
            with _conn() as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS task_queue (
                        id          TEXT PRIMARY KEY,
                        type        TEXT NOT NULL,
                        priority    INTEGER DEFAULT 1,
                        status      TEXT DEFAULT 'pending',
                        payload     TEXT DEFAULT '{}',
                        result      TEXT,
                        error       TEXT,
                        source_node TEXT,
                        assigned_to TEXT,
                        timeout_s   INTEGER DEFAULT 300,
                        created_at  TEXT NOT NULL,
                        started_at  TEXT,
                        completed_at TEXT
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority, created_at)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_task_queue_assigned ON task_queue(assigned_to)")
                db.commit()
        except Exception as e:
            logger.warning("task_queue table ensure failed: %s", e)

    # ── Core operations ───────────────────────────────────────────────

    def submit(self, unit: WorkUnit) -> str:
        """Insert a new work unit.  Returns the task ID."""
        import json
        from layla.memory.db_connection import _conn
        with _conn() as db:
            db.execute(
                """INSERT INTO task_queue
                   (id, type, priority, status, payload, source_node, assigned_to,
                    timeout_s, created_at, started_at, completed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    unit.id,
                    unit.type.value,
                    unit.priority,
                    unit.status.value,
                    json.dumps(unit.payload),
                    unit.source_node,
                    unit.assigned_to,
                    unit.timeout_seconds,
                    unit.created_at,
                    unit.started_at,
                    unit.completed_at,
                ),
            )
            db.commit()
        logger.debug("task_queue: submitted %s (%s, pri=%d)", unit.id, unit.type.value, unit.priority)
        return unit.id

    def claim(self, node_id: str, task_types: list[TaskType] | None = None) -> WorkUnit | None:
        """Claim the highest-priority pending task for this node.

        Uses ``UPDATE … WHERE status='pending'`` in a single atomic step
        to prevent races between nodes.
        """
        import json
        from layla.memory.db_connection import _conn

        type_filter = ""
        params: list[Any] = [node_id, datetime.now(timezone.utc).isoformat()]
        if task_types:
            placeholders = ",".join("?" for _ in task_types)
            type_filter = f"AND type IN ({placeholders})"
            params.extend(t.value for t in task_types)

        with _conn() as db:
            # Find the best candidate
            row = db.execute(
                f"""SELECT id FROM task_queue
                    WHERE status = 'pending' {type_filter}
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1""",
                params[2:] if task_types else [],
            ).fetchone()
            if not row:
                return None

            task_id = row["id"] if isinstance(row, dict) else row[0]

            # Atomically claim
            now = datetime.now(timezone.utc).isoformat()
            affected = db.execute(
                """UPDATE task_queue
                   SET status = 'running', assigned_to = ?, started_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (node_id, now, task_id),
            ).rowcount
            db.commit()

            if affected == 0:
                return None  # Another node beat us

            return self.get(task_id)

    def complete(self, task_id: str, result: dict | None = None) -> None:
        """Mark a task as done with optional result."""
        import json
        from layla.memory.db_connection import _conn
        with _conn() as db:
            db.execute(
                """UPDATE task_queue
                   SET status = 'done', result = ?, completed_at = ?
                   WHERE id = ?""",
                (
                    json.dumps(result) if result else None,
                    datetime.now(timezone.utc).isoformat(),
                    task_id,
                ),
            )
            db.commit()
        logger.debug("task_queue: completed %s", task_id)

    def fail(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            db.execute(
                """UPDATE task_queue
                   SET status = 'failed', error = ?, completed_at = ?
                   WHERE id = ?""",
                (error, datetime.now(timezone.utc).isoformat(), task_id),
            )
            db.commit()
        logger.warning("task_queue: failed %s — %s", task_id, error)

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending or running task.  Returns True if cancelled."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            affected = db.execute(
                """UPDATE task_queue
                   SET status = 'cancelled', completed_at = ?
                   WHERE id = ? AND status IN ('pending', 'running')""",
                (datetime.now(timezone.utc).isoformat(), task_id),
            ).rowcount
            db.commit()
        return affected > 0

    def get(self, task_id: str) -> WorkUnit | None:
        """Fetch a single task by ID."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            row = db.execute("SELECT * FROM task_queue WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return self._row_to_unit(row)

    def get_pending(self, limit: int = 50) -> list[WorkUnit]:
        """Get pending tasks ordered by priority."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                """SELECT * FROM task_queue
                   WHERE status = 'pending'
                   ORDER BY priority ASC, created_at ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row_to_unit(r) for r in rows]

    def get_running(self, node_id: str | None = None) -> list[WorkUnit]:
        """Get running tasks, optionally filtered by node."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            if node_id:
                rows = db.execute(
                    "SELECT * FROM task_queue WHERE status = 'running' AND assigned_to = ?",
                    (node_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM task_queue WHERE status = 'running'"
                ).fetchall()
        return [self._row_to_unit(r) for r in rows]

    def get_recent(self, limit: int = 20) -> list[WorkUnit]:
        """Get the most recent tasks regardless of status."""
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute(
                """SELECT * FROM task_queue
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row_to_unit(r) for r in rows]

    def cleanup_stale(self, max_age_hours: int = 72) -> int:
        """Remove completed/failed tasks older than max_age_hours."""
        from layla.memory.db_connection import _conn
        cutoff = datetime.now(timezone.utc).isoformat()
        with _conn() as db:
            affected = db.execute(
                """DELETE FROM task_queue
                   WHERE status IN ('done', 'failed', 'cancelled')
                   AND completed_at < datetime(?, '-' || ? || ' hours')""",
                (cutoff, max_age_hours),
            ).rowcount
            db.commit()
        if affected:
            logger.info("task_queue: cleaned up %d stale tasks", affected)
        return affected

    def reset_stuck(self, timeout_seconds: int = 600) -> int:
        """Reset tasks stuck in 'running' state beyond their timeout."""
        from layla.memory.db_connection import _conn
        now = datetime.now(timezone.utc).isoformat()
        with _conn() as db:
            affected = db.execute(
                """UPDATE task_queue
                   SET status = 'pending', assigned_to = NULL, started_at = NULL
                   WHERE status = 'running'
                   AND started_at IS NOT NULL
                   AND (julianday(?) - julianday(started_at)) * 86400 > timeout_s""",
                (now,),
            ).rowcount
            db.commit()
        if affected:
            logger.info("task_queue: reset %d stuck tasks", affected)
        return affected

    def stats(self) -> dict[str, int]:
        """Return count of tasks per status."""
        from layla.memory.db_connection import _conn
        result: dict[str, int] = {}
        with _conn() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) as cnt FROM task_queue GROUP BY status"
            ).fetchall()
        for row in rows:
            status = row["status"] if isinstance(row, dict) else row[0]
            count = row["cnt"] if isinstance(row, dict) else row[1]
            result[status] = count
        return result

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_unit(row) -> WorkUnit:
        """Convert a DB row to a WorkUnit."""
        import json

        def _get(key, default=None):
            if isinstance(row, dict):
                return row.get(key, default)
            # sqlite3.Row
            try:
                return row[key]
            except (IndexError, KeyError):
                return default

        payload = _get("payload", "{}")
        result = _get("result")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = None

        return WorkUnit(
            id=_get("id"),
            type=TaskType(_get("type", "inference")),
            priority=_get("priority", 1),
            payload=payload or {},
            timeout_seconds=_get("timeout_s", 300),
            created_at=_get("created_at", ""),
            assigned_to=_get("assigned_to"),
            status=TaskStatus(_get("status", "pending")),
            result=result,
            error=_get("error"),
            started_at=_get("started_at"),
            completed_at=_get("completed_at"),
            source_node=_get("source_node"),
        )


# ── Module-level convenience ─────────────────────────────────────────────

_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Get or create the singleton TaskQueue."""
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue

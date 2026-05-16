"""
Post-session and periodic memory maintenance: summaries, dedup hints, learning reinforcement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("layla")


def consolidate_session(conversation_id: str) -> dict[str, Any]:
    """Post-task: bounded distill tick + light thread bookkeeping (no new schema)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return {"ok": False, "reason": "no_conversation_id"}
    out: dict[str, Any] = {"ok": True, "actions": [], "messages_seen": 0}
    try:
        from layla.memory.db import get_conversation_messages

        msgs = get_conversation_messages(cid, limit=80)
        if not msgs:
            out["note"] = "no_messages"
            return out
        out["messages_seen"] = len(msgs)
        try:
            from layla.memory.distill import run_distill_after_outcome

            d = run_distill_after_outcome(n=min(12, max(4, len(msgs) // 3)), use_semantic=False)
            out["actions"].append(f"distill:{d}")
        except Exception as e:
            out["actions"].append(f"distill_skip:{e}")
        try:
            from shared_state import get_last_outcome_evaluation

            ev = get_last_outcome_evaluation(cid) or {}
            if isinstance(ev, dict) and ev.get("success") is False:
                try:
                    pruned = prune_low_confidence_learnings(
                        threshold=0.08,
                        batch=5,
                    )
                    out["actions"].append(f"failure_prune_low_confidence:{pruned}")
                except Exception as pe:
                    out["actions"].append(f"failure_prune_skip:{pe}")
        except Exception:
            pass
        if len(msgs) >= 12:
            out["actions"].append("thread_ready_for_summary")
        return out
    except Exception as e:
        logger.debug("consolidate_session: %s", e)
        return {"ok": False, "error": str(e)}


def consolidate_periodic() -> dict[str, Any]:
    """Periodic merge / decay hooks (non-destructive by default)."""
    out: dict[str, Any] = {"ok": True, "actions": []}
    try:
        from layla.memory.learnings import _apply_confidence_decay

        _ = _apply_confidence_decay  # module side effects: ensure import path valid
        out["actions"].append("learnings_decay_import_ok")
    except Exception as e:
        out["actions"].append(f"learnings_decay_skip:{e}")
    try:
        from layla.memory.distill import run_distill_after_outcome

        run_distill_after_outcome(n=30)
        out["actions"].append("distill_tick")
    except Exception as e:
        out["actions"].append(f"distill_skip:{e}")
    return out


def apply_retention_policies(cfg: dict | None = None) -> dict[str, Any]:
    """
    Best-effort retention for append-only memory tables.
    Defaults are conservative; operators can override via cfg keys.
    """
    out: dict[str, Any] = {"ok": True, "actions": []}
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        c = cfg or {}
        now = datetime.now(timezone.utc)

        def _cutoff(days: int) -> str:
            return (now - timedelta(days=int(days))).isoformat()

        # Age-based retention (created_at)
        policies = [
            # high-churn
            ("tool_outcomes", int(c.get("retention_tool_outcomes_days", 90)), None),
            ("conversation_messages", int(c.get("retention_conversation_messages_days", 90)), None),
            ("outcome_evaluations", int(c.get("retention_outcome_evaluations_days", 180)), None),
            # P1-3: expanded retention policy tables
            ("tool_calls", int(c.get("retention_tool_calls_days", 90)), None),
            ("telemetry_events", int(c.get("retention_telemetry_events_days", 90)), None),
            ("model_outcomes", int(c.get("retention_model_outcomes_days", 180)), None),
            ("route_telemetry", int(c.get("retention_route_telemetry_days", 90)), None),
            # low-churn
            ("conversation_summaries", int(c.get("retention_conversation_summaries_days", 365)), None),
            ("relationship_memory", int(c.get("retention_relationship_memory_days", 365)), None),
            ("timeline_events", int(c.get("retention_timeline_events_days", 365)), None),
            ("episode_events", int(c.get("retention_episode_events_days", 365)), None),
            ("goal_progress", int(c.get("retention_goal_progress_days", 365)), None),
            ("aspect_memories", int(c.get("retention_aspect_memories_days", 365)), None),
            ("session_prompts", int(c.get("retention_session_prompts_days", 180)), None),
        ]

        # Special-case age-based retention (non-created_at)
        special_policies = [
            ("audit", "timestamp", int(c.get("retention_audit_days", 365))),
        ]
        # Optional hard caps (keep newest N by created_at where available).
        hard_caps = [
            ("tool_outcomes", int(c.get("retention_tool_outcomes_max_rows", 50000))),
            ("conversation_messages", int(c.get("retention_conversation_messages_max_rows", 200000))),
            ("outcome_evaluations", int(c.get("retention_outcome_evaluations_max_rows", 5000))),
        ]

        with _conn() as db:
            cols_cache: dict[str, set[str]] = {}

            def _cols(table: str) -> set[str]:
                if table in cols_cache:
                    return cols_cache[table]
                try:
                    cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
                except Exception:
                    cols = set()
                cols_cache[table] = cols
                return cols

            for table, days, _ in policies:
                if "created_at" not in _cols(table):
                    continue
                cutoff = _cutoff(days)
                try:
                    cur = db.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
                    n = int(cur.rowcount or 0) if cur else 0
                    if n:
                        out["actions"].append(f"retention:{table}:deleted_older_than_{days}d:{n}")
                except Exception as e:
                    out["actions"].append(f"retention:{table}:skip:{e}")

            for table, col, days in special_policies:
                if col not in _cols(table):
                    continue
                cutoff = _cutoff(days)
                try:
                    cur = db.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
                    n = int(cur.rowcount or 0) if cur else 0
                    if n:
                        out["actions"].append(f"retention:{table}:deleted_older_than_{days}d:{n}")
                except Exception as e:
                    out["actions"].append(f"retention:{table}:skip:{e}")

            for table, max_rows in hard_caps:
                if max_rows <= 0:
                    continue
                if "created_at" not in _cols(table):
                    continue
                try:
                    # Keep newest max_rows by created_at; delete the rest.
                    cur = db.execute(
                        f"DELETE FROM {table} WHERE rowid IN ("
                        f"SELECT rowid FROM {table} ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                        (max_rows,),
                    )
                    n = int(cur.rowcount or 0) if cur else 0
                    if n:
                        out["actions"].append(f"retention:{table}:cap_rows:{max_rows}:{n}")
                except Exception as e:
                    out["actions"].append(f"retention:{table}:cap_skip:{e}")

            db.commit()
        # Cleanup completed/archived study plans (keep actives forever; delete old non-active plans).
        try:
            days = int((c.get("retention_completed_study_plans_days", 90) or 90))
            cutoff = _cutoff(days)
            with _conn() as db:
                cols = {r[1] for r in db.execute("PRAGMA table_info(study_plans)").fetchall()}
                if "created_at" in cols and "status" in cols:
                    cur = db.execute("DELETE FROM study_plans WHERE status != 'active' AND created_at < ?", (cutoff,))
                    n = int(cur.rowcount or 0) if cur else 0
                    if n:
                        out["actions"].append(f"retention:study_plans:completed_cleanup_older_than_{days}d:{n}")
                    db.commit()
        except Exception as e:
            out["actions"].append(f"retention:study_plans:skip:{e}")
        return out
    except Exception as e:
        logger.debug("apply_retention_policies: %s", e)
        return {"ok": False, "error": str(e)}


def reinforce_learning(learning_id: int, *, success: bool = True) -> None:
    """Bump stored confidence when a learning contributed to a successful run."""
    if not success:
        return
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        lid = int(learning_id)
        with _conn() as db:
            row = db.execute(
                "SELECT confidence FROM learnings WHERE id=?",
                (lid,),
            ).fetchone()
            if not row:
                return
            base = float(row["confidence"] if hasattr(row, "keys") else row[0] or 0.5)
            new_c = min(1.0, base + 0.04)
            db.execute("UPDATE learnings SET confidence=? WHERE id=?", (new_c, lid))
            db.commit()
    except Exception as e:
        logger.debug("reinforce_learning: %s", e)


def prune_low_confidence_learnings(threshold: float = 0.08, batch: int = 25) -> int:
    """Archive (not delete) a small batch of stale low-confidence learnings.

    Moved from hard-delete to archive: learnings are inserted into
    `learnings_archive` before being removed from the active table.
    This preserves "faded memories" that users can browse or restore.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        from layla.time_utils import utcnow

        migrate()
        th = float(threshold)
        lim = max(1, min(200, int(batch)))
        emb_ids: list[str] = []
        now = utcnow()
        with _conn() as db:
            # First, archive the learnings before deleting
            try:
                to_archive = db.execute(
                    f"SELECT id, content, type, created_at, confidence, tags, aspect_id "
                    f"FROM learnings WHERE confidence IS NOT NULL AND confidence < ? "
                    f"ORDER BY id ASC LIMIT {lim}",
                    (th,),
                ).fetchall()
                for row in (to_archive or []):
                    try:
                        r = dict(row) if hasattr(row, 'keys') else {
                            "id": row[0], "content": row[1], "type": row[2],
                            "created_at": row[3], "confidence": row[4],
                            "tags": row[5] if len(row) > 5 else "",
                            "aspect_id": row[6] if len(row) > 6 else "",
                        }
                        db.execute(
                            "INSERT OR IGNORE INTO learnings_archive "
                            "(id, content, type, created_at, archived_at, archive_reason, original_confidence, tags, aspect_id) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (r.get("id"), r.get("content", ""), r.get("type", "fact"),
                             r.get("created_at", now), now, "confidence_decay",
                             r.get("confidence", 0), r.get("tags", ""), r.get("aspect_id", "")),
                        )
                    except Exception:
                        continue  # Archive is best-effort; don't block pruning
            except Exception as _ae:
                logger.debug("prune_low_confidence: archive step failed (continuing): %s", _ae)

            try:
                cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
                if "embedding_id" in cols:
                    rows = db.execute(
                        f"SELECT embedding_id FROM learnings "
                        f"WHERE confidence IS NOT NULL AND confidence < ? AND embedding_id != '' "
                        f"ORDER BY id ASC LIMIT {lim}",
                        (th,),
                    ).fetchall()
                    emb_ids = [
                        str((r[0] if isinstance(r, (tuple, list)) else r.get("embedding_id")) or "").strip()
                        for r in rows
                        if r
                    ]
                    emb_ids = [e for e in emb_ids if e]
            except Exception:
                emb_ids = []
            cur = db.execute(
                f"DELETE FROM learnings WHERE id IN ("
                f"SELECT id FROM learnings WHERE confidence IS NOT NULL AND confidence < ? "
                f"ORDER BY id ASC LIMIT {lim})",
                (th,),
            )
            n = cur.rowcount if cur else 0
            db.commit()
        if emb_ids:
            try:
                from layla.memory.vector_store import delete_vectors_by_ids

                delete_vectors_by_ids(emb_ids)
            except Exception:
                pass
        if n:
            logger.info("memory_consolidation: archived and pruned %d low-confidence learnings", n)
        return int(n or 0)
    except Exception as e:
        logger.debug("prune_low_confidence_learnings: %s", e)
        return 0

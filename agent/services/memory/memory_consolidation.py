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
            from services.infrastructure.session_context import get_or_create_session

            ev = get_or_create_session(cid).get_outcome_evaluation() or {}
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
            # M2: previously-unbounded tables. Each guarded by _cols() (skipped if absent/no created_at).
            # NB: the created table is 'operator_journal' (migrations.py) — an earlier 'journal'
            # here silently no-op'd because _cols('journal') is empty, defeating retention entirely.
            ("operator_journal", int(c.get("retention_journal_days", 365)), None),
            ("scheduler_history", int(c.get("retention_scheduler_history_days", 90)), None),
            ("capability_events", int(c.get("retention_capability_events_days", 180)), None),
            ("wakeup_log", int(c.get("retention_wakeup_log_days", 180)), None),
            # audit #8: memory_conflicts was append-only with no cap/cleanup. Age-based on created_at
            # (the consistency guard writes created_at); a resolved conflict has no long-term value.
            ("memory_conflicts", int(c.get("retention_memory_conflicts_days", 90)), None),
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
            # M2: learnings_archive is an INSERT-only sink (prune archives INTO it, nothing prunes
            # it) — hard-cap it. strategy_stats grows with routing history.
            ("learnings_archive", int(c.get("retention_learnings_archive_max_rows", 20000))),
            ("strategy_stats", int(c.get("retention_strategy_stats_max_rows", 10000))),
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

            _orphan_vector_ids: list[str] = []  # H1: vectors whose rows we're deleting
            for table, days, _ in policies:
                if "created_at" not in _cols(table):
                    # Either the table doesn't exist (name mismatch) or has no created_at
                    # column — the policy silently no-ops. Log it so a future typo like the
                    # 'journal' vs 'operator_journal' mismatch surfaces instead of hiding.
                    logger.debug(
                        "memory_consolidation: retention policy for %r skipped "
                        "(table absent or no created_at column)", table,
                    )
                    continue
                cutoff = _cutoff(days)
                try:
                    # If the table's rows carry vectors, collect their embedding_ids BEFORE the
                    # delete so we can drop the vectors too — otherwise they orphan in the vector
                    # store and keep surfacing stale content the product has "forgotten" (H1).
                    if "embedding_id" in _cols(table):
                        try:
                            _rows = db.execute(
                                f"SELECT embedding_id FROM {table} "
                                f"WHERE created_at < ? AND embedding_id IS NOT NULL AND embedding_id != ''",
                                (cutoff,),
                            ).fetchall()
                            _orphan_vector_ids.extend(
                                (r[0] if isinstance(r, (tuple, list)) else r["embedding_id"]) for r in _rows
                            )
                        except Exception:
                            pass
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
                tcols = _cols(table)
                if not tcols:
                    # Table absent (name mismatch) — nothing to cap.
                    continue
                # audit #7: pick the table's ACTUAL recency column. strategy_stats has no
                # created_at (its timestamp is last_updated_at), so a created_at-only guard
                # silently no-op'd the 10k cap and the table grew one row per distinct goal.
                # Fall back to last_updated_at, then rowid (monotonic insert order), so the cap
                # always fires regardless of the table's timestamp column name.
                if "created_at" in tcols:
                    order_col = "created_at"
                elif "last_updated_at" in tcols:
                    order_col = "last_updated_at"
                else:
                    order_col = "rowid"
                try:
                    # Keep newest max_rows by the recency column; delete the rest.
                    cur = db.execute(
                        f"DELETE FROM {table} WHERE rowid IN ("
                        f"SELECT rowid FROM {table} ORDER BY {order_col} DESC LIMIT -1 OFFSET ?)",
                        (max_rows,),
                    )
                    n = int(cur.rowcount or 0) if cur else 0
                    if n:
                        out["actions"].append(f"retention:{table}:cap_rows:{max_rows}:{n}")
                except Exception as e:
                    out["actions"].append(f"retention:{table}:cap_skip:{e}")

            db.commit()
        # H1: after the layla.db transaction commits, drop the vectors whose rows were deleted
        # (the vector store is a separate file/Chroma, so this is done outside the DB lock).
        if _orphan_vector_ids:
            try:
                from layla.memory.vector_store import delete_vectors_by_ids
                delete_vectors_by_ids(_orphan_vector_ids)
                out["actions"].append(f"retention:vectors_deleted:{len(_orphan_vector_ids)}")
            except Exception as e:
                out["actions"].append(f"retention:vectors_delete_skip:{e}")
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


def decay_stored_confidence(cfg: dict | None = None) -> int:
    """Age-decay the STORED confidence of learnings so unused memories actually fade (audit B2).

    Root cause fixed: confidence decay was READ-time only; the stored `confidence` was never
    decremented (reinforce only ratcheted it UP), so ingested rows (default 0.5) could never
    reach the 0.08 archive threshold — the memory store grew forever and retrieval got noisier.

    Each run multiplies stored confidence by a <1 factor for rows past a short grace period.
    `reinforce_learning` (+0.04/use) counteracts this, so frequently-used memories survive while
    stale ones drift below the threshold and are archived by prune_low_confidence_learnings.
    Returns rows affected. Idempotent-safe: applied once per daily cleanup.
    """
    cfg = cfg or {}
    try:
        decay = float(cfg.get("learnings_confidence_decay_per_day", 0.98) or 0.98)
    except (TypeError, ValueError):
        decay = 0.98
    if not (0.0 < decay < 1.0):
        return 0  # decay disabled / misconfigured — never boost or zero out
    try:
        grace_days = max(0, int(cfg.get("learnings_decay_grace_days", 7) or 7))
    except (TypeError, ValueError):
        grace_days = 7
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=grace_days)).isoformat()
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if "confidence" not in cols:
                return 0
            cur = db.execute(
                "UPDATE learnings SET confidence = confidence * ? "
                "WHERE confidence IS NOT NULL AND created_at < ?",
                (decay, cutoff),
            )
            n = int(cur.rowcount or 0)
            db.commit()
        return n
    except Exception as e:
        logger.debug("decay_stored_confidence: %s", e)
        return 0


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

"""Learnings and spaced-repetition helpers (SQLite)."""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import deque

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")

_rate_lock = threading.Lock()
_recent_learning_ts: deque[float] = deque()


# ── encryption-at-rest for `sensitive` learnings (BL-020) ────────────────────
# decrypt() is a transparent no-op on plaintext, so wrapping every read is safe for
# legacy rows; maybe_encrypt() only encrypts when the flag is on AND privacy=sensitive,
# so with the feature off nothing changes.
def _dec(v):
    """Decrypt a stored content value (no-op for plaintext / when unavailable)."""
    try:
        from services.memory.memory_encryption import decrypt
        return decrypt(v)
    except Exception:
        return v


def _decrypt_rows(rows: list[dict], key: str = "content") -> list[dict]:
    for r in rows:
        if isinstance(r, dict) and r.get(key):
            r[key] = _dec(r[key])
    return rows


# ── learnings ──────────────────────────────────────────────────────────────

def save_learning(
    content: str,
    kind: str = "fact",
    embedding_id: str = "",
    confidence: float = 0.5,
    source: str = "",
    score: float = 1.0,
    tags: str = "",
    aspect_id: str = "",
    privacy_level: str = "",
) -> int:
    """Save a learning. Uses content_hash for dedup. confidence: 0.9 study, 0.7 LLM, 0.4 heuristic.
    Hook: learning quality filter rejects short/uncertain entries; long content summarized before storing.
    `privacy_level="sensitive"` + the `encryption_at_rest_enabled` flag → content is encrypted at rest
    (BL-020): stored ciphertext, dedup still on plaintext hash, and the plaintext is kept OUT of the
    embedding + Elasticsearch index (FTS auto-indexes the opaque ciphertext, which cannot be searched)."""
    migrate()
    # Simple in-process rate limit: protects DB + vector store from rapid-fire learning spam.
    # Best-effort only (resets on restart).
    try:
        limit = 20
        window_s = 60.0
        now = time.time()
        with _rate_lock:
            while _recent_learning_ts and (now - _recent_learning_ts[0]) > window_s:
                _recent_learning_ts.popleft()
            if len(_recent_learning_ts) >= limit:
                try:
                    from services.observability import log_learning_skipped
                    log_learning_skipped(reason="rate_limited")
                except Exception:
                    pass
                logger.debug("save_learning rate-limited (%d/%d in %.0fs window)", limit, limit, window_s)
                return -1
            _recent_learning_ts.append(now)
    except Exception:
        pass
    try:
        from services.memory.learning_filter import filter_learning
        pass_filter, filtered, reason = filter_learning(content)
        if not pass_filter:
            try:
                from services.observability import log_learning_skipped
                log_learning_skipped(reason=reason or "filter_rejected")
            except Exception:
                pass
            return -1
        content = filtered or content
    except Exception:
        pass
    try:
        from layla.memory.distill import passes_learning_quality_gate

        ok_q, qscore = passes_learning_quality_gate(content)
        if not ok_q:
            try:
                from services.observability import log_learning_skipped

                log_learning_skipped(reason=f"quality_gate:{qscore:.2f}")
            except Exception:
                pass
            return -1
    except Exception:
        pass
    learning_type = kind if kind in ("fact", "preference", "strategy", "identity") else "fact"
    content_hash = hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()  # PLAINTEXT hash (dedup)
    score = max(0.0, min(1.0, float(score)))
    tags_s = (tags or "").strip()[:500]
    # Encrypt at rest for sensitive content (BL-020). content_hash above stays plaintext so dedup
    # is unaffected; `stored_content` is what actually lands in the row (+ the FTS trigger).
    stored_content = content
    _sensitive = False
    if str(privacy_level or "").lower() == "sensitive":
        try:
            import runtime_safety
            from services.memory.memory_encryption import maybe_encrypt
            stored_content = maybe_encrypt(content, privacy_level, runtime_safety.load_config())
            _sensitive = stored_content != content
        except Exception:
            stored_content = content
            _sensitive = False
    with _conn() as db:
        try:
            has_hash = any(r[1] == "content_hash" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_hash = False
        try:
            has_tags = any(r[1] == "tags" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_tags = False
        if has_hash:
            row = db.execute("SELECT id FROM learnings WHERE content_hash=? AND content_hash!=''", (content_hash,)).fetchone()
            if row:
                return row[0]
        try:
            if has_tags:
                cur = db.execute(
                    """INSERT INTO learnings (content, type, created_at, embedding_id, learning_type, confidence, source, content_hash, score, tags)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        stored_content,
                        learning_type,
                        utcnow().isoformat(),
                        embedding_id,
                        learning_type,
                        confidence,
                        source,
                        content_hash,
                        score,
                        tags_s,
                    ),
                )
            else:
                cur = db.execute(
                    """INSERT INTO learnings (content, type, created_at, embedding_id, learning_type, confidence, source, content_hash, score)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (stored_content, learning_type, utcnow().isoformat(), embedding_id, learning_type, confidence, source, content_hash, score),
                )
        except sqlite3.OperationalError:
            cur = db.execute(
                "INSERT INTO learnings (content, type, created_at, embedding_id, learning_type) VALUES (?,?,?,?,?)",
                (stored_content, learning_type, utcnow().isoformat(), embedding_id, learning_type),
            )
        db.commit()
        rid = cur.lastrowid
        if rid and int(rid) > 0:
            # P1-9: dual-write consistency — if no embedding_id yet, try ChromaDB write now.
            # BL-020: never embed sensitive plaintext (the vector would leak its meaning).
            if not embedding_id and not _sensitive:
                try:
                    from layla.memory.vector_store import add_vector, embed
                    vec = embed(content)
                    meta = {"content": content, "type": learning_type}
                    if tags_s:
                        meta["tags"] = tags_s
                    new_eid = add_vector(vec, meta)
                    if new_eid:
                        db.execute("UPDATE learnings SET embedding_id=? WHERE id=?", (new_eid, int(rid)))
                        db.commit()
                except Exception as _vec_exc:
                    logger.warning("save_learning: ChromaDB write failed for learning %s, marking needs_reindex=1: %s", rid, _vec_exc)
                    try:
                        has_reindex_col = any(
                            r[1] == "needs_reindex" for r in db.execute("PRAGMA table_info(learnings)").fetchall()
                        )
                        if has_reindex_col:
                            db.execute("UPDATE learnings SET needs_reindex=1 WHERE id=?", (int(rid),))
                            db.commit()
                    except Exception:
                        pass
            asp = (aspect_id or "").strip()[:64]
            if asp:
                try:
                    has_asp_col = any(
                        r[1] == "aspect_id" for r in db.execute("PRAGMA table_info(learnings)").fetchall()
                    )
                except Exception:
                    has_asp_col = False
                if has_asp_col:
                    try:
                        db.execute("UPDATE learnings SET aspect_id=? WHERE id=?", (asp, int(rid)))
                        db.commit()
                    except Exception:
                        pass
            # BL-020: persist the privacy level so privacy-filtered retrieval (memory_router)
            # and exports see it. Column has DEFAULT 'public'; only write when non-default.
            _pl = str(privacy_level or "").strip().lower()
            if _pl and _pl != "public":
                try:
                    has_priv_col = any(
                        r[1] == "privacy_level" for r in db.execute("PRAGMA table_info(learnings)").fetchall()
                    )
                    if has_priv_col:
                        db.execute("UPDATE learnings SET privacy_level=? WHERE id=?", (_pl, int(rid)))
                        db.commit()
                except Exception:
                    pass
            if not _sensitive:  # BL-020: keep sensitive plaintext out of the Elasticsearch index
                try:
                    import runtime_safety
                    from services.retrieval.elasticsearch_bridge import index_learning

                    index_learning(
                        runtime_safety.load_config(),
                        rid=int(rid),
                        text=content,
                        tags=tags_s,
                        source=source or "learning",
                    )
                except Exception:
                    pass
        try:
            from services.observability import log_learning_saved
            log_learning_saved(content_preview=content[:80], source=source or "db")
        except Exception:
            pass
        # Layla v3: maturity XP for saved learnings (best-effort; never raise).
        if rid and int(rid) > 0:
            try:
                from services.personality.maturity_engine import award_xp

                award_xp(10, reason=f"learning_saved:{learning_type}")
            except Exception:
                pass
        # Section 5: graph expansion in background (daemon thread, non-blocking)
        if rid and content:
            try:
                import threading
                def _expand():
                    try:
                        from services.memory.graph_learning import expand_graph_from_learning
                        expand_graph_from_learning(content)
                    except Exception:
                        pass
                t = threading.Thread(target=_expand, daemon=True, name="graph-expand")
                t.start()
            except Exception:
                pass
        # Memory self-consistency guard: flag (don't block) if this new learning likely
        # contradicts a stored one, for later reconcile. Non-blocking; skip sensitive plaintext.
        if rid and content and not _sensitive:
            try:
                import threading
                def _consistency():
                    try:
                        from services.memory.consistency_guard import check_and_flag
                        check_and_flag(content, new_id=int(rid))
                    except Exception:
                        pass
                threading.Thread(target=_consistency, daemon=True, name="memory-consistency").start()
            except Exception:
                pass
        try:
            from services.memory.personal_knowledge_graph import invalidate_personal_graph
            invalidate_personal_graph()
        except Exception:
            pass
        return rid


_ASPECT_LEARNING_PREFERENCE = {"echo": "preference", "morrigan": "strategy", "nyx": "fact"}


def count_learnings() -> int:
    """Return total number of stored learnings quickly."""
    migrate()
    with _conn() as db:
        row = db.execute("SELECT COUNT(*) AS c FROM learnings").fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0


def get_recent_learnings(n: int = 30, aspect_id: str | None = None, min_score: float | None = None) -> list[dict]:
    """Recent learnings. If aspect_id given, prefer learning_type: Echo->preference, Morrigan->strategy, Nyx->fact."""
    migrate()
    with _conn() as db:
        try:
            has_lt = any(r[1] == "learning_type" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            has_asp_col = any(r[1] == "aspect_id" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_lt = False
            has_conf = False
            has_asp_col = False
        sel = "id, content, type, created_at, embedding_id"
        if has_conf:
            sel += ", confidence"
        if has_asp_col:
            sel += ", aspect_id"
        has_score = any(r[1] == "score" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        if has_score:
            sel += ", score"
        score_filter = ""
        args: list = []
        if has_score and min_score is not None:
            score_filter = " WHERE COALESCE(score, 1.0) >= ?"
            args.append(float(min_score))
        asp_extra = ""
        asp_args: list = []
        if has_asp_col and aspect_id:
            a = aspect_id.strip().lower()
            if a:
                if " WHERE " in score_filter:
                    asp_extra = " AND (COALESCE(aspect_id,'') = '' OR LOWER(aspect_id) = ?)"
                else:
                    asp_extra = " WHERE (COALESCE(aspect_id,'') = '' OR LOWER(aspect_id) = ?)"
                asp_args.append(a)
        combined_where = score_filter + asp_extra
        if not has_lt or not aspect_id:
            rows = db.execute(
                f"SELECT {sel} FROM learnings{combined_where} ORDER BY id DESC LIMIT ?",
                tuple(args + asp_args + [n]),
            ).fetchall()
        else:
            pref = _ASPECT_LEARNING_PREFERENCE.get(aspect_id.lower(), "fact")
            sel_lt = sel + ", learning_type" if has_lt else sel
            rows = db.execute(
                f"""SELECT {sel_lt} FROM learnings
                   {combined_where}
                   ORDER BY CASE WHEN learning_type = ? THEN 0 ELSE 1 END, id DESC LIMIT ?""",
                tuple(args + asp_args + [pref, n]),
            ).fetchall()
        result = [dict(r) for r in reversed(rows)]
        for r in result:
            if r.get("content"):
                r["content"] = _dec(r["content"])  # BL-020: transparent decrypt (no-op for plaintext)
            if "learning_type" not in r and "type" in r:
                r["learning_type"] = r["type"]
            if has_conf:
                r["adjusted_confidence"] = _apply_confidence_decay(r.get("confidence"), r.get("created_at", ""))
        return result


def _apply_confidence_decay(confidence: float, created_at: str) -> float:
    """Age-based decay: adjusted = confidence * exp(-age_days/180)."""
    import math
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        from datetime import timezone
        dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        age_days = (utcnow() - dt_utc).total_seconds() / 86400.0
    except Exception:
        age_days = 0.0
    conf = float(confidence) if confidence is not None else 0.5
    return conf * math.exp(-age_days / 180.0)


def search_learnings_fts(query: str, n: int = 20, aspect_id: str | None = None) -> list[dict]:
    """
    FTS5 full-text search over learnings using Porter stemmer + unicode tokenization.
    Falls back to LIKE search if FTS5 table is missing.
    Returns list of matching learning dicts ordered by relevance (BM25 rank).
    Applies age-based confidence decay for retrieval scoring.
    """
    migrate()
    with _conn() as db:
        try:
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            has_asp_col = any(r[1] == "aspect_id" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            sel = "l.id, l.content, l.type, l.created_at"
            if has_conf:
                sel += ", l.confidence"
            asp = (aspect_id or "").strip().lower()
            asp_sql = ""
            asp_args: list = []
            if has_asp_col and asp:
                asp_sql = " AND (COALESCE(l.aspect_id,'') = '' OR LOWER(l.aspect_id) = ?)"
                asp_args.append(asp)
            rows = db.execute(
                f"""SELECT {sel}
                   FROM learnings l
                   JOIN learnings_fts f ON l.id = f.rowid
                   WHERE learnings_fts MATCH ?{asp_sql}
                   ORDER BY rank
                   LIMIT ?""",
                ('"' + query.replace('"', '""') + '"', *asp_args, n),
            ).fetchall()
            result = [dict(r) for r in rows]
            for r in result:
                if r.get("content"):
                    r["content"] = _dec(r["content"])  # BL-020
                conf = r.get("confidence")
                created = r.get("created_at", "")
                r["adjusted_confidence"] = _apply_confidence_decay(conf, created)
            return result
        except Exception:
            # Fallback: simple LIKE search
            try:
                has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
                has_asp_col = any(r[1] == "aspect_id" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
                sel = "id, content, type, created_at"
                if has_conf:
                    sel += ", confidence"
                asp = (aspect_id or "").strip().lower()
                like_asp = ""
                la: list = []
                if has_asp_col and asp:
                    like_asp = " AND (COALESCE(aspect_id,'') = '' OR LOWER(aspect_id) = ?)"
                    la.append(asp)
                rows = db.execute(
                    f"SELECT {sel} FROM learnings WHERE content LIKE ?{like_asp} LIMIT ?",
                    (f"%{query}%", *la, n),
                ).fetchall()
                result = [dict(r) for r in rows]
                for r in result:
                    if r.get("content"):
                        r["content"] = _dec(r["content"])  # BL-020
                    r["adjusted_confidence"] = _apply_confidence_decay(r.get("confidence"), r.get("created_at", ""))
                return result
            except Exception:
                return []


def save_outcome_evaluation(conversation_id: str, evaluation: dict) -> None:
    """Persist last structured outcome evaluation (survives restarts)."""
    if not isinstance(evaluation, dict):
        return
    cid = (conversation_id or "").strip() or "default"
    try:
        payload = json.dumps(evaluation, ensure_ascii=False)
    except Exception:
        return
    migrate()
    with _conn() as db:
        db.execute(
            "INSERT INTO outcome_evaluations(conversation_id, created_at, evaluation_json) VALUES (?, ?, ?)",
            (cid, utcnow().isoformat(), payload),
        )
        db.commit()


def get_last_outcome_evaluation_record(conversation_id: str) -> dict | None:
    """Return latest persisted outcome evaluation for a conversation id."""
    cid = (conversation_id or "").strip() or "default"
    migrate()
    with _conn() as db:
        row = db.execute(
            "SELECT evaluation_json FROM outcome_evaluations WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (cid,),
        ).fetchone()
        if not row:
            return None
        raw = row[0] if isinstance(row, (tuple, list)) else row.get("evaluation_json")
        if not raw:
            return None
        try:
            v = json.loads(raw)
            return dict(v) if isinstance(v, dict) else None
        except Exception:
            return None


def get_learnings_by_embedding_ids(embedding_ids: list[str]) -> dict[str, dict]:
    """Look up confidence and created_at for learnings by embedding_id. Used for retrieval scoring."""
    if not embedding_ids:
        return {}
    migrate()
    result = {}
    with _conn() as db:
        try:
            has_conf = any(r[1] == "confidence" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_conf = False
        sel = "embedding_id, created_at"
        if has_conf:
            sel += ", confidence"
        placeholders = ",".join("?" * len(embedding_ids))
        rows = db.execute(
            f"SELECT {sel} FROM learnings WHERE embedding_id IN ({placeholders}) AND embedding_id != ''",
            tuple(embedding_ids),
        ).fetchall()
        for r in rows:
            rid = r["embedding_id"]
            conf = r.get("confidence")
            created = r.get("created_at", "")
            result[rid] = {
                "confidence": float(conf) if conf is not None else 0.5,
                "created_at": created,
                "adjusted_confidence": _apply_confidence_decay(conf, created),
            }
    return result


def delete_learnings_by_id(ids: list) -> None:
    """Remove learnings by id list. Used by memory distillation."""
    if not ids:
        return
    migrate()
    placeholders = ",".join("?" * len(ids))
    with _conn() as db:
        try:
            rows = db.execute(
                f"SELECT embedding_id FROM learnings WHERE id IN ({placeholders}) AND embedding_id != ''",
                tuple(ids),
            ).fetchall()
            emb_ids = [
                (r[0] if isinstance(r, (tuple, list)) else r.get("embedding_id"))
                for r in rows
                if r
            ]
            emb_ids = [str(e).strip() for e in emb_ids if e]
        except Exception:
            emb_ids = []
        db.execute(f"DELETE FROM learnings WHERE id IN ({placeholders})", tuple(ids))
        db.commit()
    if emb_ids:
        try:
            from layla.memory.vector_store import delete_vectors_by_ids

            delete_vectors_by_ids(emb_ids)
        except Exception:
            pass


def get_learnings_due_for_review(limit: int = 10) -> list[dict]:
    """
    Return learnings due for spaced repetition review.
    next_review_at <= now or NULL; ordered by importance_score then created_at.
    """
    migrate()
    now = utcnow().isoformat()
    with _conn() as db:
        try:
            has_col = any(r[1] == "next_review_at" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
        except Exception:
            has_col = False
        if not has_col:
            return []
        rows = db.execute(
            """SELECT id, content, type, created_at, importance_score, next_review_at
               FROM learnings
               WHERE next_review_at IS NULL OR next_review_at <= ?
               ORDER BY COALESCE(importance_score, 0.5) DESC, created_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
    return _decrypt_rows([dict(r) for r in rows])  # BL-020


def schedule_next_review(learning_id: int, interval_hours: float = 24.0) -> None:
    """Schedule next review for a learning at a fixed offset. For adaptive SM-2 scheduling
    (interval grows/resets with recall quality) use `services.memory.spaced_repetition.review_item`,
    which loads/persists per-item state via get_review_state / set_review_state."""
    migrate()
    from datetime import datetime, timedelta, timezone
    try:
        next_at = (datetime.now(timezone.utc) + timedelta(hours=interval_hours)).isoformat()
        with _conn() as db:
            db.execute("UPDATE learnings SET next_review_at = ? WHERE id = ?", (next_at, learning_id))
            db.commit()
    except Exception as e:
        logger.warning("schedule_next_review failed: %s", e)


def get_review_state(learning_id: int) -> dict:
    """Per-item SM-2 state (ease, interval_days, reps) for adaptive spaced repetition (BL-134).
    Returns sensible defaults (2.5 / 0 / 0) for a never-reviewed or pre-migration item."""
    migrate()
    default = {"ease": 2.5, "interval_days": 0, "reps": 0}
    try:
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if not {"review_ease", "review_interval_days", "review_reps"} <= cols:
                return default
            row = db.execute(
                "SELECT review_ease, review_interval_days, review_reps FROM learnings WHERE id = ?",
                (learning_id,),
            ).fetchone()
        if not row:
            return default
        return {
            "ease": float(row[0]) if row[0] is not None else 2.5,
            "interval_days": int(row[1]) if row[1] is not None else 0,
            "reps": int(row[2]) if row[2] is not None else 0,
        }
    except Exception as e:
        logger.warning("get_review_state failed: %s", e)
        return default


def set_review_state(
    learning_id: int,
    *,
    ease: float,
    interval_days: int,
    reps: int,
    interval_hours: float | None = None,
) -> None:
    """Persist per-item SM-2 state and schedule the next review (BL-134). `interval_hours`
    overrides the next-review offset; defaults to interval_days * 24."""
    migrate()
    from datetime import datetime, timedelta, timezone
    hours = interval_hours if interval_hours is not None else max(0.0, float(interval_days)) * 24.0
    next_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    try:
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if {"review_ease", "review_interval_days", "review_reps"} <= cols:
                db.execute(
                    """UPDATE learnings
                       SET review_ease = ?, review_interval_days = ?, review_reps = ?, next_review_at = ?
                       WHERE id = ?""",
                    (float(ease), int(interval_days), int(reps), next_at, learning_id),
                )
            else:  # pre-migration fallback: at least schedule the next review
                db.execute("UPDATE learnings SET next_review_at = ? WHERE id = ?", (next_at, learning_id))
            db.commit()
    except Exception as e:
        logger.warning("set_review_state failed: %s", e)


def set_learning_importance(learning_id: int, score: float) -> None:
    """Set importance_score (0-1) for a learning. Higher = more likely to persist."""
    migrate()
    score = max(0.0, min(1.0, score))
    try:
        with _conn() as db:
            has_col = any(r[1] == "importance_score" for r in db.execute("PRAGMA table_info(learnings)").fetchall())
            if has_col:
                db.execute("UPDATE learnings SET importance_score = ? WHERE id = ?", (score, learning_id))
                db.commit()
    except Exception as e:
        logger.warning("set_learning_importance failed: %s", e)


def get_top_learnings_for_planning(limit: int = 5, *, min_confidence: float = 0.66) -> list[dict]:
    """
    Return top learnings to inject as binding priors for planning.
    Heuristic: high confidence first, then high importance_score, then recency.
    """
    migrate()
    lim = max(1, min(20, int(limit or 5)))
    mc = float(min_confidence)
    try:
        with _conn() as db:
            cols = [r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()]
            has_conf = "confidence" in cols
            has_imp = "importance_score" in cols
            sel = "id, content, type, created_at"
            if has_conf:
                sel += ", confidence"
            if has_imp:
                sel += ", importance_score"
            where = "WHERE content IS NOT NULL AND TRIM(content) != ''"
            args: list = []
            if has_conf:
                where += " AND COALESCE(confidence, 0.5) >= ?"
                args.append(mc)
            order = []
            if has_conf:
                order.append("COALESCE(confidence, 0.5) DESC")
            if has_imp:
                order.append("COALESCE(importance_score, 0.5) DESC")
            order.append("created_at DESC")
            sql = f"SELECT {sel} FROM learnings {where} ORDER BY {', '.join(order)} LIMIT ?"
            args.append(lim)
            rows = db.execute(sql, tuple(args)).fetchall()
            return _decrypt_rows([dict(r) for r in rows])  # BL-020
    except Exception:
        return []


def reindex_failed_learnings() -> int:
    """P1-9: re-embed learnings whose ChromaDB write failed (needs_reindex=1).

    Queries up to 50 rows, re-embeds each, and writes to ChromaDB.
    On success, clears needs_reindex and updates embedding_id.
    Returns count of successfully reindexed learnings.
    """
    migrate()
    reindexed = 0
    try:
        with _conn() as db:
            cols = {r[1] for r in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if "needs_reindex" not in cols:
                return 0
            rows = db.execute(
                "SELECT id, content, type FROM learnings WHERE needs_reindex=1 LIMIT 50"
            ).fetchall()
            if not rows:
                return 0
        from layla.memory.vector_store import add_vector, embed
        for row in rows:
            learning_id = row["id"]
            content = row["content"] or ""
            learning_type = row["type"] or "fact"
            if not content.strip():
                continue
            try:
                vec = embed(content)
                meta = {"content": content, "type": learning_type}
                new_eid = add_vector(vec, meta)
                with _conn() as db:
                    db.execute(
                        "UPDATE learnings SET embedding_id=?, needs_reindex=0 WHERE id=?",
                        (new_eid, int(learning_id)),
                    )
                    db.commit()
                reindexed += 1
            except Exception as _e:
                logger.warning("reindex_failed_learnings: failed for learning %s: %s", learning_id, _e)
    except Exception as _e:
        logger.warning("reindex_failed_learnings: %s", _e)
    if reindexed > 0:
        logger.info("reindex_failed_learnings: successfully reindexed %d learnings", reindexed)
    return reindexed



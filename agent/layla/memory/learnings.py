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
) -> int:
    """Save a learning. Uses content_hash for dedup. confidence: 0.9 study, 0.7 LLM, 0.4 heuristic.
    Hook: learning quality filter rejects short/uncertain entries; long content summarized before storing."""
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
                return -1
            _recent_learning_ts.append(now)
    except Exception:
        pass
    try:
        from services.learning_filter import filter_learning
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
    content_hash = hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()
    score = max(0.0, min(1.0, float(score)))
    tags_s = (tags or "").strip()[:500]
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
                        content,
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
                    (content, learning_type, utcnow().isoformat(), embedding_id, learning_type, confidence, source, content_hash, score),
                )
        except sqlite3.OperationalError:
            cur = db.execute(
                "INSERT INTO learnings (content, type, created_at, embedding_id, learning_type) VALUES (?,?,?,?,?)",
                (content, learning_type, utcnow().isoformat(), embedding_id, learning_type),
            )
        db.commit()
        rid = cur.lastrowid
        if rid and int(rid) > 0:
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
            try:
                import runtime_safety
                from services.elasticsearch_bridge import index_learning

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
                from services.maturity_engine import award_xp

                award_xp(10, reason=f"learning_saved:{learning_type}")
            except Exception:
                pass
        # Section 5: graph expansion in background (daemon thread, non-blocking)
        if rid and content:
            try:
                import threading
                def _expand():
                    try:
                        from services.graph_learning import expand_graph_from_learning
                        expand_graph_from_learning(content)
                    except Exception:
                        pass
                t = threading.Thread(target=_expand, daemon=True, name="graph-expand")
                t.start()
            except Exception:
                pass
        try:
            from services.personal_knowledge_graph import invalidate_personal_graph
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
                (query, *asp_args, n),
            ).fetchall()
            result = [dict(r) for r in rows]
            for r in result:
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
    return [dict(r) for r in rows]


def schedule_next_review(learning_id: int, interval_hours: float = 24.0) -> None:
    """Schedule next review for a learning. Uses simple interval (FSRS-style would need more params)."""
    migrate()
    from datetime import datetime, timedelta
    try:
        next_at = (datetime.utcnow() + timedelta(hours=interval_hours)).isoformat() + "Z"
        with _conn() as db:
            db.execute("UPDATE learnings SET next_review_at = ? WHERE id = ?", (next_at, learning_id))
            db.commit()
    except Exception as e:
        logger.warning("schedule_next_review failed: %s", e)


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
            return [dict(r) for r in rows]
    except Exception:
        return []



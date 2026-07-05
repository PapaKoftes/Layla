"""Learning from feedback (BL-242) — close the loop on explicit answer feedback.

`rl_feedback` already turns *tool* outcomes into preference hints. This does the same for
*answers*: a 👍/👎 signal (and an optional written correction) on a reply. A 👎 with a
correction is the highest-signal event there is — it's routed into the learning store
(so it influences planning/prompts through the existing channel) and surfaced as a
prompt hint ("the user previously corrected …"), so the next turn actually behaves
differently. Ratings are also tallied so the loop's effect is observable.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

RATINGS = ("up", "down")


def _data_dir() -> Path:
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "answer_feedback.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS answer_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT DEFAULT '',
                rating TEXT NOT NULL,
                goal TEXT DEFAULT '',
                answer TEXT DEFAULT '',
                correction TEXT DEFAULT '',
                routed_to_learning INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _route_correction_to_learning(goal: str, correction: str) -> bool:
    """A 👎 correction becomes a durable learning that feeds future prompts/planning."""
    try:
        from layla.memory.learnings import save_learning
        content = f"User correction: {correction.strip()}"
        if goal.strip():
            content += f" (re: {goal.strip()[:160]})"
        lid = save_learning(
            content, kind="correction", confidence=0.85,
            source="user_feedback", score=1.0, tags="feedback,correction",
        )
        return lid != -1 and lid is not None
    except Exception as e:  # noqa: BLE001
        logger.debug("route correction to learning failed: %s", e)
        return False


def record_feedback(
    rating: str,
    *,
    goal: str = "",
    answer: str = "",
    correction: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    """Record 👍/👎 on an answer. A 👎 correction is routed into the learning loop."""
    rating = (rating or "").strip().lower()
    if rating not in RATINGS:
        return {"ok": False, "error": f"rating must be one of {RATINGS}"}
    correction = (correction or "").strip()
    routed = False
    if rating == "down" and correction:
        routed = _route_correction_to_learning(goal, correction)
    # BL-190: let the feedback tint Layla's mood (praise on 👍, correction on 👎).
    try:
        from services.personality.emotional_presence import register_signal
        register_signal("praise" if rating == "up" else "correction")
    except Exception as e:  # noqa: BLE001
        logger.debug("mood nudge from feedback skipped: %s", e)
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO answer_feedback (conversation_id, rating, goal, answer, correction,"
            " routed_to_learning, created_at) VALUES (?,?,?,?,?,?,?)",
            (conversation_id, rating, goal[:1000], answer[:2000], correction[:1000],
             int(routed), time.time()),
        )
        return {"ok": True, "id": cur.lastrowid, "rating": rating, "routed_to_learning": routed}


def feedback_stats() -> dict[str, Any]:
    with _db() as conn:
        up = conn.execute("SELECT COUNT(*) FROM answer_feedback WHERE rating='up'").fetchone()[0]
        down = conn.execute("SELECT COUNT(*) FROM answer_feedback WHERE rating='down'").fetchone()[0]
        routed = conn.execute("SELECT COUNT(*) FROM answer_feedback WHERE routed_to_learning=1").fetchone()[0]
    total = up + down
    return {
        "up": up, "down": down, "total": total,
        "satisfaction": round(up / total, 3) if total else None,
        "corrections_routed": routed,
    }


def recent_corrections(limit: int = 5) -> list[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT correction FROM answer_feedback WHERE rating='down' AND correction != ''"
            " ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [r["correction"] for r in rows]


def feedback_hint_for_prompt(max_chars: int = 400) -> str:
    """Recent user corrections, phrased as a behaviour hint for the next turn."""
    corrections = recent_corrections(limit=4)
    if not corrections:
        return ""
    joined = "; ".join(c[:120] for c in corrections)
    return ("Recent user corrections to honour going forward: " + joined)[:max_chars]

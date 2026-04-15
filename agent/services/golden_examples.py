"""
Golden examples: store and retrieve small successful patterns to reuse as few-shot context.

Design goals:
- Deterministic, small, and safe: no network; no extra dependencies.
- Local-only storage in layla.db (SQLite).
- Token-bounded prompt injection (caller controls max_chars).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from layla.memory.db import _conn, migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")


def _tokenize_goal(goal: str) -> set[str]:
    g = (goal or "").lower()
    return set(_WORD_RE.findall(g)) if g else set()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    return inter / max(1, len(a | b))


def store_golden_example(
    task_type: str,
    goal: str,
    decision_pattern: str,
    score: float,
    *,
    min_score: float = 0.85,
    max_rows: int = 200,
) -> bool:
    """Store a golden example if it meets thresholds and is not a near-duplicate."""
    try:
        if float(score) < float(min_score):
            return False
    except Exception:
        return False

    tt = (task_type or "").strip() or "agent"
    gs = (goal or "").strip().replace("\n", " ")
    gs = gs[:240]
    dp = (decision_pattern or "").strip()
    if not gs or not dp:
        return False

    migrate()
    ts = utcnow().isoformat()
    goal_tokens = _tokenize_goal(gs)
    try:
        with _conn() as db:
            # Cap table size (delete lowest-score rows first).
            try:
                cur = db.execute("SELECT COUNT(*) AS n FROM golden_examples")
                n = int((cur.fetchone() or {}).get("n") or 0)
                if n >= int(max_rows):
                    db.execute(
                        """
                        DELETE FROM golden_examples
                        WHERE id IN (
                            SELECT id FROM golden_examples
                            ORDER BY outcome_score ASC, id ASC
                            LIMIT ?
                        )
                        """,
                        (max(1, n - int(max_rows) + 1),),
                    )
            except Exception:
                pass

            # Deduplicate against recent examples for the same task type.
            cur = db.execute(
                """
                SELECT goal_summary
                FROM golden_examples
                WHERE task_type = ?
                ORDER BY id DESC
                LIMIT 40
                """,
                (tt,),
            )
            for row in cur.fetchall() or []:
                try:
                    other = (row["goal_summary"] or "").strip()
                except Exception:
                    other = str(row[0] if row else "").strip()
                if not other:
                    continue
                if _jaccard(goal_tokens, _tokenize_goal(other)) >= 0.7:
                    return False

            db.execute(
                """
                INSERT INTO golden_examples (ts, task_type, goal_summary, decision_pattern, outcome_score, usage_count)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (ts, tt, gs, dp[:1200], float(score)),
            )
            db.commit()
        return True
    except Exception as e:
        logger.debug("store_golden_example failed: %s", e)
        return False


def retrieve_relevant_examples(
    goal: str,
    task_type: str,
    *,
    k: int = 2,
) -> list[dict[str, Any]]:
    """Retrieve up to k relevant examples for a goal using simple lexical overlap."""
    tt = (task_type or "").strip() or "agent"
    tokens = _tokenize_goal(goal)
    if not tokens:
        return []
    migrate()
    try:
        with _conn() as db:
            # Pull a small candidate set by task type and score; rank in Python.
            cur = db.execute(
                """
                SELECT id, goal_summary, decision_pattern, outcome_score, usage_count
                FROM golden_examples
                WHERE task_type = ?
                ORDER BY outcome_score DESC, id DESC
                LIMIT 60
                """,
                (tt,),
            )
            rows = cur.fetchall() or []
        scored: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            gs = (rd.get("goal_summary") or "").strip()
            if not gs:
                continue
            sim = _jaccard(tokens, _tokenize_goal(gs))
            if sim <= 0.0:
                continue
            score = float(sim) + (0.05 * float(rd.get("outcome_score") or 0.0))
            scored.append((score, rd))
        scored.sort(key=lambda x: -x[0])
        out = [x[1] for x in scored[: max(0, int(k))]]
        return out
    except Exception as e:
        logger.debug("retrieve_relevant_examples failed: %s", e)
        return []


def format_for_prompt(examples: list[dict[str, Any]], *, max_chars: int = 1200) -> str:
    """Format examples into a compact prompt section."""
    if not examples:
        return ""
    parts: list[str] = []
    for ex in examples[:3]:
        gs = (ex.get("goal_summary") or "").strip()
        dp = (ex.get("decision_pattern") or "").strip()
        if not gs or not dp:
            continue
        parts.append(f"- Similar goal: {gs}\n  Pattern:\n{dp}")
    if not parts:
        return ""
    text = "Successful patterns (reuse these shapes):\n" + "\n\n".join(parts)
    text = text.strip()
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def bump_usage(example_ids: list[int]) -> None:
    """Best-effort usage_count increment (non-critical)."""
    ids = [int(x) for x in example_ids if isinstance(x, (int, float, str)) and str(x).strip().isdigit()]
    if not ids:
        return
    migrate()
    try:
        with _conn() as db:
            for i in ids[:10]:
                db.execute("UPDATE golden_examples SET usage_count = usage_count + 1 WHERE id = ?", (int(i),))
            db.commit()
    except Exception:
        pass


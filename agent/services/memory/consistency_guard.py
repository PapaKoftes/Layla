"""Memory self-consistency guard (BL-feature): flag when a newly-saved learning likely
contradicts an already-stored one, so the conflict can be surfaced and reconciled instead
of silently storing both.

Deliberately backend-independent — pure SQL candidate-finding over the `learnings` table
plus high-precision heuristics — so it works whether or not the semantic vector store
(Chroma) is enabled. It surfaces *candidate* conflicts for a human to reconcile; it is a
heuristic assistant, not a theorem prover, so it favours precision (few false alarms):

  * numeric value-drift: two same-subject learnings citing different, non-overlapping
    numbers ("timeout is 30s" vs "timeout is 60s") — high precision;
  * negation flip: two near-identical statements where exactly one is negated
    ("X supports Y" vs "X does not support Y"), gated on high term overlap.
"""
from __future__ import annotations

import logging
import re

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")

_STOP = frozenset(
    "the a an is are was were be been being to of in on at for and or but with as by from this "
    "that these those it its their his her your our my we you they he she then than so if not no "
    "never cannot can will would should could may might must do does did has have had".split()
)
_NEG_RE = re.compile(
    r"(?:^|\s)(?:not|no|never|cannot|can['’]?t|isn['’]?t|aren['’]?t|doesn['’]?t|don['’]?t|"
    r"won['’]?t|wasn['’]?t|weren['’]?t|false|incorrect|unsupported|untrue)(?:\s|$|[.,;:])"
)


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text or ""))


def _has_neg(text: str) -> bool:
    return bool(_NEG_RE.search((text or "").lower()))


def _contradiction_reason(a: str, b: str, shared: set[str], terms_a: set[str], terms_b: set[str]) -> str | None:
    if len(shared) < 2:
        return None
    # Numeric value-drift: same subject, different non-overlapping numbers. High precision.
    na, nb = _numbers(a), _numbers(b)
    if na and nb and not (na & nb):
        return f"conflicting values ({', '.join(sorted(na))} vs {', '.join(sorted(nb))})"
    # Negation flip on near-identical statements only (guarded on overlap to avoid false alarms).
    if _has_neg(a) != _has_neg(b):
        overlap = len(shared) / max(1, min(len(terms_a), len(terms_b)))
        if len(shared) >= 3 and overlap >= 0.5:
            return "negation polarity differs on an otherwise near-identical statement"
    return None


def detect_conflict(content: str, *, exclude_id: int | None = None, max_candidates: int = 40) -> dict | None:
    """Return the first likely-contradicting existing learning, or None."""
    terms = _terms(content)
    if len(terms) < 2:
        return None
    top = sorted(terms, key=len, reverse=True)[:4]
    like = " OR ".join(["content LIKE ?"] * len(top))
    params: list = [f"%{t}%" for t in top]
    sql = f"SELECT id, content FROM learnings WHERE ({like})"
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(int(exclude_id))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(max_candidates))
    try:
        with _conn() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
    except Exception as exc:
        logger.debug("consistency_guard candidate query failed: %s", exc)
        return None
    for r in rows:
        eid, ecol = r[0], (r[1] or "")
        if not ecol or ecol.strip() == (content or "").strip():
            continue
        terms_b = _terms(ecol)
        shared = terms & terms_b
        reason = _contradiction_reason(content, ecol, shared, terms, terms_b)
        if reason:
            return {"existing_id": int(eid), "existing_content": ecol, "reason": reason, "shared_terms": sorted(shared)[:8]}
    return None


def record_conflict(new_content: str, conflict: dict, *, new_id: int | None = None) -> int:
    migrate()
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO memory_conflicts (new_id, new_content, existing_id, existing_content, reason, created_at, resolved) "
            "VALUES (?,?,?,?,?,?,0)",
            (
                new_id,
                (new_content or "")[:2000],
                conflict.get("existing_id"),
                (conflict.get("existing_content") or "")[:2000],
                conflict.get("reason", ""),
                utcnow().isoformat(),
            ),
        )
        db.commit()
        return int(cur.lastrowid or 0)


def check_and_flag(content: str, *, new_id: int | None = None) -> dict | None:
    """Detect + record a likely contradiction for a just-saved learning. Best-effort; gated by
    `memory_consistency_guard_enabled` (default True). Never raises."""
    try:
        import runtime_safety
        if not runtime_safety.load_config().get("memory_consistency_guard_enabled", True):
            return None
    except Exception:
        pass
    try:
        conflict = detect_conflict(content, exclude_id=new_id)
        if conflict:
            conflict["conflict_id"] = record_conflict(content, conflict, new_id=new_id)
            logger.info(
                "memory consistency: new learning %s may contradict %s (%s)",
                new_id, conflict["existing_id"], conflict["reason"],
            )
            return conflict
    except Exception as exc:
        logger.debug("consistency_guard check_and_flag failed: %s", exc)
    return None


def list_conflicts(*, unresolved_only: bool = True, limit: int = 50) -> list[dict]:
    migrate()
    cols = ("id", "new_id", "new_content", "existing_id", "existing_content", "reason", "created_at", "resolved")
    sql = f"SELECT {', '.join(cols)} FROM memory_conflicts"
    if unresolved_only:
        sql += " WHERE resolved=0"
    sql += " ORDER BY id DESC LIMIT ?"
    with _conn() as db:
        rows = db.execute(sql, (int(limit),)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def resolve_conflict(conflict_id: int) -> bool:
    migrate()
    with _conn() as db:
        cur = db.execute("UPDATE memory_conflicts SET resolved=1 WHERE id=?", (int(conflict_id),))
        db.commit()
        return (cur.rowcount or 0) > 0

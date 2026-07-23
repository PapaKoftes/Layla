"""Runtime liveness registry — the one signal that catches "correct component, nobody drives it".

This codebase's signature defect is a complete, correct component that never fires: the agent
executed zero tools for 16 days, conversation summaries had 0 rows ever, clustering moved no work,
an SM-2 grader produced 0 rows. Every one had a valid caller and a live import edge, so every static
gate — orphan detection, import graph, the architecture ratchets — reported them healthy. Structure
makes code singular; it cannot make anything *fire*.

A load-bearing EFFECT registers here and calls `fire()` at the moment it actually happens. A monotonic
counter and a last-fired timestamp accumulate in the DB. `check_liveness.py` then reports any effect
that has never fired — turning "the tool pipeline has been dead for two weeks" from something
discovered by accident into a line in a dashboard.

REPORT-ONLY BY DESIGN. This is a single-user machine; a zero count can legitimately mean "not used
this week". It is a signal, never a gate. And it is strictly additive and read-only to the turn:
`fire()` can never raise, so a broken counter cannot break a reply.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

# Named load-bearing effects. The point of naming them is that a NEW one is a deliberate act, and a
# named effect that reports 0 is a question worth asking. Each maps to a confirmed-or-plausible
# historical failure mode.
KNOWN_EFFECTS: dict[str, str] = {
    "tool_executed": "A registry tool actually ran in the agent loop (core.executor.run_tool). "
                     "This was 0 for 16 days while the model chose tools correctly.",
    "turn_committed": "A completed turn was persisted through commit_turn (the single turn seam).",
    "outcome_evaluated": "A turn produced an outcome evaluation (the learning-feedback signal).",
    "conversation_compacted": "Older turns were summarised into conversation_summaries — the "
                              "second-tier memory that had 0 rows for the life of the database.",
}


def _ensure(db) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS liveness ("
        "effect TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, last_fired_at TEXT)"
    )


def fire(effect: str) -> None:
    """Record that a load-bearing effect happened. NEVER raises — a counter must not break a turn."""
    try:
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow

        with _conn() as db:
            _ensure(db)
            db.execute(
                "INSERT INTO liveness(effect, count, last_fired_at) VALUES(?, 1, ?) "
                "ON CONFLICT(effect) DO UPDATE SET count = count + 1, last_fired_at = excluded.last_fired_at",
                (effect, utcnow().isoformat()),
            )
            db.commit()
    except Exception as e:  # noqa: BLE001 — deliberate: liveness is never load-bearing for a reply
        logger.debug("liveness.fire(%r) failed (ignored): %s", effect, e)


def snapshot() -> dict[str, dict]:
    """Every KNOWN effect with its count + last-fired time. Unfired effects appear at count 0."""
    rows: dict[str, dict] = {}
    try:
        from layla.memory.db_connection import _conn

        with _conn() as db:
            _ensure(db)
            for r in db.execute("SELECT effect, count, last_fired_at FROM liveness"):
                rows[r["effect"]] = {"count": r["count"], "last_fired_at": r["last_fired_at"]}
    except Exception as e:  # noqa: BLE001
        logger.debug("liveness.snapshot failed (ignored): %s", e)
    out: dict[str, dict] = {}
    for effect, desc in KNOWN_EFFECTS.items():
        rec = rows.get(effect, {"count": 0, "last_fired_at": None})
        out[effect] = {**rec, "description": desc, "known": True}
    # Surface any effect recorded but not in the registry (a rename left a ghost).
    for effect, rec in rows.items():
        if effect not in out:
            out[effect] = {**rec, "description": "(unregistered effect)", "known": False}
    return out

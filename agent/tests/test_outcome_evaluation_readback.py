"""The learning-feedback loop must be READABLE, not just writable.

`get_last_outcome_evaluation_record` called `.get()` on a sqlite3.Row (which has no `.get`), so every
real read raised AttributeError; the only production caller (SessionContext.get_outcome_evaluation)
swallowed it and returned None. So outcome evaluations were WRITTEN but silently unreadable across a
restart — the "does it learn" loop had a broken read half. This pins the round-trip through the real
reader so the regression can't return.
"""
from __future__ import annotations


def test_persisted_outcome_evaluation_reads_back_through_the_real_reader(isolated_db):
    from layla.memory.learnings import (
        get_last_outcome_evaluation_record,
        save_outcome_evaluation,
    )

    cid = "conv-readback"
    assert get_last_outcome_evaluation_record(cid) is None  # nothing yet

    # save_outcome_evaluation takes a dict (it rejects non-dicts), mirroring the real write path.
    save_outcome_evaluation(cid, {"quality": "good", "score": 0.82, "reason": "grounded"})

    got = get_last_outcome_evaluation_record(cid)
    assert got is not None, "a persisted outcome evaluation must be readable (the .get-on-Row bug)"
    assert got.get("quality") == "good" and abs(got.get("score", 0) - 0.82) < 1e-9

    # latest-wins: a second write is what a subsequent read returns
    save_outcome_evaluation(cid, {"quality": "poor", "score": 0.1})
    latest = get_last_outcome_evaluation_record(cid)
    assert latest and latest.get("quality") == "poor"


def test_clear_outcome_evaluation_clears_the_durable_row(isolated_db):
    """`clear` must clear the DURABLE record, not just an in-memory cache.

    Once the DB read works (the .get-on-Row fix), clearing only in-memory left the row behind, so a
    fresh SessionContext (or the get() DB-fallback) resurrected the value — exactly what the full suite
    caught in test_outcome_evaluation_lifecycle. This pins the cross-instance clear: a NEW context
    (simulating a restart) must see None after a clear.
    """
    from services.infrastructure.session_context import SessionContext

    cid = "conv-clear"
    SessionContext(cid).set_outcome_evaluation({"score": 0.8, "success": True})
    # durability: a fresh context reads the persisted value (this is the learning loop)
    assert SessionContext(cid).get_outcome_evaluation() == {"score": 0.8, "success": True}

    SessionContext(cid).clear_outcome_evaluation()
    # a fresh context (restart) must now see None — the durable row was actually cleared
    assert SessionContext(cid).get_outcome_evaluation() is None

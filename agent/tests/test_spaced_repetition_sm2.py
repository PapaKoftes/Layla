"""BL-134: SM-2 spaced repetition — per-item state persists so intervals ACCUMULATE.

Before the fix, review_item() always reset ease/interval/reps to defaults, so the interval
never grew past the first step (effectively a fixed schedule). These tests lock in that the
state is now loaded + persisted and the interval grows on success / resets on failure.
"""
from __future__ import annotations


def _save(content: str) -> int:
    # Insert directly so the test is deterministic — save_learning() applies a quality gate
    # + rate limiter that would reject short synthetic content (returns -1). We only need a row.
    from layla.memory.db_connection import _conn
    from layla.memory.migrations import migrate
    from layla.time_utils import utcnow

    migrate()
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO learnings (content, type, created_at) VALUES (?, 'fact', ?)",
            (content, utcnow().isoformat()),
        )
        db.commit()
        return int(cur.lastrowid)


def test_sm2_pure_function_grows_and_resets():
    from services.memory.spaced_repetition import sm2

    ef, iv, reps = sm2(2.5, 0, 0, 5)      # first success
    assert (iv, reps) == (1, 1)
    ef, iv, reps = sm2(ef, iv, reps, 5)   # second success
    assert (iv, reps) == (6, 2)
    ef2, iv2, reps2 = sm2(ef, iv, reps, 5)  # third success → interval * ease
    assert iv2 > 6 and reps2 == 3
    ef3, iv3, reps3 = sm2(ef2, iv2, reps2, 1)  # failure → reset
    assert iv3 == 1 and reps3 == 0


def test_review_state_persists_and_accumulates():
    from layla.memory import db
    from services.memory.spaced_repetition import review_item

    lid = _save("SR accumulate: Kaffee = coffee")
    assert lid and lid > 0

    st0 = db.get_review_state(lid)
    assert st0["reps"] == 0 and st0["interval_days"] == 0  # never reviewed

    r1 = review_item(lid, 5)
    assert r1["new_reps"] == 1 and r1["new_interval_days"] == 1
    assert db.get_review_state(lid)["reps"] == 1            # persisted

    r2 = review_item(lid, 5)
    assert r2["prev_reps"] == 1                             # loaded prior state
    assert r2["new_reps"] == 2 and r2["new_interval_days"] == 6

    r3 = review_item(lid, 5)
    assert r3["new_reps"] == 3
    assert r3["new_interval_days"] > 6                      # ← genuine accumulation

    st3 = db.get_review_state(lid)
    assert st3["interval_days"] == r3["new_interval_days"]
    assert st3["ease"] >= 2.5                               # ease grew on all-passes


def test_review_failure_resets_interval():
    from layla.memory import db
    from services.memory.spaced_repetition import review_item

    lid = _save("SR reset: Hund = dog")
    review_item(lid, 5)
    review_item(lid, 5)
    review_item(lid, 5)                                     # interval now > 1
    assert db.get_review_state(lid)["interval_days"] > 1

    r = review_item(lid, 1)                                 # failed recall
    assert r["new_reps"] == 0 and r["new_interval_days"] == 1
    st = db.get_review_state(lid)
    assert st["reps"] == 0 and st["interval_days"] == 1     # persisted reset

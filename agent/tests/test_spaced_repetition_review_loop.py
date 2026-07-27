"""Plan #22 — SM-2 over learnings: the review LOOP + the two-into-one consolidation.

The algorithm was never wrong; the gap was that NOTHING graded due learnings, so their schedule never
advanced. get_learnings_due_for_review counts a NULL next_review_at as due, so an ungraded learning is
permanently due and the same items resurface forever. These tests pin three things:

  (a) the ONE canonical SM-2 (services.memory.spaced_repetition.sm2) advances interval/ease correctly
      for good vs poor grades;
  (b) the scheduled review loop (jobs._bg_spaced_repetition_review) moves next_review_at off NULL for a
      due learning and advances its interval — and grows it further on a second review;
  (c) the German flashcard deck and the learnings path now route through the SAME sm2 — proof there is
      one implementation, not three drifting copies.
"""
from __future__ import annotations

import pytest

from layla.memory.db import _conn, set_learning_importance
from layla.memory.learnings import save_learning
from layla.scheduler.jobs import _bg_spaced_repetition_review
from services.memory.spaced_repetition import self_grade_learning, sm2


# ── (a) the canonical algorithm, pinned ──────────────────────────────────────────────────────────────
class TestCanonicalSM2:
    def test_good_grades_grow_the_interval(self):
        """The standard SM-2 ladder: 1 → 6 → round(interval * ease), computed off the NEW ease."""
        ease, interval, reps = sm2(ease=2.5, interval_days=0, reps=0, quality=5)
        assert (interval, reps) == (1, 1)
        assert ease > 2.5, "a strong recall nudges the ease factor up"

        ease, interval, reps = sm2(ease=ease, interval_days=interval, reps=reps, quality=5)
        assert (interval, reps) == (6, 2)

        ease3, interval3, reps3 = sm2(ease=ease, interval_days=interval, reps=reps, quality=5)
        assert reps3 == 3
        assert interval3 > 6
        assert interval3 == int(round(6 * ease3)), (
            "the third interval must use the ease produced BY this review, not the stale prior ease"
        )

    def test_poor_grade_resets_and_drops_ease(self):
        ease, interval, reps = sm2(ease=2.5, interval_days=30, reps=5, quality=1)
        assert interval == 1, "a failed recall comes back tomorrow, not in a month"
        assert reps == 0, "the repetition streak resets on failure"
        assert ease < 2.5, "the ease factor drops on a failed recall"

    def test_ease_never_falls_below_the_1_3_floor(self):
        ease = 2.5
        for _ in range(30):
            ease, _i, _r = sm2(ease=ease, interval_days=1, reps=0, quality=0)
        assert ease >= 1.3, "below 1.3 the interval collapses and the item is shown forever"

    def test_quality_is_clamped(self):
        for q in (-9, 0, 3, 5, 42):
            ease, interval, reps = sm2(ease=2.5, interval_days=1, reps=1, quality=q)
            assert ease >= 1.3 and interval >= 1 and reps >= 0

    def test_self_grade_is_deterministic_and_bounded(self):
        # Strong + fresh → high grade; weak → low; heavy staleness knocks a strong item down.
        assert self_grade_learning(importance=0.95, confidence=0.95, age_days=0) == 5
        assert self_grade_learning(importance=0.05, confidence=0.05, age_days=0) == 1
        assert self_grade_learning(importance=0.95, age_days=400) < 5
        for imp in (None, -1.0, 0.0, 0.5, 1.0, 2.0):
            assert 0 <= self_grade_learning(importance=imp) <= 5


# ── (b) the review loop actually schedules due learnings ─────────────────────────────────────────────
def test_review_loop_moves_next_review_off_null_and_advances_interval(isolated_db):
    lid = save_learning(
        "The operator prefers four-space indentation and never tabs in Python source files.",
        kind="fact",
        confidence=0.85,
        score=1.0,
    )
    assert lid and lid > 0
    set_learning_importance(lid, 0.9)  # high importance → strong deterministic self-grade

    # Precondition: never scheduled → next_review_at NULL (which is exactly why it is "due").
    with _conn() as db:
        before = db.execute(
            "SELECT next_review_at, review_interval_days, review_reps FROM learnings WHERE id=?", (lid,)
        ).fetchone()
    assert before["next_review_at"] is None
    assert (before["review_interval_days"] or 0) == 0

    _bg_spaced_repetition_review()

    with _conn() as db:
        after = db.execute(
            "SELECT next_review_at, review_interval_days, review_reps FROM learnings WHERE id=?", (lid,)
        ).fetchone()
    assert after["next_review_at"] is not None, "the review loop must move next_review_at off NULL"
    assert after["review_interval_days"] >= 1, "a graded item's interval must advance past 0"
    assert after["review_reps"] == 1

    # Force it due again and re-grade: the interval must GROW — repetition WITH spacing.
    with _conn() as db:
        db.execute("UPDATE learnings SET next_review_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", lid))
        db.commit()
    _bg_spaced_repetition_review()

    with _conn() as db:
        grown = db.execute(
            "SELECT review_interval_days, review_reps FROM learnings WHERE id=?", (lid,)
        ).fetchone()
    assert grown["review_interval_days"] > after["review_interval_days"], (
        "a second successful review must push the next review further out"
    )
    assert grown["review_reps"] == 2


def test_review_loop_is_a_noop_when_nothing_is_due(isolated_db):
    # Empty DB → no due learnings → the loop must run cleanly and touch nothing.
    _bg_spaced_repetition_review()
    with _conn() as db:
        cnt = db.execute("SELECT COUNT(*) AS c FROM learnings").fetchone()["c"]
    assert cnt == 0


# ── (c) consolidation proof: one implementation, both paths ──────────────────────────────────────────
def test_german_deck_and_learnings_share_one_sm2(monkeypatch):
    """Both remaining `_sm2` shims must delegate to the ONE canonical sm2 — not re-implement it."""
    import services.memory.spaced_repetition as sr
    from layla.tools.impl import memory as tools_memory
    from services.infrastructure import german_mode

    calls: list[dict] = []
    real = sr.sm2

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(sr, "sm2", spy)

    # german_mode._sm2(ease_factor, interval, reps, quality); tools._sm2(quality, ease, interval, reps).
    german_result = german_mode._sm2(2.5, 6, 2, 5)
    learnings_result = tools_memory._sm2(5, 2.5, 6, 2)

    assert len(calls) == 2, "both the flashcard deck and the learnings path must call the one canonical sm2"
    assert german_result == learnings_result == real(ease=2.5, interval_days=6, reps=2, quality=5), (
        "identical logical inputs must yield identical schedules — proof of a single shared implementation"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))

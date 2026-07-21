"""Phase 13 criterion 5 (SRS): spaced repetition had no spacing.

`spaced_repetition_review`'s REGISTERED DESCRIPTION has always read "Review a learning with a quality
score (0-5) and schedule the next review via SM-2." The implementation took no quality score and
scheduled nothing — it listed due items and returned. So the model was told the tool did SM-2, called
it, and nothing was ever written back.

That is worse than a missing feature because of how "due" is defined. get_learnings_due_for_review
returns rows where `next_review_at <= now OR next_review_at IS NULL`. With nothing ever scheduled,
every row is NULL, so EVERY learning is permanently due and the same items resurface forever.
Measured on the live DB: 28 learnings, next_review_at non-null on 0 of them.

`set_review_state` — which persists ease/interval/reps and computes the next date — already existed,
fully written, with zero callers. The gap was one function call, not an algorithm.

The operator chose WIRE over delete for this subsystem (2026-07-21).
"""
from __future__ import annotations

import pytest

from layla.tools.impl.memory import _sm2, spaced_repetition_review


class TestSM2Maths:
    def test_a_failed_recall_resets_to_tomorrow(self):
        ease, interval, reps = _sm2(2, 2.5, 30, 5)
        assert interval == 1, "a forgotten item must come back tomorrow, not in a month"
        assert reps == 0, "the repetition streak resets on failure"
        assert ease < 2.5, "ease drops when recall fails"

    def test_intervals_grow_on_success(self):
        """1 → 6 → interval*ease is the standard SM-2 ladder."""
        ease, i1, r1 = _sm2(5, 2.5, 0, 0)
        assert (i1, r1) == (1, 1)
        ease, i2, r2 = _sm2(5, ease, i1, r1)
        assert (i2, r2) == (6, 2)
        ease, i3, r3 = _sm2(5, ease, i2, r2)
        assert i3 > i2, "the third review must be further out than the second"
        assert r3 == 3

    def test_ease_never_falls_below_the_floor(self):
        """Below 1.3 the interval collapses and the item is shown forever — the bug being fixed."""
        ease = 2.5
        for _ in range(20):
            ease, _i, _r = _sm2(0, ease, 1, 0)
        assert ease >= 1.3

    @pytest.mark.parametrize("q", [-5, 0, 3, 5, 99])
    def test_out_of_range_quality_is_clamped(self, q):
        ease, interval, reps = _sm2(q, 2.5, 1, 1)
        assert ease >= 1.3 and interval >= 1 and reps >= 0


class TestGradingIsActuallyPersisted:
    """The half that did not exist. Without this, nothing is ever scheduled."""

    def test_grading_writes_review_state(self, monkeypatch):
        written = {}
        monkeypatch.setattr("layla.memory.db.get_review_state", lambda lid: {})
        monkeypatch.setattr(
            "layla.memory.db.set_review_state",
            lambda lid, *, ease, interval_days, reps: written.update(
                lid=lid, ease=ease, interval_days=interval_days, reps=reps
            ),
        )
        out = spaced_repetition_review(learning_id=7, quality=5)
        assert out["ok"] is True
        assert written.get("lid") == 7, (
            "grading did not reach set_review_state — next_review_at stays NULL and the item is "
            "permanently due, which is exactly the shipped bug"
        )
        assert written["reps"] == 1 and written["interval_days"] == 1

    def test_repeated_success_pushes_the_item_further_out(self, monkeypatch):
        state = {"review_ease": 2.5, "review_interval_days": 0, "review_reps": 0}
        monkeypatch.setattr("layla.memory.db.get_review_state", lambda lid: dict(state))
        monkeypatch.setattr(
            "layla.memory.db.set_review_state",
            lambda lid, *, ease, interval_days, reps: state.update(
                review_ease=ease, review_interval_days=interval_days, review_reps=reps
            ),
        )
        seen = []
        for _ in range(3):
            spaced_repetition_review(learning_id=1, quality=5)
            seen.append(state["review_interval_days"])
        assert seen == sorted(seen) and seen[-1] > seen[0], (
            f"intervals did not grow across reviews ({seen}) — that is repetition without spacing"
        )

    def test_listing_still_works_without_a_grade(self, monkeypatch):
        monkeypatch.setattr(
            "layla.memory.db.get_learnings_due_for_review",
            lambda limit: [{"id": 1, "content": "x", "importance_score": 0.5}],
        )
        out = spaced_repetition_review(limit=5)
        assert out["ok"] is True and out["due_count"] == 1

    def test_a_db_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(
            "layla.memory.db.get_review_state",
            lambda lid: (_ for _ in ()).throw(RuntimeError("db gone")),
        )
        out = spaced_repetition_review(learning_id=1, quality=4)
        assert out["ok"] is False and "error" in out


def test_the_tool_description_matches_what_it_does():
    """The defect was a contract mismatch: the description promised SM-2 grading, the code listed rows."""
    from layla.tools.domains.memory import TOOLS as MEM_TOOLS
    import inspect

    desc = MEM_TOOLS["spaced_repetition_review"]["description"].lower()
    assert "quality" in desc and "sm-2" in desc, "description drifted from the promised contract"
    sig = inspect.signature(spaced_repetition_review).parameters
    assert "quality" in sig and "learning_id" in sig, (
        "the tool is registered as accepting a quality score but its signature cannot take one — "
        "the model would call it as described and silently schedule nothing"
    )

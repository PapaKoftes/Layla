"""Phase 13 criterion 1: the learning pipeline must run on a NORMAL turn.

A normal turn is a streamed one — the UI ships streaming ON by default. And a streamed turn was
never evaluated. `reasoning_handler` sets `status="stream_pending"` and returns BEFORE the answer
exists, `run_finalizer` gates every piece of its learning work on `status == "finished"`, so on the
default path the gate simply never opened.

The evidence was in the operator's own database: outcome_evaluations stopped at 2026-07-16 while
tool executions continued through 2026-07-19, and all 101 stored rows are reply-only finishes from
the non-streamed path.

commit_turn is the right seam because it is the TURN BOUNDARY — it runs on both paths, and the
streamed done-frame hands it the run state together with the finished answer, the first moment both
exist at once. Two neighbours (the mood nudge, learning extraction) were migrated here previously
for exactly this reason; outcome evaluation was left behind.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.agent import turn_commit


@pytest.fixture
def captured(monkeypatch):
    """Silence persistence; capture what the evaluation produced."""
    seen: dict = {}

    class _Session:
        def set_outcome_evaluation(self, ev):
            seen["persisted"] = ev

    monkeypatch.setattr(turn_commit, "_persist_turn", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(
        "services.infrastructure.session_context.get_or_create_session",
        lambda cid: _Session(),
    )
    return seen


def _streamed_state(**over) -> dict:
    """What the streamed done-frame actually hands commit_turn: real steps, stale status."""
    st = {
        "status": "stream_pending",   # <- the orchestrator returned before the answer existed
        "conversation_id": "c1",
        "original_goal": "read the config and summarise it",
        "steps": [{"action": "read_file", "args": {"path": "x"}, "result": {"ok": True}}],
    }
    st.update(over)
    return st


class TestStreamedTurnGetsEvaluated:
    def test_a_streamed_turn_is_evaluated_at_the_turn_boundary(self, captured):
        state = _streamed_state()
        turn_commit.commit_turn(
            "c1", "read the config and summarise it", "here is the summary",
            aspect_id="morrigan", status="finished", state=state,
        )
        ev = state.get("outcome_evaluation")
        assert ev, (
            "a streamed turn produced no outcome evaluation — this is the default UI path, so the "
            "learning pipeline is dead for normal use"
        )
        assert captured.get("persisted"), "the evaluation must be persisted, not just computed"

    def test_the_stale_stream_pending_status_is_resolved_before_scoring(self, captured):
        """The subtle half. evaluate_outcome scores `finished = status == 'finished'`.

        Evaluating against the stale 'stream_pending' would score EVERY streamed turn 0.35 and teach
        the feedback loop that ordinary successful use is failure — worse than not evaluating at all.
        """
        state = _streamed_state()
        turn_commit.commit_turn(
            "c1", "read the config", "done", aspect_id="morrigan", status="finished", state=state,
        )
        ev = state["outcome_evaluation"]
        assert ev.get("score", 0) > 0.5, (
            f"streamed turn scored {ev.get('score')} — it was scored as unfinished, which is the "
            "stale-status bug rather than a genuine low score"
        )

    @pytest.mark.parametrize("terminal", ["timeout", "tool_limit", "system_busy"])
    def test_a_real_terminal_status_is_never_overwritten(self, captured, terminal):
        """Regression: the first version of this fix clobbered the run's own terminal status.

        `state["status"]` is a fact about the run. The router maps it to the text explaining WHY a
        turn stopped ("took too long", "hit maximum tool calls"). Rewriting it to "finished" so the
        evaluator scores well silently removes that explanation. Only the stream_pending placeholder
        is a stand-in awaiting resolution; everything else is an answer.
        """
        state = _streamed_state(status=terminal)
        turn_commit.commit_turn(
            "c1", "goal", "text", aspect_id="morrigan", status="finished", state=state,
        )
        assert state["status"] == terminal, (
            f"the run ended in {terminal!r} and commit_turn rewrote it — the user loses the "
            "explanation for why their turn stopped"
        )

    def test_a_tool_using_streamed_turn_is_not_recorded_as_reply_only(self, captured):
        """All 101 stored evaluations say 'no_tool_steps: reply-only finish'. Tool steps must count."""
        state = _streamed_state()
        turn_commit.commit_turn(
            "c1", "read the config", "done", aspect_id="morrigan", status="finished", state=state,
        )
        ev = state["outcome_evaluation"]
        issues = " ".join(str(i) for i in (ev.get("issues") or []))
        assert "no_tool_steps" not in issues, (
            "a turn with a real read_file step was scored as a reply-only finish"
        )


class TestIdempotenceAndSafety:
    def test_an_existing_evaluation_is_never_recomputed(self, captured):
        """The non-streamed path is already evaluated by run_finalizer — do not double-count."""
        sentinel = {"score": 0.99, "success": True, "issues": ["ORIGINAL"]}
        state = _streamed_state(status="finished", outcome_evaluation=sentinel)
        turn_commit.commit_turn(
            "c1", "goal", "text", aspect_id="morrigan", status="finished", state=state,
        )
        assert state["outcome_evaluation"] is sentinel, (
            "run_finalizer's evaluation was overwritten — that double-counts the non-streamed path"
        )
        assert "persisted" not in captured, "an already-evaluated turn must not re-persist"

    def test_stateless_fast_paths_do_not_crash(self, captured):
        """Fast paths never call agent_loop and pass state=None. They must still commit."""
        turn_commit.commit_turn(
            "c1", "hello", "hi there", aspect_id="morrigan", status="finished", state=None,
        )  # must not raise

    def test_evaluation_failure_never_breaks_the_turn(self, captured, monkeypatch):
        """Learning is best-effort; a broken evaluator must not cost the user their reply."""
        monkeypatch.setattr(
            "services.infrastructure.outcome_evaluation.evaluate_outcome_structured",
            lambda s: (_ for _ in ()).throw(RuntimeError("evaluator exploded")),
        )
        state = _streamed_state()
        turn_commit.commit_turn(
            "c1", "goal", "text", aspect_id="morrigan", status="finished", state=state,
        )  # must not raise

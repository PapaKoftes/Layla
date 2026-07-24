"""`deliberation_mode: "auto"` must actually mean something — without bypassing tools.

"auto" is the schema default, yet both callers pinned it solo-equivalent, so the shipped default
was single-voice whatever the schema said. The pin was CORRECT at the time: the previous behaviour
escalated every non-solo turn, and `debate_engine` dispatches no tools and consults no approval
gate (grep it: not one "tool" reference), so a routed turn silently lost tool capability and the
approval floor.

`should_auto_deliberate` is the decision the stop-gap was waiting for. These tests pin BOTH halves:
it escalates when deliberating is useful, and it refuses when escalating would throw away a tool
result. The second half is the safety property — if it ever regresses, a turn that read your files
would answer from six opinions and none of the file contents.
"""
from __future__ import annotations

import pytest

from services.planning.debate_engine import (
    MODE_SOLO,
    should_auto_deliberate,
)


class TestItEscalatesWhenDeliberationIsAskedFor:
    def test_an_opinion_request_escalates(self):
        mode = should_auto_deliberate("what do you think about rewriting this in Rust?", None, {})
        assert mode != MODE_SOLO, (
            "a turn that explicitly asks for judgement stayed solo — 'auto' is still pinned and the "
            "feature is off by default no matter what the schema says"
        )

    def test_the_resolved_mode_is_a_real_mode(self):
        mode = should_auto_deliberate("what do you think about rewriting this in Rust?", None, {})
        assert mode in ("debate", "council", "tribunal"), f"resolved to a bogus mode: {mode!r}"


class TestItRefusesWhenEscalatingWouldLoseWork:
    """THE SAFETY HALF. debate_engine implements no tools, so replacing the answer on a turn that
    already ran one discards what that tool found."""

    @pytest.mark.parametrize("action", ["read_file", "grep_code", "shell", "write_file"])
    def test_a_turn_that_ran_a_tool_stays_solo(self, action):
        state = {"steps": [{"action": action, "result": "the file said X"}]}
        assert should_auto_deliberate("what do you think of this file?", state, {}) == MODE_SOLO, (
            f"a turn that ran {action!r} was routed to the tool-less debate engine — its result "
            "would be silently dropped from the answer"
        )

    def test_reasoning_only_steps_do_not_count_as_tool_use(self):
        """think/reason steps are not tool calls; they must not block deliberation."""
        state = {"steps": [{"action": "think", "result": ""}, {"action": "reason", "result": "hm"}]}
        assert should_auto_deliberate("what should i do here?", state, {}) != MODE_SOLO


class TestItIsNotFooledByLength:
    def test_a_long_factual_question_does_not_trigger_six_opinions(self):
        """`select_deliberation_mode` falls back to WORD COUNT, which fires on any long question.
        Auto must key on intent: 'explain this 90-word traceback' is not a request to debate."""
        long_factual = "explain " + " ".join(f"line{i}" for i in range(90)) + " in this traceback"
        assert should_auto_deliberate(long_factual, None, {}) == MODE_SOLO, (
            "length alone escalated a factual question — on a CPU box that turns a slow answer "
            "into several slow answers for no benefit"
        )

    def test_empty_goal_stays_solo(self):
        assert should_auto_deliberate("", None, {}) == MODE_SOLO
        assert should_auto_deliberate(None, None, {}) == MODE_SOLO


def test_the_streaming_path_defaults_to_not_vouching_for_tool_freedom():
    """stream_handler passes state={} and cannot see whether tools ran, so `tool_free` must default
    False — only a caller that KNOWS may opt in. A True default would reintroduce the exact bypass."""
    import inspect

    from services.agent import stream_handler

    for fn in (stream_handler.stream_reason, stream_handler._stream_reason_body):
        sig = inspect.signature(fn)
        assert "tool_free" in sig.parameters, f"{fn.__name__} lost the tool_free signal"
        assert sig.parameters["tool_free"].default is False, (
            f"{fn.__name__} defaults tool_free True — every streamed turn would claim to be "
            "tool-free and could be hijacked by the tool-less debate engine"
        )

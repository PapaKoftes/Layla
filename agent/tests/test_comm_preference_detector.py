"""Communication-preference detector + its wiring into run_finalizer.

learn_communication_preference() had zero callers, so get_evolved_hints' entire
communication-preference branch was dead. detect_comm_preferences is the high-precision signal
source that now feeds it (from run_finalizer, per turn). These tests pin that it fires ONLY on
explicit operator cues — never inferring from message length — and that run_finalizer actually
calls learn_communication_preference with what it detects.
"""
from __future__ import annotations

from services.personality.evolution import detect_comm_preferences


def test_explicit_short_cue_maps_to_low_response_length():
    prefs = dict(detect_comm_preferences("Please be concise and just give me the answer."))
    assert prefs.get("response_length") == 0.15


def test_explicit_detail_cue_maps_to_high_response_length():
    prefs = dict(detect_comm_preferences("Walk me through it step by step, in detail."))
    assert prefs.get("response_length") == 0.85


def test_eli5_maps_to_low_technical_depth():
    prefs = dict(detect_comm_preferences("eli5 how does TLS work"))
    assert prefs.get("technical_depth") == 0.15


def test_under_the_hood_maps_to_high_technical_depth():
    prefs = dict(detect_comm_preferences("show me what happens under the hood"))
    assert prefs.get("technical_depth") == 0.85


def test_no_cue_returns_nothing():
    # A long, detailed message must NOT be read as "wants detail" — only explicit cues count.
    assert detect_comm_preferences(
        "Here is a very long message about my project with lots of context and background "
        "that goes on for a while but never states a preference about how I want replies."
    ) == []
    assert detect_comm_preferences("what is the capital of France") == []
    assert detect_comm_preferences("") == []


def test_at_most_one_pair_per_type():
    # Two response_length cues in one message → still a single response_length pair.
    prefs = detect_comm_preferences("be concise, keep it short, one sentence")
    types = [p for p, _ in prefs]
    assert types.count("response_length") == 1


def test_run_finalizer_calls_learn_communication_preference(monkeypatch):
    """The wiring: run_finalizer must feed detected cues into learn_communication_preference."""
    from services.agent.run_finalizer import finalize_run_state
    from services.personality import evolution as _evo_mod

    calls: list = []

    class _FakeEvo:
        def record_interaction(self, *a, **k):
            return None

        def learn_communication_preference(self, aspect_id, ptype, value):
            calls.append((aspect_id, ptype, value))

    monkeypatch.setattr(_evo_mod, "get_personality_evolution", lambda: _FakeEvo())

    class _RS:
        @staticmethod
        def load_config():
            return {}

    def noop(*a, **k):
        return None

    state = {"status": "finished", "steps": [], "tools_used": []}
    finalize_run_state(
        state,
        {"id": "morrigan"},
        "please be concise",  # goal carries the explicit cue
        None,
        False,
        noop,
        inject_cancel_message_fn=noop,
        save_outcome_memory_fn=noop,
        set_effective_sandbox_fn=noop,
        runtime_safety_module=_RS,
    )
    assert ("morrigan", "response_length", 0.15) in calls

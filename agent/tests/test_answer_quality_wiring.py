"""A1 (BL-100/BL-102): finalize_run_state attaches answer_quality when grounding is enabled."""
from __future__ import annotations

import pytest


def _run_finalize(cfg, monkeypatch, answer="Layla runs fully local on CPU with llama.cpp."):
    from services.agent.run_finalizer import finalize_run_state

    # supporting passage so grounding resolves to grounded (not abstain)
    monkeypatch.setattr(
        "layla.memory.vector_store.get_knowledge_chunks_with_sources",
        lambda query, k=5, aspect_id="": [{"text": answer, "source": "docs/arch.md"}],
        raising=False,
    )

    class _RS:
        @staticmethod
        def load_config():
            return cfg

    state = {
        "status": "finished",
        "steps": [{"action": "reason", "result": answer}],
        "original_goal": "how does layla run",
        "conversation_id": "",
    }
    def noop(*a, **k):
        return None
    finalize_run_state(
        state,
        {"id": "morrigan"},
        "how does layla run",
        None,
        False,
        noop,
        inject_cancel_message_fn=noop,
        # `auto_extract_learnings_fn` is gone (BL-338): learning extraction moved out of the
        # finalizer to services/agent/turn_commit.commit_turn, which fires on the turn boundary
        # instead of on `status == "finished"`.
        save_outcome_memory_fn=noop,
        set_effective_sandbox_fn=noop,
        runtime_safety_module=_RS,
    )
    return state


def test_answer_quality_attached_when_grounding_enabled(monkeypatch):
    state = _run_finalize({"grounding_enabled": True, "grounding_mode": "flag"}, monkeypatch)
    aq = state.get("answer_quality")
    assert aq is not None, "answer_quality must be attached when grounding is on"
    assert aq["grounding"]["enabled"] is True
    assert "confidence" in aq and "abstain" in aq


def test_answer_quality_absent_when_disabled(monkeypatch):
    state = _run_finalize({}, monkeypatch)  # both features off
    assert state.get("answer_quality") is None  # inert by default — no metadata, no mutation


def test_answer_text_never_mutated(monkeypatch):
    ans = "Layla runs fully local on CPU with llama.cpp."
    state = _run_finalize({"grounding_enabled": True, "grounding_mode": "flag"}, monkeypatch, answer=ans)
    # the reason step's result (the answer) is unchanged — assessment is metadata only
    assert state["steps"][0]["result"] == ans

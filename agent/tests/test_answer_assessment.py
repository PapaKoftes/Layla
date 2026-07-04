"""BL-100+BL-102: combined answer assessment — grounding + escalation in one gated call."""
from __future__ import annotations

from services.llm.answer_assessment import assess_answer


def test_noop_when_both_disabled():
    out = assess_answer("Any answer.", "q", {})
    assert out["grounding"]["enabled"] is False
    assert out["confidence"] == 1.0 and out["escalate"] is False and out["abstain"] is False


def test_grounding_runs_when_enabled(monkeypatch):
    # Stub retrieval so we don't need a live vector store; provide a supporting passage.
    import services.retrieval.grounding as gmod
    monkeypatch.setattr(
        "layla.memory.vector_store.get_knowledge_chunks_with_sources",
        lambda query, k=5, aspect_id="": [{"text": "Layla runs fully local on CPU.", "source": "docs/arch.md"}],
        raising=False,
    )
    out = assess_answer("Layla runs fully local on CPU.", "how does layla run",
                        {"grounding_enabled": True, "grounding_mode": "flag"})
    assert out["grounding"]["enabled"] is True
    assert out["grounding"]["overall"] == 1.0
    assert out["grounding"]["claims"][0]["source"] == "docs/arch.md"   # real citation


def test_escalation_fires_on_low_confidence():
    cfg = {"hybrid_escalation_enabled": True, "escalation_model": "big.gguf", "escalation_confidence_threshold": 0.5}
    out = assess_answer("I don't know, I'm not sure at all.", "q", cfg, current_model="small.gguf")
    assert out["escalate"] is True and out["escalation_model"] == "big.gguf"
    assert out["confidence"] < 0.5


def test_grounding_drives_escalation(monkeypatch):
    # Grounding finds no support (empty retrieval) → low confidence → escalate.
    monkeypatch.setattr(
        "layla.memory.vector_store.get_knowledge_chunks_with_sources",
        lambda query, k=5, aspect_id="": [],
        raising=False,
    )
    cfg = {
        "grounding_enabled": True, "grounding_mode": "flag",
        "hybrid_escalation_enabled": True, "escalation_model": "big.gguf",
    }
    out = assess_answer("The exact population is 8,013,442 as of this morning.", "population?", cfg, current_model="small.gguf")
    assert out["grounding"]["unsupported"]        # nothing supports it
    assert out["escalate"] is True                # ungrounded → escalate

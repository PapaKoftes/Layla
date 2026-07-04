"""BL-102 / UPG-01: hybrid escalation decision — confidence heuristics + escalate gate."""
from __future__ import annotations

from services.llm import hybrid_escalation as he

_ON = {"hybrid_escalation_enabled": True, "escalation_model": "big-model.gguf", "escalation_confidence_threshold": 0.5}


def test_confident_answer_scores_high():
    assert he.answer_confidence("The capital of France is Paris.") >= 0.9


def test_hedging_lowers_confidence():
    c = he.answer_confidence("I think it might be around 42, but I'm not sure and could be wrong.")
    assert c < 0.5


def test_abstain_is_low_confidence():
    assert he.answer_confidence("I don't know the answer to that.") <= 0.2


def test_bare_fragment_is_low():
    assert he.answer_confidence("Maybe.") < 0.6


def test_grounding_unsupported_lowers_confidence():
    g = {"enabled": True, "overall": 0.0, "unsupported": [{"claim": "x", "score": 0.0}]}
    high_text = "This is a clear, well-formed declarative statement of fact."
    assert he.answer_confidence(high_text) >= 0.9                     # no grounding → high
    assert he.answer_confidence(high_text, grounding=g) <= 0.25       # unsupported → low


def test_should_escalate_gated_off_by_default():
    assert he.should_escalate("I don't know.", {}) is False           # feature disabled
    assert he.should_escalate("I don't know.", {"hybrid_escalation_enabled": True}) is False  # no target model


def test_should_escalate_fires_on_low_confidence():
    assert he.should_escalate("I don't know, hard to say, I'm not sure.", _ON) is True


def test_no_escalate_on_confident_answer():
    assert he.should_escalate("The capital of France is Paris, a well-known fact.", _ON) is False


def test_no_escalate_when_target_equals_current():
    # Escalating to the same model you're already on is pointless.
    assert he.should_escalate("I don't know.", _ON, current_model="big-model.gguf") is False


def test_escalation_decision_record():
    d = he.escalation_decision("I'm not sure, possibly.", _ON)
    assert d["escalate"] is True
    assert d["escalation_model"] == "big-model.gguf"
    assert d["confidence"] < d["threshold"]

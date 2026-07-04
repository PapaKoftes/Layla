"""BL-100 / REQ-30: inline RAG grounding — claim splitting, support scoring, cite-or-abstain."""
from __future__ import annotations

from services.retrieval import grounding as g

_ON = {"grounding_enabled": True, "grounding_mode": "flag"}
_ABSTAIN = {"grounding_enabled": True, "grounding_mode": "abstain"}


def test_split_claims_skips_nonassertions():
    ans = "Paris is the capital of France. What is the capital of Italy? See `code_here`. Ok."
    claims = g.split_claims(ans)
    assert any("capital of France" in c for c in claims)
    assert not any(c.endswith("?") for c in claims)       # question dropped
    assert not any("Ok" == c for c in claims)             # too short dropped


def test_split_claims_drops_code_fences():
    ans = "The function sorts input.\n```python\nprint('secret hallucination')\n```\nIt returns a list."
    claims = g.split_claims(ans)
    joined = " ".join(claims)
    assert "hallucination" not in joined                  # fenced code isn't a claim
    assert "sorts input" in joined and "returns a list" in joined


def test_lexical_scorer_full_and_zero_support():
    passages = ["France is a country in Europe; the capital of France is Paris, a large city."]
    s_full, idx = g.lexical_scorer("The capital of France is Paris.", passages)
    assert s_full >= 0.9 and idx == 0
    s_zero, _ = g.lexical_scorer("The moon is made of green cheese.", passages)
    assert s_zero == 0.0


def test_disabled_returns_inert_block():
    out = g.check_grounding("Anything.", ["ctx"], {"grounding_enabled": False})
    assert out["enabled"] is False and out["overall"] == 1.0 and out["abstain"] is False


def test_supported_answer_scores_high():
    passages = ["Layla runs fully local. The default model is a GGUF loaded via llama.cpp on CPU."]
    ans = "Layla runs fully local. The default model is a GGUF loaded via llama.cpp."
    out = g.check_grounding(ans, passages, _ON)
    assert out["enabled"] is True
    assert out["overall"] == 1.0 and not out["unsupported"]
    assert all(c["supported"] for c in out["claims"])
    assert out["claims"][0]["source"] == 0                # cites the passage


def test_hallucinated_claim_is_flagged():
    passages = ["Layla runs fully local with a GGUF model on CPU."]
    ans = "Layla runs fully local. Layla was founded by Napoleon in 1804."
    out = g.check_grounding(ans, passages, _ON)
    assert out["supported"] == 1
    assert len(out["unsupported"]) == 1
    assert "Napoleon" in out["unsupported"][0]["claim"]
    assert out["abstain"] is False                        # flag mode doesn't abstain


def test_abstain_mode_triggers_on_unsupported():
    out = g.check_grounding(
        "The API rate limit is exactly 9000 requests per second.",
        ["The service is local and has no documented rate limit."],
        _ABSTAIN,
    )
    assert out["abstain"] is True and g.should_abstain(out)


def test_empty_context_makes_claims_unsupported():
    out = g.check_grounding("Concrete factual assertion about specifics.", [], _ON)
    assert out["overall"] == 0.0 and len(out["unsupported"]) >= 1


def test_no_groundable_claims_does_not_abstain():
    # Pure questions / greetings → nothing to ground → overall 1.0, never abstains.
    out = g.check_grounding("Hi there! How are you doing today?", ["ctx"], _ABSTAIN)
    assert out["overall"] == 1.0 and out["abstain"] is False


def test_pluggable_nli_scorer_is_used():
    # Simulate an entailment model that fully supports everything.
    g.set_scorer(lambda claim, passages: (1.0, 0) if passages else (0.0, -1))
    try:
        out = g.check_grounding("Any claim at all here.", ["some passage"], _ON)
        assert out["overall"] == 1.0 and not out["unsupported"]
    finally:
        g.reset_scorer()
    # After reset, the lexical scorer is back (unsupported for unrelated ctx).
    out2 = g.check_grounding("Totally unrelated specific assertion.", ["some passage"], _ON)
    assert out2["unsupported"]

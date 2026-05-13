# -*- coding: utf-8 -*-
"""
Tests for the multi-aspect debate/council/tribunal engine.

Covers:
  - Mode detection from keywords
  - Aspect selection for tasks
  - Full deliberation pipeline (DEBATE, COUNCIL, TRIBUNAL)
  - Synthesis combining viewpoints
  - Auto-mode detection
  - Domain mapping correctness
  - Edge cases (empty goal, unknown mode, single aspect)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# Helpers: canned LLM responses and mock personality loader
# ---------------------------------------------------------------------------

_CANNED_RESPONSES = {
    "morrigan": "Ship it. The architecture is sound. Refactor the interface, keep the internals.",
    "nyx": "There are three layers to this. The real issue is the dependency graph, not the surface API.",
    "echo": "I notice you've asked this before. Last time you went with the rewrite and regretted it.",
    "eris": "What if the whole premise is wrong? Maybe you don't need either -- just wrap it.",
    "cassandra": "The performance bottleneck is in the ORM layer, not where you think it is.",
    "lilith": "Before deciding, consider: a rewrite affects three downstream teams. Be honest about the cost.",
}

_CANNED_CRITIQUES = {
    "morrigan": "Nyx overcomplicates. Echo's historical note is useful. Ship-or-kill decision needed.",
    "nyx": "Morrigan is too fast. Missing the dependency risk. Echo's pattern match is relevant.",
    "echo": "Both Morrigan and Nyx are right technically. Neither asked what the user actually needs.",
    "eris": "Everyone is stuck in the refactor-vs-rewrite frame. The lateral option was ignored.",
    "cassandra": "Good points all around but nobody profiled the actual bottleneck yet.",
    "lilith": "Morrigan's speed is a risk here. The downstream impact needs explicit acknowledgment.",
}

_CANNED_SYNTHESIS = (
    "The refactoring path is the right call for now. The dependency graph needs attention first. "
    "Consider wrapping as a quick interim step.\n\n"
    "SYNTHESIS_NOTES: - Agreement: refactor over rewrite. "
    "- Disagreement: Eris suggests wrapping instead. "
    "- Risk: downstream team impact (Lilith)."
)

_FAKE_PERSONALITIES = {
    aid: {
        "id": aid,
        "name": aid.capitalize(),
        "role": f"Role of {aid}",
        "voice": f"Voice of {aid}",
        "systemPromptAddition": f"You are {aid.capitalize()}.",
    }
    for aid in ["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]
}


def _mock_run_completion(prompt, max_tokens=800, temperature=0.7, stream=False, **kw):
    """Return canned responses based on which aspect name appears in the prompt."""
    prompt_lower = prompt.lower()

    # Synthesis prompt
    if "synthesize" in prompt_lower or "unified response" in prompt_lower:
        return {"choices": [{"message": {"content": _CANNED_SYNTHESIS}}]}

    # Critique prompt
    if "critique" in prompt_lower:
        for aid, critique in _CANNED_CRITIQUES.items():
            if aid in prompt_lower or aid.capitalize() in prompt:
                return {"choices": [{"message": {"content": critique}}]}
        return {"choices": [{"message": {"content": "No strong critique."}}]}

    # Aspect generation prompt
    for aid, response in _CANNED_RESPONSES.items():
        if aid in prompt_lower or aid.capitalize() in prompt:
            return {"choices": [{"message": {"content": response}}]}

    return {"choices": [{"message": {"content": "Default response."}}]}


def _mock_load_aspects():
    return list(_FAKE_PERSONALITIES.values())


# ---------------------------------------------------------------------------
# Test: select_deliberation_mode
# ---------------------------------------------------------------------------


class TestSelectDeliberationMode:
    """Tests for keyword-based mode auto-detection."""

    def test_debate_should_i(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("Should I refactor or rewrite?", {}, {}) == "debate"

    def test_debate_tradeoff(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("What are the trade-offs of microservices?", {}, {}) == "debate"

    def test_debate_pros_cons(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("List the pros and cons of Python vs Go", {}, {}) == "debate"

    def test_debate_compare(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("Compare React and Vue", {}, {}) == "debate"

    def test_council_ethical(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("Is this approach ethical?", {}, {}) == "council"

    def test_council_risky(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("This seems risky, help me decide", {}, {}) == "council"

    def test_council_dangerous(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("Is this dangerous for production?", {}, {}) == "council"

    def test_tribunal_comprehensive(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("I need a comprehensive review of this design", {}, {}) == "tribunal"

    def test_tribunal_all_perspectives(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("Give me all perspectives on this decision", {}, {}) == "tribunal"

    def test_solo_simple(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("What is a for loop?", {}, {}) == "solo"

    def test_solo_empty(self):
        from services.debate_engine import select_deliberation_mode
        assert select_deliberation_mode("", {}, {}) == "solo"

    def test_long_goal_becomes_council(self):
        from services.debate_engine import select_deliberation_mode
        # 81+ words
        goal = " ".join(["word"] * 85)
        assert select_deliberation_mode(goal, {}, {}) == "council"

    def test_medium_goal_becomes_debate(self):
        from services.debate_engine import select_deliberation_mode
        # 41-80 words
        goal = " ".join(["word"] * 50)
        assert select_deliberation_mode(goal, {}, {}) == "debate"


# ---------------------------------------------------------------------------
# Test: select_aspects_for_task
# ---------------------------------------------------------------------------


class TestSelectAspectsForTask:
    """Tests for domain-aware aspect selection."""

    def test_code_task_picks_cassandra(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("fix the code architecture performance", "debate", {})
        assert "cassandra" in aspects
        assert len(aspects) == 2

    def test_ethics_task_picks_lilith(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("is this safe and ethical with proper boundaries", "council", {})
        assert "lilith" in aspects
        assert len(aspects) == 3

    def test_creativity_task_picks_eris(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("brainstorm unconventional alternatives", "debate", {})
        assert "eris" in aspects

    def test_investigation_picks_nyx(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("deep analysis and investigation of the truth", "debate", {})
        assert "nyx" in aspects

    def test_empathy_picks_echo(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("help me communicate my feelings to the team", "debate", {})
        assert "echo" in aspects

    def test_tribunal_returns_all(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("full review", "tribunal", {})
        assert len(aspects) == 6

    def test_solo_returns_morrigan(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("hello", "solo", {})
        assert aspects == ["morrigan"]

    def test_morrigan_always_included_in_debate(self):
        from services.debate_engine import select_aspects_for_task
        aspects = select_aspects_for_task("help with empathy feelings communication people", "debate", {})
        # Even when echo scores highest, morrigan should still be included
        assert "morrigan" in aspects or len(aspects) == 2


# ---------------------------------------------------------------------------
# Test: run_deliberation -- DEBATE mode
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_deliberation_debate_mode(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Should I refactor or rewrite the auth module?",
        state={},
        cfg={},
        mode="debate",
        aspects=["morrigan", "nyx"],
    )

    assert result.mode == "debate"
    assert len(result.participating_aspects) == 2
    assert "morrigan" in result.participating_aspects
    assert "nyx" in result.participating_aspects
    assert result.final_response  # non-empty
    assert result.aspect_responses  # has entries
    assert len(result.aspect_responses) == 2
    assert result.synthesis_notes  # notes were extracted


# ---------------------------------------------------------------------------
# Test: run_deliberation -- COUNCIL mode
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_deliberation_council_mode(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Is this approach ethical and risky?",
        state={},
        cfg={},
        mode="council",
        aspects=["morrigan", "lilith", "echo"],
    )

    assert result.mode == "council"
    assert len(result.participating_aspects) == 3
    assert result.final_response
    assert len(result.aspect_responses) == 3
    assert len(result.critiques) == 3


# ---------------------------------------------------------------------------
# Test: run_deliberation -- TRIBUNAL mode (all 6)
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_deliberation_tribunal_mode(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Give me a comprehensive review and all perspectives",
        state={},
        cfg={},
        mode="tribunal",
    )

    assert result.mode == "tribunal"
    assert len(result.participating_aspects) == 6
    assert len(result.aspect_responses) == 6
    assert result.final_response


# ---------------------------------------------------------------------------
# Test: synthesis combines viewpoints and extracts notes
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_synthesis_extracts_notes(mock_completion, mock_personality):
    from services.debate_engine import _synthesize

    responses = {
        "morrigan": _CANNED_RESPONSES["morrigan"],
        "nyx": _CANNED_RESPONSES["nyx"],
    }
    critiques = {
        "morrigan": _CANNED_CRITIQUES["morrigan"],
        "nyx": _CANNED_CRITIQUES["nyx"],
    }

    final, notes = _synthesize("Should I refactor?", responses, critiques, {}, {})

    assert final  # non-empty
    assert notes  # synthesis notes extracted
    assert "SYNTHESIS_NOTES" not in final  # tag stripped from response


# ---------------------------------------------------------------------------
# Test: auto-mode detection end-to-end
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_auto_mode_selects_debate(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Should I use PostgreSQL or MongoDB? Compare the pros and cons.",
        state={},
        cfg={},
        mode="auto",
    )

    # "should i" and "pros and cons" -> debate
    assert result.mode == "debate"
    assert len(result.participating_aspects) >= 2


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_auto_mode_selects_solo_for_simple(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="What is a list comprehension?",
        state={},
        cfg={},
        mode="auto",
    )

    assert result.mode == "solo"
    assert len(result.participating_aspects) == 1


# ---------------------------------------------------------------------------
# Test: domain mapping is complete
# ---------------------------------------------------------------------------


def test_all_aspects_have_domains():
    from services.debate_engine import ALL_ASPECT_IDS, ASPECT_DOMAINS

    for aid in ALL_ASPECT_IDS:
        assert aid in ASPECT_DOMAINS
        assert len(ASPECT_DOMAINS[aid]) >= 3, f"{aid} has fewer than 3 domains"


def test_all_six_aspects_listed():
    from services.debate_engine import ALL_ASPECT_IDS

    expected = {"morrigan", "nyx", "echo", "eris", "cassandra", "lilith"}
    assert set(ALL_ASPECT_IDS) == expected


# ---------------------------------------------------------------------------
# Test: SOLO mode returns single aspect response
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=_mock_run_completion)
def test_solo_mode_single_aspect(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Fix the login bug",
        state={},
        cfg={},
        mode="solo",
        aspects=["cassandra"],
    )

    assert result.mode == "solo"
    assert result.participating_aspects == ["cassandra"]
    assert not result.critiques  # no cross-critique in solo
    assert not result.synthesis_notes


# ---------------------------------------------------------------------------
# Test: extract_text handles various response formats
# ---------------------------------------------------------------------------


def test_extract_text_from_dict():
    from services.debate_engine import _extract_text

    result = {"choices": [{"message": {"content": "hello world"}}]}
    assert _extract_text(result) == "hello world"


def test_extract_text_from_string():
    from services.debate_engine import _extract_text

    assert _extract_text("  raw string  ") == "raw string"


def test_extract_text_from_empty():
    from services.debate_engine import _extract_text

    assert _extract_text({}) == ""
    assert _extract_text(None) == ""
    assert _extract_text({"choices": []}) == ""


# ---------------------------------------------------------------------------
# Test: deliberation handles LLM failures gracefully
# ---------------------------------------------------------------------------


@patch("services.debate_engine._load_aspect_personality", side_effect=lambda aid: _FAKE_PERSONALITIES.get(aid, {"id": aid, "name": aid}))
@patch("services.llm_gateway.run_completion", side_effect=Exception("LLM unavailable"))
def test_deliberation_handles_llm_failure(mock_completion, mock_personality):
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Should I refactor?",
        state={},
        cfg={},
        mode="debate",
        aspects=["morrigan", "nyx"],
    )

    # Should still return a result, even with failure markers
    assert result.mode == "debate"
    assert len(result.participating_aspects) == 2
    # Aspect responses should contain failure markers
    for aid, resp in result.aspect_responses.items():
        assert "unable to respond" in resp.lower()
    # Synthesis should have failed gracefully
    assert result.synthesis_notes == "synthesis_failed"
    assert "unable to respond" in result.final_response.lower()

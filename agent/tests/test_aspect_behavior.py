# -*- coding: utf-8 -*-
"""
test_aspect_behavior.py -- Unit tests for aspect behavioral separation.

Tests reasoning depth bias, response length instructions, step limit
derivation, refusal topics, and the behavior block prompt text.

Run:
    cd agent/ && python -m pytest tests/test_aspect_behavior.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.aspect_behavior import (
    apply_reasoning_depth,
    build_behavior_block,
    get_behavior_summary,
    get_max_steps,
    get_refusal_topics,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aspect(aid: str, behavior: dict | None = None) -> dict:
    base = {"id": aid, "name": aid.capitalize()}
    if behavior is not None:
        base["behavior"] = behavior
    return base


def _beh(depth="auto", length="medium", steps=6, topics=None):
    return {
        "reasoning_depth_bias": depth,
        "response_length_bias": length,
        "max_steps_bias": steps,
        "refusal_topics": topics or [],
    }


# ---------------------------------------------------------------------------
# apply_reasoning_depth
# ---------------------------------------------------------------------------

class TestApplyReasoningDepth:
    def test_auto_passthrough_light(self):
        a = _aspect("eris", _beh(depth="auto"))
        assert apply_reasoning_depth(a, "light") == "light"

    def test_auto_passthrough_deep(self):
        a = _aspect("nyx", _beh(depth="auto"))
        assert apply_reasoning_depth(a, "deep") == "deep"

    def test_deep_bias_upgrades_light(self):
        a = _aspect("nyx", _beh(depth="deep"))
        assert apply_reasoning_depth(a, "light") == "deep"

    def test_deep_bias_keeps_deep(self):
        a = _aspect("nyx", _beh(depth="deep"))
        assert apply_reasoning_depth(a, "deep") == "deep"

    def test_deep_bias_respects_none(self):
        # Trivial turns stay trivial regardless of aspect
        a = _aspect("nyx", _beh(depth="deep"))
        assert apply_reasoning_depth(a, "none") == "none"

    def test_light_bias_downgrades_deep(self):
        a = _aspect("eris", _beh(depth="light"))
        assert apply_reasoning_depth(a, "deep") == "light"

    def test_light_bias_keeps_light(self):
        a = _aspect("eris", _beh(depth="light"))
        assert apply_reasoning_depth(a, "light") == "light"

    def test_light_bias_keeps_none(self):
        a = _aspect("eris", _beh(depth="light"))
        assert apply_reasoning_depth(a, "none") == "none"

    def test_no_behavior_field_passthrough(self):
        # Aspect with no behavior block -- pass through
        a = _aspect("morrigan")
        assert apply_reasoning_depth(a, "light") == "light"
        assert apply_reasoning_depth(a, "deep") == "deep"

    def test_none_aspect_passthrough(self):
        assert apply_reasoning_depth(None, "deep") == "deep"
        assert apply_reasoning_depth({}, "light") == "light"


# ---------------------------------------------------------------------------
# get_max_steps
# ---------------------------------------------------------------------------

class TestGetMaxSteps:
    def test_aspect_steps_used_when_no_limit(self):
        a = _aspect("nyx", _beh(steps=12))
        assert get_max_steps(a) == 12

    def test_base_limit_lower_wins(self):
        a = _aspect("nyx", _beh(steps=12))
        assert get_max_steps(a, base_limit=5) == 5

    def test_aspect_lower_wins(self):
        a = _aspect("echo", _beh(steps=4))
        assert get_max_steps(a, base_limit=10) == 4

    def test_equal_values(self):
        a = _aspect("morrigan", _beh(steps=8))
        assert get_max_steps(a, base_limit=8) == 8

    def test_min_clamp(self):
        a = _aspect("eris", _beh(steps=0))
        assert get_max_steps(a) >= 2

    def test_max_clamp(self):
        a = _aspect("nyx", _beh(steps=999))
        assert get_max_steps(a) <= 20

    def test_no_behavior_returns_default(self):
        a = _aspect("cassandra")
        assert get_max_steps(a) == 6  # _DEFAULT_STEPS

    def test_none_aspect_returns_default(self):
        assert get_max_steps(None) == 6
        assert get_max_steps({}) == 6


# ---------------------------------------------------------------------------
# get_refusal_topics
# ---------------------------------------------------------------------------

class TestGetRefusalTopics:
    def test_topics_returned(self):
        a = _aspect("lilith", _beh(topics=["harm", "manipulation"]))
        assert "harm" in get_refusal_topics(a)
        assert "manipulation" in get_refusal_topics(a)

    def test_empty_list_returned_by_default(self):
        a = _aspect("morrigan", _beh(topics=[]))
        assert get_refusal_topics(a) == []

    def test_no_behavior_returns_empty(self):
        assert get_refusal_topics(_aspect("echo")) == []

    def test_topics_lowercased(self):
        a = _aspect("lilith", _beh(topics=["HARM", "Manipulation"]))
        topics = get_refusal_topics(a)
        assert all(t == t.lower() for t in topics)


# ---------------------------------------------------------------------------
# build_behavior_block
# ---------------------------------------------------------------------------

class TestBuildBehaviorBlock:
    def test_concise_length_in_block(self):
        a = _aspect("morrigan", _beh(length="concise"))
        block = build_behavior_block(a)
        assert "concise" in block.lower() or "lead with" in block.lower()

    def test_thorough_length_in_block(self):
        a = _aspect("nyx", _beh(length="thorough"))
        block = build_behavior_block(a)
        assert "thorough" in block.lower() or "trade-offs" in block.lower()

    def test_medium_length_no_instruction(self):
        # Medium is the default -- not injected to avoid noise
        a = _aspect("echo", _beh(length="medium"))
        block = build_behavior_block(a)
        # Medium should produce no length instruction (it's the neutral default)
        assert "medium" not in block.lower() or block == ""

    def test_refusal_topics_in_block(self):
        a = _aspect("lilith", _beh(length="medium", topics=["harm", "coercion"]))
        block = build_behavior_block(a)
        assert "harm" in block
        assert "coercion" in block
        assert "refuse" in block.lower()

    def test_no_behavior_empty_block(self):
        assert build_behavior_block(_aspect("morrigan")) == ""

    def test_none_aspect_empty_block(self):
        assert build_behavior_block(None) == ""
        assert build_behavior_block({}) == ""

    def test_all_defaults_empty_block(self):
        a = _aspect("echo", _beh(depth="auto", length="medium", steps=6, topics=[]))
        assert build_behavior_block(a) == ""


# ---------------------------------------------------------------------------
# get_behavior_summary
# ---------------------------------------------------------------------------

class TestGetBehaviorSummary:
    def test_summary_contains_all_keys(self):
        a = _aspect("cassandra", _beh(depth="deep", length="thorough", steps=6))
        s = get_behavior_summary(a)
        assert s["aspect_id"] == "cassandra"
        assert s["reasoning_depth_bias"] == "deep"
        assert s["response_length_bias"] == "thorough"
        assert s["max_steps_bias"] == 6
        assert isinstance(s["refusal_topics"], list)

    def test_summary_unknown_aspect(self):
        s = get_behavior_summary({})
        assert s["aspect_id"] == "unknown"

    def test_summary_none(self):
        s = get_behavior_summary(None)
        assert s["aspect_id"] == "unknown"


# ---------------------------------------------------------------------------
# Integration: real personality JSON files
# ---------------------------------------------------------------------------

PERSONALITIES_DIR = AGENT_DIR.parent / "personalities"


@pytest.mark.skipif(not PERSONALITIES_DIR.exists(), reason="personalities/ not found")
class TestRealPersonalities:
    """Verify the behavior blocks we added to the JSON files are correct."""

    def _load(self, name):
        import json
        return json.loads((PERSONALITIES_DIR / f"{name}.json").read_text(encoding="utf-8"))

    def test_morrigan_deep_concise(self):
        a = self._load("morrigan")
        assert apply_reasoning_depth(a, "light") == "deep"
        assert build_behavior_block(a) != ""  # concise instruction injected

    def test_nyx_deep_thorough(self):
        a = self._load("nyx")
        assert apply_reasoning_depth(a, "light") == "deep"
        block = build_behavior_block(a)
        assert "thorough" in block.lower() or "trade-off" in block.lower()

    def test_nyx_max_steps_12(self):
        a = self._load("nyx")
        assert get_max_steps(a) == 12

    def test_echo_light_medium(self):
        a = self._load("echo")
        assert apply_reasoning_depth(a, "deep") == "light"
        # medium is default -- no instruction injected
        block = build_behavior_block(a)
        assert "refusal" not in block.lower()  # echo has no refusal topics

    def test_eris_light_concise(self):
        a = self._load("eris")
        assert apply_reasoning_depth(a, "deep") == "light"
        assert get_max_steps(a) == 4

    def test_cassandra_deep_thorough(self):
        a = self._load("cassandra")
        assert apply_reasoning_depth(a, "light") == "deep"
        assert get_max_steps(a) == 6

    def test_lilith_refusal_topics(self):
        a = self._load("lilith")
        topics = get_refusal_topics(a)
        assert len(topics) > 0
        block = build_behavior_block(a)
        assert "refuse" in block.lower()

    def test_all_aspects_have_behavior_block(self):
        import json
        for f in sorted(PERSONALITIES_DIR.glob("*.json")):
            a = json.loads(f.read_text(encoding="utf-8"))
            assert "behavior" in a, f"{f.name} missing behavior block"
            b = a["behavior"]
            assert "reasoning_depth_bias" in b
            assert "response_length_bias" in b
            assert "max_steps_bias" in b
            assert "refusal_topics" in b

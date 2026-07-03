"""Tests for the self-consistency vote (services/llm/self_consistency.py) — pure, no model."""
from __future__ import annotations

from services.llm.self_consistency import majority_decision, self_consistency_samples


def _tool(name):
    return {"action": "tool", "tool": name, "args": {}}


def test_empty_returns_none():
    assert majority_decision([]) is None
    assert majority_decision([{}, {"tool": "x"}]) is None  # no 'action' key -> filtered


def test_unanimous():
    out = majority_decision([_tool("read_file")] * 3)
    assert out["action"] == "tool" and out["tool"] == "read_file"
    assert out["_self_consistency"] == {"samples": 3, "agreement": 1.0}


def test_majority_wins():
    out = majority_decision([_tool("read_file"), _tool("grep_code"), _tool("read_file")])
    assert out["tool"] == "read_file"
    assert out["_self_consistency"]["agreement"] == round(2 / 3, 3)


def test_tie_breaks_to_earliest():
    # 1 vs 1 — the first-sampled key wins (stable)
    out = majority_decision([_tool("grep_code"), _tool("read_file")])
    assert out["tool"] == "grep_code"


def test_action_vote_across_types():
    # reason beats a single tool sample
    out = majority_decision([
        {"action": "reason", "objective_complete": True},
        {"action": "reason", "objective_complete": False},
        _tool("read_file"),
    ])
    assert out["action"] == "reason"


def test_winner_preserves_first_matching_sample_args():
    out = majority_decision([
        {"action": "tool", "tool": "read_file", "args": {"path": "a.py"}},
        {"action": "tool", "tool": "read_file", "args": {"path": "b.py"}},
    ])
    assert out["args"] == {"path": "a.py"}  # first matching sample's args


def test_tool_vs_notool_same_action_distinct():
    # a 'tool' with no name and a 'reason' are different keys
    out = majority_decision([
        {"action": "reason"}, {"action": "reason"}, {"action": "tool", "tool": "x"},
    ])
    assert out["action"] == "reason"


def test_samples_clamp():
    assert self_consistency_samples({}) == 1
    assert self_consistency_samples({"self_consistency_samples": 0}) == 1
    assert self_consistency_samples({"self_consistency_samples": 3}) == 3
    assert self_consistency_samples({"self_consistency_samples": 99}) == 7
    assert self_consistency_samples({"self_consistency_samples": "bad"}) == 1

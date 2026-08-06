"""Regression: mutating tools are forbidden on plain conversational / companion turns.

The small local model would propose write_file / git_commit on ordinary chat turns; each raised an
approval prompt the user never asked for ("she always has a random approval for a git commit and a
write file"). caps_from_turn_intent keeps mutating tools off the table unless the turn is genuinely
agentic — while still letting a real "write X" request through to the normal approval flow.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.safety.decision_policy import (
    _MUTATING_TOOLS,
    apply_caps_to_valid_tools,
    build_policy_caps,
    caps_from_turn_intent,
)


def _forbidden(state, cfg=None):
    return caps_from_turn_intent(state, cfg or {}).forbidden_tools


def test_companion_turn_forbids_mutating_tools():
    state = {"original_goal": "i feel so alone, my girlfriend and i are drifting apart", "steps": []}
    assert _MUTATING_TOOLS <= _forbidden(state)
    # write_file / git_commit specifically off the table
    assert "write_file" in _forbidden(state) and "git_commit" in _forbidden(state)


def test_casual_chat_forbids_mutating_tools():
    assert "write_file" in _forbidden({"original_goal": "how are you today?", "steps": []})
    assert "git_commit" in _forbidden({"original_goal": "tell me about the ladder in my shed", "steps": []})


def test_engineering_goal_allows_mutating_tools():
    for goal in ["write a python function to reverse a list", "fix the failing test",
                 "refactor the auth module", "commit these changes", "create a new file"]:
        assert _forbidden({"original_goal": goal, "steps": []}) == frozenset(), goal


def test_authorized_write_run_plan_allows_tools():
    assert _forbidden({"original_goal": "hey", "allow_write": True, "steps": []}) == frozenset()
    assert _forbidden({"original_goal": "hey", "allow_run": True, "steps": []}) == frozenset()
    assert _forbidden({"original_goal": "hey", "plan_mode": True, "steps": []}) == frozenset()


def test_already_mutating_this_turn_allows_more():
    state = {"original_goal": "hey", "steps": [{"action": "write_file", "result": {"ok": True}}]}
    assert _forbidden(state) == frozenset()


def test_config_flag_disables_suppression():
    state = {"original_goal": "how are you?", "steps": []}
    assert _forbidden(state, {"suppress_mutating_tools_on_chat": False}) == frozenset()


def test_apply_caps_removes_forbidden_from_valid_tools():
    base = frozenset({"read_file", "write_file", "git_commit", "grep_code"})
    caps = caps_from_turn_intent({"original_goal": "how are you?", "steps": []}, {})
    valid = apply_caps_to_valid_tools(base, caps)
    assert "write_file" not in valid and "git_commit" not in valid
    assert "read_file" in valid and "grep_code" in valid


def test_build_policy_caps_includes_turn_intent():
    caps = build_policy_caps({"original_goal": "just chatting", "steps": []}, {}, conversation_id="t1")
    assert "write_file" in caps.forbidden_tools
    assert "non_agentic_turn" in caps.sources

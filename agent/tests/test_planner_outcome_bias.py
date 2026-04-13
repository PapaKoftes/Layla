"""Planning bias + recovery gates (North Star §6, §8)."""


def test_should_plan_replan_bypasses_length_gate():
    from services.planner import should_plan

    cfg = {"planning_enabled": True, "max_plan_depth": 3}
    state = {"recovery_strategy": "replan"}
    assert should_plan("short", cfg, plan_depth=0, state=state) is True


def test_should_plan_without_replan_requires_length_and_keyword():
    from services.planner import should_plan

    cfg = {"planning_enabled": True, "max_plan_depth": 3}
    assert should_plan("short", cfg, plan_depth=0, state=None) is False
    long_goal = "x" * 81 + " implement the feature with tests"
    assert should_plan(long_goal, cfg, plan_depth=0, state={}) is True


def test_block_repeated_mutating_under_retry_constrained():
    from services.failure_recovery import block_repeated_mutating_under_retry_constrained

    st = {
        "recovery_strategy": "retry_constrained",
        "consecutive_no_progress": 1,
        "last_tool_used": "write_file",
    }
    assert block_repeated_mutating_under_retry_constrained(st, "write_file") is True
    assert block_repeated_mutating_under_retry_constrained(st, "read_file") is False
    st2 = {**st, "consecutive_no_progress": 0}
    assert block_repeated_mutating_under_retry_constrained(st2, "write_file") is False
    st3 = {**st, "recovery_strategy": "replan"}
    assert block_repeated_mutating_under_retry_constrained(st3, "write_file") is False


def test_personality_planner_bias_nonempty_for_core_aspects():
    from services.planner import personality_planner_bias

    assert "Morrigan" in personality_planner_bias("morrigan")
    assert "Nyx" in personality_planner_bias("nyx")
    assert "Lilith" in personality_planner_bias("lilith")


def test_maybe_append_inline_state_aware_repetition():
    from services.initiative_inline import maybe_append_inline_suggestion

    cfg = {"inline_initiative_enabled": True}
    state = {
        "refused": False,
        "original_goal": "fix the handler",
        "steps": [
            {"action": "read_file", "result": {"ok": True}},
            {"action": "grep_code", "result": {"ok": True}},
            {"action": "grep_code", "result": {"ok": True}},
        ],
    }
    out = maybe_append_inline_suggestion("Done.", state, cfg)
    assert "Suggestion" in out
    assert "grep_code" in out or "repeatedly" in out

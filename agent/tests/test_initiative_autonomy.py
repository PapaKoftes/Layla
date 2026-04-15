"""Initiative engine + autonomy optimizer (suggestions only; governance allowlists preserved)."""

from __future__ import annotations


def test_collect_initiative_hints_respects_gate():
    from services.initiative_engine import collect_initiative_hints

    state = {
        "status": "finished",
        "steps": [{"action": "shell", "result": {"ok": False, "error": "e"}}],
        "original_goal": "fix it",
    }
    assert collect_initiative_hints(state, {}) == []
    hints = collect_initiative_hints(state, {"initiative_engine_enabled": True})
    assert hints and "shell" in hints[0].lower()


def test_propose_step_recovery_respects_allowlist():
    from services.autonomy_optimizer import propose_step_recovery

    cfg = {"autonomy_optimizer_enabled": True}
    p = propose_step_recovery(
        failed_tool="write_file",
        validation_reason="tool:write_file:x",
        step_tools=["list_dir", "grep_code"],
        cfg=cfg,
    )
    assert p.get("action") == "suggest_tool"
    assert p.get("tool") in frozenset({"list_dir", "grep_code"})
    assert p.get("tool") != "write_file"


def test_propose_step_recovery_off_by_default():
    from services.autonomy_optimizer import propose_step_recovery

    p = propose_step_recovery(
        failed_tool="write_file",
        validation_reason="x",
        step_tools=["read_file"],
        cfg={},
    )
    assert p.get("action") == "none"


def test_propose_never_suggests_tool_outside_allowlist():
    from services.autonomy_optimizer import propose_step_recovery

    cfg = {"autonomy_optimizer_enabled": True}
    allow = ["grep_code", "list_dir"]
    p = propose_step_recovery(
        failed_tool="shell",
        validation_reason="fail",
        step_tools=allow,
        cfg=cfg,
    )
    if p.get("action") == "suggest_tool":
        assert p.get("tool") in allow


def test_last_failed_tool_from_agent_response():
    from services.autonomy_optimizer import last_failed_tool_from_agent_response

    r = last_failed_tool_from_agent_response(
        {
            "state": {
                "steps": [
                    {"action": "read_file", "result": {"ok": True}},
                    {"action": "shell", "result": {"ok": False, "error": "nope"}},
                ]
            }
        }
    )
    assert r == "shell"


def test_wakeup_engine_hints_gated():
    from services.initiative_engine import wakeup_engine_hints

    assert wakeup_engine_hints([{"topic": "a"}], {}) == []
    h = wakeup_engine_hints([], {"initiative_engine_enabled": True})
    assert h and "study" in h[0].lower()

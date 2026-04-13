from services.decision_policy import (
    PolicyCaps,
    apply_caps_to_valid_tools,
    build_policy_caps,
    caps_from_outcome_evaluation,
    effective_max_tool_calls,
    merge_policy_caps,
)


def test_merge_policy_caps_unions_forbidden():
    a = PolicyCaps(forbidden_tools=frozenset({"a"}), sources=["x"])
    b = PolicyCaps(forbidden_tools=frozenset({"b"}), require_verify_before_mutate=True, sources=["y"])
    m = merge_policy_caps(a, b)
    assert m.forbidden_tools == frozenset({"a", "b"})
    assert m.require_verify_before_mutate is True
    assert "x" in m.sources and "y" in m.sources


def test_apply_caps_removes_forbidden():
    base = frozenset({"read_file", "write_file", "reason", "think"})
    caps = PolicyCaps(forbidden_tools=frozenset({"write_file"}))
    out = apply_caps_to_valid_tools(base, caps)
    assert "write_file" not in out
    assert "read_file" in out
    assert "reason" in out


def test_outcome_low_score_tightens():
    ev = {"score": 0.35, "success": False, "tool_fail": 1}
    c = caps_from_outcome_evaluation(ev)
    assert c.require_verify_before_mutate is True
    assert c.max_tool_calls_delta < 0


def test_effective_max_tool_calls_delta():
    assert effective_max_tool_calls(10, PolicyCaps(max_tool_calls_delta=-3)) == 7


def test_build_policy_caps_disabled():
    st = {"steps": [], "goal": "hi", "original_goal": "hi"}
    caps = build_policy_caps(st, {"decision_policy_enabled": False}, conversation_id="c1")
    assert caps.sources == ["disabled"]


def test_validate_machining_ir_dict_empty_features():
    from layla.geometry.machining_ir import validate_machining_ir_dict

    v = validate_machining_ir_dict({"features": [], "machine_steps_preview": []})
    assert v.get("ok") is False
    assert "not_validated" in (v.get("machine_readiness") or "")


def test_validate_gcode_text_empty():
    from layla.geometry.machining_ir import validate_gcode_text

    v = validate_gcode_text("")
    assert v.get("ok") is False

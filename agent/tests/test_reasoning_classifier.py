"""
Tests for adaptive reasoning classifier and reasoning_mode on agent state.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_classify_hi_is_none():
    from services.reasoning_classifier import classify_reasoning_need

    assert classify_reasoning_need("hi") == "none"


def test_classify_coding_is_deep():
    from services.reasoning_classifier import classify_reasoning_need

    assert classify_reasoning_need("fix the bug in login.py") == "deep"


def test_classify_explain_for_loop_is_light():
    from services.reasoning_classifier import classify_reasoning_need

    assert classify_reasoning_need("explain what a for loop does") == "light"


def test_research_mode_forces_deep():
    from services.reasoning_classifier import classify_reasoning_need

    assert classify_reasoning_need("hi", research_mode=True) == "deep"


def test_stabilize_deep_to_light_stays_light():
    from services.reasoning_classifier import stabilize_reasoning_mode

    assert stabilize_reasoning_mode("deep", "light") == "light"
    assert stabilize_reasoning_mode("light", "deep") == "deep"
    assert stabilize_reasoning_mode("", "none") == "none"


def test_low_performance_caps_deep_to_light(monkeypatch, tmp_path):
    import agent_loop

    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    cfg = {
        "sandbox_root": str(tmp_path),
        "use_chroma": False,
        "knowledge_max_bytes": 0,
        "learnings_n": 0,
        "semantic_k": 0,
        "planning_enabled": False,
        "max_tool_calls": 10,
        "convo_turns": 0,
        "max_runtime_seconds": 5,
        "temperature": 0.0,
        "completion_max_tokens": 40,
        "telemetry_enabled": False,
        "performance_mode": "low",
        "enable_cognitive_lens": False,
        "enable_lens_knowledge": False,
        "enable_behavioral_rhythm": False,
        "enable_ui_reflection": False,
        "enable_operational_guidance": False,
        "enable_personality_expression": False,
        "uncensored": False,
        "nsfw_allowed": False,
    }
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_loop, "_get_effective_config", lambda bc: dict(bc))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")

    monkeypatch.setattr(agent_loop, "_llm_decision", lambda *a, **k: {
        "action": "reason", "tool": None, "args": {}, "objective_complete": True, "priority_level": "high",
    })
    monkeypatch.setattr(agent_loop, "run_completion", lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "morrigan", "name": "Morrigan"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)
    monkeypatch.setattr(agent_loop, "_save_outcome_memory", lambda *a, **k: None)
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *a, **k: "")
    monkeypatch.setattr(agent_loop, "_maybe_save_echo_memory", lambda *a, **k: None)

    result = agent_loop.autonomous_run(
        goal="fix the bug in login.py",
        context="",
        workspace_root=str(tmp_path),
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="",
        show_thinking=False,
    )
    assert result.get("reasoning_mode") == "light"


def test_autonomous_run_includes_reasoning_mode(monkeypatch, tmp_path):
    import agent_loop

    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    cfg = {
        "sandbox_root": str(tmp_path),
        "use_chroma": False,
        "knowledge_max_bytes": 0,
        "learnings_n": 0,
        "semantic_k": 0,
        "planning_enabled": False,
        "max_tool_calls": 10,
        "convo_turns": 0,
        "max_runtime_seconds": 5,
        "temperature": 0.0,
        "completion_max_tokens": 40,
        "telemetry_enabled": False,
        "enable_cognitive_lens": False,
        "enable_lens_knowledge": False,
        "enable_behavioral_rhythm": False,
        "enable_ui_reflection": False,
        "enable_operational_guidance": False,
        "enable_personality_expression": False,
        "uncensored": False,
        "nsfw_allowed": False,
    }
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_loop, "_get_effective_config", lambda bc: dict(bc))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")

    monkeypatch.setattr(agent_loop, "_llm_decision", lambda *a, **k: {
        "action": "reason", "tool": None, "args": {}, "objective_complete": True, "priority_level": "high",
    })
    monkeypatch.setattr(agent_loop, "run_completion", lambda *a, **k: {"choices": [{"message": {"content": "hey"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "echo", "name": "Echo"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)
    monkeypatch.setattr(agent_loop, "_save_outcome_memory", lambda *a, **k: None)
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *a, **k: "")
    monkeypatch.setattr(agent_loop, "_maybe_save_echo_memory", lambda *a, **k: None)

    result = agent_loop.autonomous_run(
        goal="hello there",
        context="",
        workspace_root=str(tmp_path),
        allow_write=False,
        allow_run=False,
        conversation_history=[],
        aspect_id="",
        show_thinking=False,
    )
    assert "reasoning_mode" in result
    assert result["reasoning_mode"] in ("none", "light", "deep")

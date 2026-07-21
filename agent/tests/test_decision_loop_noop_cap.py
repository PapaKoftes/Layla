"""audit round-3 #3: 'think'/'none' decisions advance no loop-stop counter, so a model that keeps
emitting them would spin one decision-model call per iteration until max_runtime. A no_op_steps cap
must terminate the run with a forced answer instead."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_think_only_run_is_capped_not_spun(monkeypatch, tmp_path):
    import agent_loop

    calls = {"n": 0}

    def _always_think(*a, **k):
        calls["n"] += 1
        return {"action": "think", "tool": None, "args": {}, "thought": "still thinking",
                "objective_complete": False, "priority_level": "high"}

    cfg = {
        "sandbox_root": str(tmp_path), "use_chroma": False, "knowledge_max_bytes": 0,
        "learnings_n": 0, "semantic_k": 0, "planning_enabled": False, "max_tool_calls": 10,
        "convo_turns": 0, "max_runtime_seconds": 8, "temperature": 0.0, "completion_max_tokens": 40,
        "telemetry_enabled": False, "performance_mode": "low", "decision_policy_enabled": False,
        "enable_cognitive_lens": False, "enable_lens_knowledge": False,
        "enable_behavioral_rhythm": False, "enable_ui_reflection": False,
        "enable_operational_guidance": False, "enable_personality_expression": False,
        "uncensored": False, "nsfw_allowed": False,
    }
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_loop, "_get_effective_config", lambda bc: dict(bc))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")
    monkeypatch.setattr(agent_loop, "_llm_decision", _always_think)
    monkeypatch.setattr(agent_loop, "run_completion",
                        lambda *a, **k: {"choices": [{"message": {"content": "final answer"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect",
                        lambda *a, **k: {"id": "morrigan", "name": "Morrigan"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)
    monkeypatch.setattr(agent_loop, "_save_outcome_memory", lambda *a, **k: None)
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *a, **k: "")
    monkeypatch.setattr(agent_loop, "_maybe_save_session_pattern_memory", lambda *a, **k: None)

    # allow_write=True disables the self-contained fast-path, so the decision loop actually runs.
    result = agent_loop.autonomous_run(
        goal="refactor the retry logic across the module carefully",
        context="", workspace_root=str(tmp_path), allow_write=True, allow_run=False,
        conversation_history=[], aspect_id="", show_thinking=False,
    )
    # Capped at ~no_op_cap (8) iterations — NOT spinning until the 8s max_runtime.
    assert calls["n"] <= 12, f"think loop was not capped: {calls['n']} decision calls"
    assert result is not None

"""A model "revised objective" is a note beside the operator's objective, never a replacement.

Live (jinx-20b): revised_objective was often the ANSWER ("The secret token in probe_token.txt is TOK-...").
It overwrote state["objective"], so every later decision prompt's "Objective:" was the model's own claim,
and verification/reflection judged progress against it.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))



def test_reframe_is_kept_as_a_note_and_the_objective_survives(monkeypatch, tmp_path):
    import agent_loop

    seen = []
    script = [
        {"action": "tool", "tool": "list_dir", "args": {}, "revised_objective": "The secret token is TOK-WRONG.",
         "objective_complete": False},
        {"action": "reason", "thought": "done", "objective_complete": True},
    ]

    def _decide(goal, state, *a, **k):
        seen.append({"objective": state.get("objective"), "reframe": state.get("objective_reframe")})
        return dict(script[min(len(seen) - 1, len(script) - 1)])

    cfg = {
        "sandbox_root": str(tmp_path), "use_chroma": False, "knowledge_max_bytes": 0, "learnings_n": 0,
        "semantic_k": 0, "planning_enabled": False, "max_tool_calls": 10, "convo_turns": 0,
        "max_runtime_seconds": 8, "temperature": 0.0, "completion_max_tokens": 40, "telemetry_enabled": False,
        "performance_mode": "low", "decision_policy_enabled": False, "enable_cognitive_lens": False,
        "enable_lens_knowledge": False, "enable_behavioral_rhythm": False, "enable_ui_reflection": False,
        "enable_operational_guidance": False, "enable_personality_expression": False, "uncensored": False,
        "nsfw_allowed": False,
    }
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
    monkeypatch.setattr(agent_loop.runtime_safety, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_loop, "_get_effective_config", lambda bc: dict(bc))
    monkeypatch.setattr(agent_loop.runtime_safety, "load_identity", lambda: "")
    monkeypatch.setattr(agent_loop.runtime_safety, "load_personality", lambda: "")
    monkeypatch.setattr(agent_loop, "_llm_decision", _decide)
    monkeypatch.setattr(agent_loop, "run_completion",
                        lambda *a, **k: {"choices": [{"message": {"content": "final answer"}}]})
    monkeypatch.setattr(agent_loop.orchestrator, "select_aspect", lambda *a, **k: {"id": "morrigan", "name": "M"})
    monkeypatch.setattr(agent_loop.orchestrator, "should_deliberate", lambda *a, **k: False)
    monkeypatch.setattr(agent_loop, "_save_outcome_memory", lambda *a, **k: None)
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *a, **k: "")
    monkeypatch.setattr(agent_loop, "_maybe_save_session_pattern_memory", lambda *a, **k: None)

    goal = "What is the secret token in probe_token.txt?"
    agent_loop.autonomous_run(goal=goal, context="", workspace_root=str(tmp_path), allow_write=True,
                              allow_run=False, conversation_history=[], aspect_id="", show_thinking=False)

    assert len(seen) >= 2, f"PROBE BROKEN: the reframe decision never ran a second decision: {seen}"
    after = seen[1]
    assert goal in (after["objective"] or ""), after
    assert "TOK-WRONG" not in (after["objective"] or ""), after
    assert after["reframe"] == "The secret token is TOK-WRONG.", after


def test_decision_prompt_shows_the_reframe_only_as_a_labelled_note():
    src = (AGENT_DIR / "services" / "agent" / "llm_decision.py").read_text(encoding="utf-8")
    assert "not the operator's words" in src and 'state.get("objective_reframe")' in src

"""D1 concurrent batch: read_file + list_dir in one decision step (ordering + both run)."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_autonomous_run_concurrent_batch_read_and_list_dir(tmp_path, monkeypatch):
    import runtime_safety

    import agent_loop
    from layla.tools.registry import set_effective_sandbox

    f1 = tmp_path / "a.txt"
    f1.write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("x", encoding="utf-8")

    base_cfg = {
        "sandbox_root": str(tmp_path),
        "tool_routing_enabled": False,
        "max_tool_calls": 8,
        "max_runtime_seconds": 90,
        "chat_light_max_runtime_seconds": 90,
        "use_instructor_for_decisions": False,
        "temperature": 0.2,
        "n_ctx": 4096,
        "completion_max_tokens": 64,
        "tool_call_timeout_seconds": 30,
        "semantic_k": 0,
        "context_compression": False,
        "agent_hooks_enabled": False,
    }

    monkeypatch.setattr(runtime_safety, "load_config", lambda: base_cfg)
    monkeypatch.setattr("services.planner.should_plan", lambda *a, **k: False)
    monkeypatch.setattr("services.cognitive_workspace.should_use_cognitive_workspace", lambda *a, **k: False)

    n = {"c": 0}

    def fake_llm_decision(goal, state, context, active_aspect, show_thinking, conversation_history):
        n["c"] += 1
        if n["c"] == 1:
            return {
                "action": "tool",
                "tool": "read_file",
                "args": {"path": str(f1)},
                "batch_tools": [{"tool": "list_dir", "args": {"path": str(tmp_path)}}],
                "objective_complete": False,
                "priority_level": "medium",
            }
        return {"action": "reason", "objective_complete": True, "priority_level": "medium"}

    monkeypatch.setattr(agent_loop, "_llm_decision", fake_llm_decision)
    # Avoid rare "system_busy" / scheduler interactions when the full suite loads the app.
    monkeypatch.setattr(agent_loop, "schedule_slot", lambda priority=0: nullcontext())
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda priority=0: False)

    def fake_run_completion(prompt, **kwargs):
        return {"choices": [{"message": {"content": "Done."}}]}

    monkeypatch.setattr(agent_loop, "run_completion", fake_run_completion)

    set_effective_sandbox(str(tmp_path))
    try:
        r = agent_loop.autonomous_run(
            "batch probe",
            context="",
            workspace_root=str(tmp_path),
            allow_write=False,
            allow_run=False,
            conversation_history=[],
            aspect_id="morrigan",
        )
    finally:
        set_effective_sandbox(None)

    steps = r.get("steps") or []
    actions = [s.get("action") for s in steps if isinstance(s, dict)]
    assert "read_file" in actions, actions
    assert "list_dir" in actions, actions
    assert actions.index("read_file") < actions.index("list_dir")

"""Tool routing must classify the operator's message, not the retrieval-augmented decision goal.

decision_loop appends "\\n\\n[Retrieval context]\\n<memories, reflections>" to the goal it hands the decision
step. get_tools_for_goal routed on that string: past 400 chars classify_task says "reasoning", whose
deterministic route is read-only, so live on the real model "Create a file named X containing banana" was
never offered write_file — and the reply then claimed the file existed. The more Layla remembered, the more
requests were silently downgraded to read-only.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

GOAL = "Create a file named probe_write.txt in the workspace containing exactly the word banana."
AUGMENTED = GOAL + "\n\n[Retrieval context]\nMemory:\n" + ("Reflection: the operator likes concise answers. " * 20)


def _tools(goal, monkeypatch, tmp_path):
    import runtime_safety
    from layla.tools.registry import TOOLS
    from services.agent.llm_decision import get_tools_for_goal

    base = dict(runtime_safety.load_config())
    base.update({"deterministic_tool_routes_enabled": True, "tool_routing_enabled": True})
    monkeypatch.setattr(runtime_safety, "load_config", lambda: base)
    state = {"original_goal": GOAL, "goal": GOAL}
    return get_tools_for_goal(goal, context="", workspace_root=str(tmp_path), state=state,
                              tools_registry=TOOLS, valid_tools_all=frozenset(TOOLS))


def test_probe_reproduces_the_reasoning_downgrade():
    from services.llm.model_router import classify_task

    assert len(AUGMENTED) > 400 and classify_task(AUGMENTED, "") == "reasoning", \
        "PROBE BROKEN: the augmented goal no longer trips the reasoning route"
    assert classify_task(GOAL, "") != "reasoning"


def test_write_request_is_offered_write_file_despite_retrieval_context(monkeypatch, tmp_path):
    plain = _tools(GOAL, monkeypatch, tmp_path)
    augmented = _tools(AUGMENTED, monkeypatch, tmp_path)
    assert "write_file" in plain, sorted(plain)
    assert "write_file" in augmented, f"retrieval context downgraded a write request to read-only: {sorted(augmented)}"
    assert augmented == plain, "routing must depend on the operator's message only"

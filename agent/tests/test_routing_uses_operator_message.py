"""Task routing classifies the operator's message, not the whole prompt.

With the persona/system text prepended, "Say hello in one short sentence." classified as coding (alone it is
chat), so with a code model configured every turn — greetings included — was routed to it (live: a
"code model not found" warning on every turn).
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

HEAD = ("You are Morrigan, Layla's engineering aspect: code, debug, refactor, write tests, implement "
        "functions, fix bugs in python and javascript repositories. ") * 20


def _route(monkeypatch, prompt, goal):
    import services.llm.model_router as mr
    from services.llm import llm_gateway as gw

    seen = []

    def _classify(text, context="", cfg=None, aspect_id=None):
        seen.append(text)
        return mr.classify_task(text, context)

    monkeypatch.setattr(mr, "classify_task_for_routing", _classify)
    monkeypatch.setattr(mr, "is_routing_enabled", lambda: True)
    monkeypatch.setattr(gw, "get_model_override", lambda: None)
    tok = gw._routing_prompt_var.set(prompt)
    try:
        if goal is None:
            gw._effective_model_filename({"model_filename": "main.gguf", "tool_routing_enabled": True})
        else:
            with gw.routing_goal(goal):
                gw._effective_model_filename({"model_filename": "main.gguf", "tool_routing_enabled": True})
    finally:
        gw._routing_prompt_var.reset(tok)
    return seen


def test_probe_the_full_prompt_really_misclassifies_a_greeting():
    from services.llm.model_router import classify_task

    assert classify_task("Say hello in one short sentence.") == "chat"
    assert classify_task(HEAD + "\nUser: Say hello in one short sentence.") == "coding", "PROBE BROKEN"


def test_turn_routing_classifies_the_operators_message(monkeypatch):
    seen = _route(monkeypatch, HEAD + "\nUser: Say hello in one short sentence.",
                  "Say hello in one short sentence.\n\n[Tool results so far]:\nwrite code fix bug refactor")
    assert seen == ["Say hello in one short sentence."], seen


def test_without_a_turn_goal_the_prompt_is_still_used(monkeypatch):
    seen = _route(monkeypatch, "Summarize this text please.", None)
    assert seen and seen[0].startswith("Summarize this text"), seen


def test_autonomous_run_scopes_the_routing_goal_to_the_turn():
    src = (AGENT_DIR / "agent_loop.py").read_text(encoding="utf-8")
    assert "_routing_goal(goal)" in src

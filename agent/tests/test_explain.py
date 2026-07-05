"""BL-237: explainable reasoning — concise 'why' from a run trace."""
from __future__ import annotations

from services.agent.explain import build_explanation, explain_state

_STEPS = [
    {"action": "think", "result": {"ok": True, "thought": "I should read the config first"}},
    {"action": "read_file", "args": {"path": "cfg.json"}, "result": {"ok": True}},
    {"action": "grep_code", "args": {"q": "port"}, "result": {"ok": False, "reason": "no match"}},
    {"action": "think", "result": {"ok": True, "thought": "the port is set in env, not the file"}},
    {"action": "reason", "result": "The service reads its port from the PORT env var."},
]


def test_build_extracts_thoughts_and_tools():
    e = build_explanation(_STEPS, goal="find where the port is set", answer="It's the PORT env var.")
    assert e["thoughts"] == ["I should read the config first", "the port is set in env, not the file"]
    assert [t["tool"] for t in e["tools"]] == ["read_file", "grep_code"]
    assert e["tools_succeeded"] == 1 and e["tools_failed"] == 1


def test_markdown_has_sections():
    md = build_explanation(_STEPS, goal="g", answer="a")["markdown"]
    assert "**Goal:**" in md and "**Reasoning:**" in md
    assert "**Actions taken:**" in md and "read_file✓" in md and "grep_code✗" in md
    assert "**Conclusion:**" in md


def test_empty_trace():
    e = build_explanation([], goal="", answer="")
    assert e["thoughts"] == [] and e["tools"] == []
    assert "No reasoning trace" in e["markdown"]


def test_explain_state_pulls_reason_answer():
    e = explain_state({"original_goal": "g", "steps": _STEPS})
    assert e["answer"] == "The service reads its port from the PORT env var."
    assert e["goal"] == "g"


def test_router():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import explain as er
    app = FastAPI(); app.include_router(er.router)
    client = TestClient(app)
    r = client.post("/explain", json={"steps": _STEPS, "goal": "g", "answer": "a"}).json()
    assert r["tools_succeeded"] == 1 and "**Goal:**" in r["markdown"]

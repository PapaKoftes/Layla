"""Tests for OpenClaw-style emulation: tool_policy, loop detection, HTTP cache, shell sessions, markdown skills."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_tool_policy_profile_minimal():
    from layla.tools.registry import TOOLS
    from services.tool_policy import resolve_effective_tools

    cfg = {
        "tools_profile": "minimal",
        "tools_allow": [],
        "tools_deny": [],
        "tool_routing_enabled": False,
    }
    names = resolve_effective_tools(cfg, "hello", TOOLS, skip_intent_filter=True)
    assert "read_file" in names
    assert "shell" not in names


def test_tool_policy_deny_wins():
    from layla.tools.registry import TOOLS
    from services.tool_policy import resolve_effective_tools

    cfg = {
        "tools_profile": "full",
        "tools_deny": ["shell"],
        "tool_routing_enabled": False,
    }
    names = resolve_effective_tools(cfg, "run shell", TOOLS, skip_intent_filter=True)
    assert "shell" not in names


def test_tool_loop_repeat_stop():
    from services.tool_loop_detection import push_and_evaluate

    cfg = {
        "tool_loop_detection_enabled": True,
        "tool_loop_history_size": 50,
        "tool_loop_warning_threshold": 3,
        "tool_loop_stop_threshold": 5,
        "tool_loop_detect_repeat": True,
        "tool_loop_detect_pingpong": False,
    }
    state: dict = {}
    decision = {"args": {"path": "x"}}
    assert push_and_evaluate(cfg, state, "read_file", decision) is None
    assert push_and_evaluate(cfg, state, "read_file", decision) is None
    w3 = push_and_evaluate(cfg, state, "read_file", decision)
    assert w3 and w3.startswith("WARN:")
    w4 = push_and_evaluate(cfg, state, "read_file", decision)
    assert w4 and w4.startswith("WARN:")
    stop = push_and_evaluate(cfg, state, "read_file", decision)
    assert stop and stop.startswith("STOP:")


def test_http_cache_ttl():
    from services import http_response_cache as hc

    hc.clear_cache()
    cfg = {"http_cache_ttl_seconds": 60, "http_cache_max_entries": 10}
    payload = {"ok": True, "x": 1}
    hc.set_cached("k1", payload, cfg)
    assert hc.get_cached("k1", cfg)["x"] == 1
    hc.clear_cache()


def test_shell_session_reject_blocked():
    from services.shell_sessions import shell_session_tool

    r = shell_session_tool(action="start", argv=["rm", "-rf", "/"], cwd=str(AGENT))
    assert r.get("ok") is False


def test_markdown_skills_prompt(tmp_path):
    from services.markdown_skills import load_markdown_skills_prompt

    d = tmp_path / "skills" / "demo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Test skill\n---\n\nBody instructions here.\n",
        encoding="utf-8",
    )
    cfg = {"markdown_skills_dir": str(tmp_path / "skills")}
    text = load_markdown_skills_prompt(cfg)
    assert "demo-skill" in text or "demo" in text


def test_openai_compatible_urls_order():
    from services.inference_router import _openai_compatible_base_urls

    cfg = {
        "llama_server_url": "http://a:8000",
        "inference_fallback_urls": ["http://b:8000", "http://a:8000"],
    }
    u = _openai_compatible_base_urls(cfg)
    assert u[0] == "http://a:8000"
    assert "http://b:8000" in u

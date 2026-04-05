"""Integration-style probe for services.mcp_client stdio JSON-RPC."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.mcp_client import (  # noqa: E402
    McpStdioServerSpec,
    get_cached_mcp_tool_summary_for_prompt,
    load_mcp_stdio_servers,
    mcp_session_call_tool,
    mcp_session_list_resources,
    mcp_session_list_tools,
    mcp_session_read_resource,
    stdio_jsonrpc_roundtrip,
)

FAKE_MCP = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_stdio.py"


def test_mcp_operator_auth_hint_registry():
    from layla.tools.registry import mcp_operator_auth_hint

    r = mcp_operator_auth_hint()
    assert r.get("ok") is True
    assert "mcp_stdio_servers" in (r.get("message") or "")


def test_load_mcp_stdio_servers_disabled():
    assert load_mcp_stdio_servers({"mcp_client_enabled": False, "mcp_stdio_servers": []}) == []


def test_load_mcp_stdio_servers_parses():
    cfg = {
        "mcp_client_enabled": True,
        "mcp_stdio_servers": [{"name": "a", "command": "python", "args": ["-c", "pass"]}],
    }
    specs = load_mcp_stdio_servers(cfg)
    assert len(specs) == 1
    assert specs[0].name == "a"


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_stdio_jsonrpc_roundtrip_initialize():
    spec = McpStdioServerSpec(name="fake", command=sys.executable, args=(str(FAKE_MCP),))
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = stdio_jsonrpc_roundtrip(spec, request=req, timeout_s=10.0)
    assert resp.get("result", {}).get("serverInfo", {}).get("name") == "fake-mcp"


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_session_call_tool_echo():
    spec = McpStdioServerSpec(name="fake", command=sys.executable, args=(str(FAKE_MCP),))
    out = mcp_session_call_tool(spec, "echo", {"hello": "world"}, session_timeout_s=30.0, line_timeout_s=15.0)
    assert out.get("ok") is True
    mcp = out.get("mcp") or {}
    content = (mcp.get("content") or [{}])[0] if isinstance(mcp.get("content"), list) else {}
    text = content.get("text", "") if isinstance(content, dict) else ""
    assert "ok:echo" in text
    assert "hello" in text


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_tools_call_registry(monkeypatch):
    import runtime_safety

    cfg = {
        "mcp_client_enabled": True,
        "mcp_stdio_servers": [{"name": "fake", "command": sys.executable, "args": [str(FAKE_MCP)]}],
        "sandbox_root": str(Path.home()),
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    from layla.tools.registry import mcp_tools_call

    r = mcp_tools_call(mcp_server="fake", tool_name="echo", arguments={"k": 1})
    assert r.get("ok") is True
    assert r.get("tool") == "echo"


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_session_list_tools():
    spec = McpStdioServerSpec(name="fake", command=sys.executable, args=(str(FAKE_MCP),))
    out = mcp_session_list_tools(spec, session_timeout_s=30.0, line_timeout_s=15.0)
    assert out.get("ok") is True
    mcp = out.get("mcp") or {}
    tools = mcp.get("tools") if isinstance(mcp, dict) else []
    assert isinstance(tools, list) and len(tools) >= 1
    assert any((t.get("name") == "echo") for t in tools if isinstance(t, dict))


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_list_mcp_tools_registry(monkeypatch):
    import runtime_safety

    cfg = {
        "mcp_client_enabled": True,
        "mcp_stdio_servers": [{"name": "fake", "command": sys.executable, "args": [str(FAKE_MCP)]}],
        "sandbox_root": str(Path.home()),
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    from layla.tools.registry import mcp_list_mcp_tools

    r = mcp_list_mcp_tools(mcp_server="fake")
    assert r.get("ok") is True
    assert r.get("server") == "fake"
    assert any(t.get("name") == "echo" for t in (r.get("tools") or []) if isinstance(t, dict))


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_session_list_resources():
    spec = McpStdioServerSpec(name="fake", command=sys.executable, args=(str(FAKE_MCP),))
    out = mcp_session_list_resources(spec, session_timeout_s=30.0, line_timeout_s=15.0)
    assert out.get("ok") is True
    mcp = out.get("mcp") or {}
    res = mcp.get("resources") if isinstance(mcp, dict) else []
    assert isinstance(res, list) and len(res) >= 1
    assert any((r.get("uri") == "memo://demo") for r in res if isinstance(r, dict))


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_session_read_resource():
    spec = McpStdioServerSpec(name="fake", command=sys.executable, args=(str(FAKE_MCP),))
    out = mcp_session_read_resource(spec, "memo://demo", session_timeout_s=30.0, line_timeout_s=15.0)
    assert out.get("ok") is True
    mcp = out.get("mcp") or {}
    contents = mcp.get("contents") if isinstance(mcp, dict) else []
    assert isinstance(contents, list) and len(contents) >= 1
    assert "resource-body" in str(contents[0])


@pytest.mark.skipif(not FAKE_MCP.is_file(), reason="fake mcp fixture missing")
def test_mcp_list_read_resources_registry(monkeypatch):
    import runtime_safety

    cfg = {
        "mcp_client_enabled": True,
        "mcp_stdio_servers": [{"name": "fake", "command": sys.executable, "args": [str(FAKE_MCP)]}],
        "sandbox_root": str(Path.home()),
    }
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    from layla.tools.registry import mcp_list_mcp_resources, mcp_read_mcp_resource

    lr = mcp_list_mcp_resources(mcp_server="fake")
    assert lr.get("ok") is True
    assert any((r.get("uri") == "memo://demo") for r in (lr.get("resources") or []) if isinstance(r, dict))
    rr = mcp_read_mcp_resource(mcp_server="fake", uri="memo://demo")
    assert rr.get("ok") is True


def test_get_cached_mcp_tool_summary_for_prompt(monkeypatch):
    import services.mcp_client as mc

    cfg = {
        "mcp_client_enabled": True,
        "mcp_tool_summary_ttl_seconds": 60,
        "mcp_stdio_servers": [{"name": "fake", "command": sys.executable, "args": [str(FAKE_MCP)]}],
        "sandbox_root": str(Path.home()),
    }

    calls = {"n": 0}

    def fake_list_tools(spec, **kwargs):
        calls["n"] += 1
        return {"ok": True, "mcp": {"tools": [{"name": "alpha", "description": "does a thing"}]}}

    monkeypatch.setattr(mc, "mcp_session_list_tools", fake_list_tools)
    with mc._mcp_tool_summary_lock:
        mc._mcp_tool_summary_cache["text"] = ""
        mc._mcp_tool_summary_cache["deadline"] = 0.0
    text = get_cached_mcp_tool_summary_for_prompt(cfg)
    assert "alpha" in text
    assert "mcp_tools_call" in text
    get_cached_mcp_tool_summary_for_prompt(cfg)
    assert calls["n"] == 1

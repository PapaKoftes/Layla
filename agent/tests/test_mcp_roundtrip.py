"""MCP both-directions roundtrip (Plan item 14).

Covers:
  (a) CLIENT — the refactored client holds a PERSISTENT SDK ClientSession per server:
      list_tools/call_tool succeed AND a second call REUSES the session (no respawn).
  (b) SERVER — an MCP client lists Layla's exposed tools and calls a safe one for a real result.
  (c) SAFETY — destructive tools are never exposed / are refused, and every MCP-originated
      call runs fail-closed (allow_write == allow_run == False).
Plus graceful degradation when the `mcp` SDK is absent (raw one-shot fallback still works).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# The whole suite (except the explicit degrade test) needs the official SDK; it is an
# optional extra. Skip cleanly when it is not installed rather than erroring.
pytest.importorskip("mcp", reason="official MCP SDK (mcp) not installed")

import anyio  # noqa: E402

from services.infrastructure import mcp_client as mc  # noqa: E402
from services.infrastructure.mcp_server import (  # noqa: E402
    SAFE_MCP_TOOLS,
    build_layla_mcp_server,
    exposed_tool_names,
)

FAKE_RAW = AGENT_DIR / "tests" / "fixtures" / "fake_mcp_stdio.py"

# A tiny SDK-native (FastMCP) stdio server, written to a temp file per test. Using the SDK on
# BOTH ends is the truest "roundtrip" and proves the refactored client speaks real MCP.
_FASTMCP_SERVER_SRC = '''\
import sys
from mcp.server.fastmcp import FastMCP

server = FastMCP("roundtrip-fake")


@server.tool()
def ping(msg: str = "hi") -> str:
    """Echo back a pong."""
    return f"pong:{msg}"


if __name__ == "__main__":
    server.run(transport="stdio")
'''


def _write_sdk_server(tmp_path: Path) -> Path:
    p = tmp_path / "sdk_server.py"
    p.write_text(_FASTMCP_SERVER_SRC, encoding="utf-8")
    return p


# ── (a) CLIENT: persistent session, reused across calls ──────────────────────


def test_client_list_and_call_through_refactored_client(tmp_path):
    server_py = _write_sdk_server(tmp_path)
    spec = mc.McpStdioServerSpec(name="rt_pub", command=sys.executable, args=(str(server_py),))
    lt = mc.mcp_session_list_tools(spec, session_timeout_s=30.0)
    assert lt.get("ok") is True
    tools = lt["mcp"]["tools"]
    assert any(t.get("name") == "ping" for t in tools)

    ct = mc.mcp_session_call_tool(spec, "ping", {"msg": "world"}, session_timeout_s=30.0)
    assert ct.get("ok") is True
    text = ct["mcp"]["content"][0]["text"]
    assert "pong:world" in text


def test_client_reuses_session_no_respawn(tmp_path):
    """Second call must reuse the live ClientSession — exactly ONE subprocess spawn."""
    server_py = _write_sdk_server(tmp_path)
    spec = mc.McpStdioServerSpec(name="rt_reuse", command=sys.executable, args=(str(server_py),))
    pool = mc._McpClientPool()  # dedicated pool → deterministic spawn accounting
    try:
        assert pool.spawn_count == 0
        lt = pool.list_tools(spec, timeout_s=30.0)
        assert any(t.name == "ping" for t in lt.tools)
        assert pool.spawn_count == 1  # one session spawned

        first_session = pool._sessions[mc._spec_key(spec)]
        ct = pool.call_tool(spec, "ping", {"msg": "again"}, timeout_s=30.0)
        assert "pong:again" in ct.content[0].text
        # Still exactly one spawn, and the SAME session object serviced the second call.
        assert pool.spawn_count == 1
        assert pool._sessions[mc._spec_key(spec)] is first_session
    finally:
        pool.close_all()


def test_client_degrades_without_sdk(monkeypatch):
    """With the SDK reported absent, the client falls back to the raw one-shot path."""
    if not FAKE_RAW.is_file():
        pytest.skip("raw fake fixture missing")
    monkeypatch.setattr(mc, "_sdk", lambda: None)
    spec = mc.McpStdioServerSpec(name="fallback", command=sys.executable, args=(str(FAKE_RAW),))
    out = mc.mcp_session_list_tools(spec, session_timeout_s=30.0, line_timeout_s=15.0)
    assert out.get("ok") is True
    assert any(t.get("name") == "echo" for t in out["mcp"]["tools"])


# ── (b) SERVER: expose Layla, list + call a safe tool ────────────────────────


def _enabled_cfg(monkeypatch, tmp_path):
    import runtime_safety
    cfg = {"mcp_server_enabled": True, "sandbox_root": str(tmp_path)}
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)
    return cfg


def test_server_lists_and_calls_safe_tool(monkeypatch, tmp_path):
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    _enabled_cfg(monkeypatch, tmp_path)
    server = build_layla_mcp_server()  # loads the enabled cfg above

    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def go():
        async with connect(server) as sess:
            await sess.initialize()
            lt = await sess.list_tools()
            names = {t.name for t in lt.tools}
            # memory recall + safe reads are exposed
            assert "search_memories" in names
            assert "list_dir" in names
            # A safe read returns a REAL result scoped to the configured sandbox.
            r = await sess.call_tool("list_dir", {"path": "."})
            assert r.isError is False
            data = json.loads(r.content[0].text)
            assert data.get("ok") is True
            assert any(e.get("name") == "hello.txt" for e in data.get("entries", []))

    anyio.run(go)


def test_server_exposes_memory_recall_resource(monkeypatch, tmp_path):
    _enabled_cfg(monkeypatch, tmp_path)
    server = build_layla_mcp_server()
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def go():
        async with connect(server) as sess:
            await sess.initialize()
            lr = await sess.list_resources()
            uris = {str(r.uri) for r in lr.resources}
            assert "layla://memory/recent" in uris
            rr = await sess.read_resource(next(iter(lr.resources)).uri)
            body = json.loads(str(rr.contents[0].text))
            assert body.get("ok") is True  # memory recall returned a structured result

    anyio.run(go)


# ── (c) SAFETY: no destructive exposure, forced fail-closed ──────────────────

_DESTRUCTIVE = [
    "write_file", "write_files_batch", "apply_patch", "search_replace", "replace_in_file",
    "shell", "shell_session_start", "run_python", "run_tests", "pip_install", "docker_run",
    "git_commit", "git_push", "git_revert", "git_clone", "github_pr",
    "send_email", "send_webhook", "discord_send", "mcp_tools_call", "clipboard_write",
]


def test_destructive_tools_are_never_exposed(monkeypatch, tmp_path):
    _enabled_cfg(monkeypatch, tmp_path)
    exposed = set(exposed_tool_names())
    assert exposed, "expected a non-empty safe surface"
    for bad in _DESTRUCTIVE:
        assert bad not in exposed, f"destructive tool {bad!r} must not be exposed over MCP"
    # And the curated allowlist itself contains no destructive names.
    for bad in _DESTRUCTIVE:
        assert bad not in SAFE_MCP_TOOLS


def test_server_refuses_unexposed_tool(monkeypatch, tmp_path):
    _enabled_cfg(monkeypatch, tmp_path)
    server = build_layla_mcp_server()
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def go():
        async with connect(server) as sess:
            await sess.initialize()
            r = await sess.call_tool("write_file", {"path": "x", "content": "y"})
            payload = json.loads(r.content[0].text)
            assert payload.get("ok") is False
            assert "not exposed" in payload.get("error", "")

    anyio.run(go)


def test_mcp_calls_are_forced_read_only(monkeypatch):
    """Every MCP-originated call runs with allow_write == allow_run == False."""
    import services.infrastructure.mcp_server as srv

    captured: dict = {}

    def fake_run_tool(tool_name, args, timeout_s=60.0, sandbox_root=None, *, allow_run=False, conversation_id=""):
        from services.tools.tool_permissions import check_tool_permission
        w_ok, _ = check_tool_permission("write_file")
        x_ok, _ = check_tool_permission("shell")
        r_ok, _ = check_tool_permission("read_file")
        captured.update(
            allow_run=allow_run,
            write_blocked=(not w_ok),
            exec_blocked=(not x_ok),
            read_allowed=r_ok,
        )
        return {"ok": True, "tool_name": tool_name}

    monkeypatch.setattr("core.executor.run_tool", fake_run_tool)
    out = srv._run_safe_tool("read_file", {"path": "x"}, "")
    assert out.get("ok") is True
    assert captured["allow_run"] is False          # run_tool called with allow_run=False
    assert captured["write_blocked"] is True        # writes refused by the active context
    assert captured["exec_blocked"] is True         # exec refused by the active context
    assert captured["read_allowed"] is True         # safe reads still permitted


def test_server_refuses_to_build_when_disabled(monkeypatch):
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"mcp_server_enabled": False})
    with pytest.raises(RuntimeError, match="mcp_server_enabled"):
        build_layla_mcp_server()


def test_standalone_entry_refuses_when_disabled(monkeypatch):
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"mcp_server_enabled": False})
    from clients.layla_mcp_server import main
    assert main([]) == 2  # fail-closed: exits non-zero without serving

"""
MCP stdio client building blocks (opt-in; agent-loop wiring is incremental).

Use this module for JSON-RPC over newline-delimited messages to a subprocess.
See tests/test_mcp_client_stdio.py for a minimal fake server.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("layla")


@dataclass(frozen=True)
class McpStdioServerSpec:
    """One MCP server launched as a subprocess (command + argv)."""

    name: str
    command: str
    args: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> McpStdioServerSpec | None:
        cmd = (d.get("command") or "").strip()
        if not cmd:
            return None
        raw_args = d.get("args") or []
        if not isinstance(raw_args, list):
            raw_args = []
        args = tuple(str(x) for x in raw_args)
        return cls(name=name, command=cmd, args=args)


def load_mcp_stdio_servers(cfg: dict) -> list[McpStdioServerSpec]:
    """Parse runtime_config `mcp_stdio_servers` list of {name, command, args}."""
    if not cfg.get("mcp_client_enabled"):
        return []
    raw = cfg.get("mcp_stdio_servers")
    if not isinstance(raw, list):
        return []
    out: list[McpStdioServerSpec] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"server_{i}")
        spec = McpStdioServerSpec.from_dict(name, item)
        if spec:
            out.append(spec)
    return out


def stdio_jsonrpc_roundtrip(
    spec: McpStdioServerSpec,
    *,
    request: dict[str, Any],
    cwd: Path | None = None,
    timeout_s: float = 5.0,
    decode: Callable[[str], dict[str, Any]] = json.loads,
) -> dict[str, Any]:
    """
    Send one JSON-RPC object (one line) and read one JSON line response.
    Suitable for initialize / probes; not a full MCP session manager.
    """
    line = json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n"
    proc = subprocess.Popen(
        [spec.command, *spec.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdin is not None and proc.stdout is not None
    err_chunks: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            err_chunks.append(proc.stderr.read() or "")
        except Exception:
            pass

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()
    proc.stdin.write(line)
    proc.stdin.flush()
    proc.stdin.close()
    deadline = time.monotonic() + timeout_s
    out_line = ""
    while time.monotonic() < deadline:
        out_line = proc.stdout.readline()
        if out_line.strip():
            break
        if proc.poll() is not None:
            break
        time.sleep(0.02)
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    t.join(timeout=1)
    if not out_line.strip():
        raise TimeoutError(f"mcp stdio no response from {spec.name!r}")
    return decode(out_line.strip())


def _mcp_spawn_stdio(spec: McpStdioServerSpec) -> subprocess.Popen | None:
    proc = subprocess.Popen(
        [spec.command, *spec.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdin is None or proc.stdout is None:
        return None
    return proc


def _mcp_handshake_initialized(
    proc: subprocess.Popen,
    deadline_remaining: Callable[[], float],
) -> dict[str, Any]:
    init_obj: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "layla", "version": "1.0.0"},
        },
    }
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(init_obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line1 = _readline_threaded(proc, deadline_remaining())
    if not line1.strip():
        return {"ok": False, "error": "mcp initialize: no response"}
    r1 = json.loads(line1.strip())
    if r1.get("error"):
        return {"ok": False, "error": f"mcp initialize failed: {r1.get('error')}"}
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    proc.stdin.write(json.dumps(notif, separators=(",", ":"), ensure_ascii=False) + "\n")
    proc.stdin.flush()
    return {"ok": True}


def _mcp_jsonrpc_request_line(
    proc: subprocess.Popen,
    req: dict[str, Any],
    deadline_remaining: Callable[[], float],
    *,
    no_response_err: str,
    rpc_error_label: str,
) -> dict[str, Any]:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(req, separators=(",", ":"), ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line2 = _readline_threaded(proc, deadline_remaining())
    if not line2.strip():
        return {"ok": False, "error": no_response_err}
    r2 = json.loads(line2.strip())
    if r2.get("error"):
        return {"ok": False, "error": f"mcp {rpc_error_label} failed: {r2.get('error')}"}
    return {"ok": True, "mcp": r2.get("result"), "raw": r2}


def _mcp_close_stdio_process(proc: subprocess.Popen) -> None:
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# TTL cache for decision-prompt injection (see get_cached_mcp_tool_summary_for_prompt).
_mcp_tool_summary_cache: dict[str, Any] = {"text": "", "deadline": 0.0}
_mcp_tool_summary_lock = threading.Lock()


def get_cached_mcp_tool_summary_for_prompt(cfg: dict[str, Any]) -> str:
    """
    One-line-per-tool summary per configured MCP server, for _llm_decision context.
    Refreshes on TTL; avoids registering every remote tool as a native TOOLS key.
    """
    if not cfg.get("mcp_client_enabled"):
        return ""
    ttl = float(cfg.get("mcp_tool_summary_ttl_seconds") or 300)
    now = time.monotonic()
    with _mcp_tool_summary_lock:
        if now < float(_mcp_tool_summary_cache.get("deadline", 0)) and (_mcp_tool_summary_cache.get("text") or "").strip():
            return str(_mcp_tool_summary_cache["text"])
    specs = load_mcp_stdio_servers(cfg)
    if not specs:
        return ""
    line_timeout = min(30.0, max(5.0, ttl))
    session_timeout = min(90.0, ttl + 30.0)
    lines: list[str] = [
        "External MCP tools (call native tool mcp_tools_call with mcp_server + tool_name; "
        "discover via mcp_list_mcp_tools):",
    ]
    for spec in specs:
        out = mcp_session_list_tools(
            spec, line_timeout_s=line_timeout, session_timeout_s=session_timeout
        )
        if not out.get("ok"):
            err = str(out.get("error") or "failed")[:120]
            lines.append(f"- {spec.name}: (tools/list failed: {err})")
            continue
        mcp = out.get("mcp") or {}
        tools = mcp.get("tools") if isinstance(mcp, dict) else None
        if not isinstance(tools, list):
            tools = []
        parts: list[str] = []
        for t in tools[:50]:
            if not isinstance(t, dict):
                continue
            nm = str(t.get("name") or "")[:120]
            if not nm:
                continue
            desc = str(t.get("description") or "").replace("\n", " ").strip()[:100]
            parts.append(f"{nm}" + (f" — {desc}" if desc else ""))
        lines.append(f"- {spec.name}: " + ("; ".join(parts) if parts else "(no tools)"))
    text = "\n".join(lines).strip()
    if len(text) > 4000:
        text = text[:3997] + "..."
    with _mcp_tool_summary_lock:
        _mcp_tool_summary_cache["text"] = text
        _mcp_tool_summary_cache["deadline"] = time.monotonic() + max(5.0, ttl)
    return text



def mcp_session_list_resources(
    spec: McpStdioServerSpec,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """initialize, notifications/initialized, resources/list."""
    deadline = time.monotonic() + session_timeout_s
    proc = _mcp_spawn_stdio(spec)
    if proc is None:
        return {"ok": False, "error": "mcp subprocess missing stdio pipes"}

    def _deadline_remaining() -> float:
        return max(0.5, min(line_timeout_s, deadline - time.monotonic()))

    try:
        hs = _mcp_handshake_initialized(proc, _deadline_remaining)
        if not hs.get("ok"):
            return hs
        req = {"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}}
        return _mcp_jsonrpc_request_line(
            proc,
            req,
            _deadline_remaining,
            no_response_err="mcp resources/list: no response",
            rpc_error_label="resources/list",
        )
    except Exception as e:
        logger.warning("mcp_session_list_resources: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        _mcp_close_stdio_process(proc)



def mcp_session_read_resource(
    spec: McpStdioServerSpec,
    uri: str,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """initialize, notifications/initialized, resources/read."""
    uri = (uri or "").strip()
    if not uri:
        return {"ok": False, "error": "uri is required"}
    deadline = time.monotonic() + session_timeout_s
    proc = _mcp_spawn_stdio(spec)
    if proc is None:
        return {"ok": False, "error": "mcp subprocess missing stdio pipes"}

    def _deadline_remaining() -> float:
        return max(0.5, min(line_timeout_s, deadline - time.monotonic()))

    try:
        hs = _mcp_handshake_initialized(proc, _deadline_remaining)
        if not hs.get("ok"):
            return hs
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": uri},
        }
        return _mcp_jsonrpc_request_line(
            proc,
            req,
            _deadline_remaining,
            no_response_err="mcp resources/read: no response",
            rpc_error_label="resources/read",
        )
    except Exception as e:
        logger.warning("mcp_session_read_resource: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        _mcp_close_stdio_process(proc)


def _readline_threaded(proc: subprocess.Popen, timeout_s: float) -> str:
    """Read one line from proc.stdout with timeout (Windows-safe)."""
    out: list[str] = []
    err: list[BaseException] = []

    def _go() -> None:
        try:
            if proc.stdout:
                out.append(proc.stdout.readline())
        except BaseException as e:
            err.append(e)

    th = threading.Thread(target=_go, daemon=True)
    th.start()
    th.join(timeout=max(0.05, timeout_s))
    if err:
        raise err[0]
    return out[0] if out else ""



def mcp_session_call_tool(
    spec: McpStdioServerSpec,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """initialize, notifications/initialized, tools/call."""
    arguments = arguments if isinstance(arguments, dict) else {}
    deadline = time.monotonic() + session_timeout_s
    proc = _mcp_spawn_stdio(spec)
    if proc is None:
        return {"ok": False, "error": "mcp subprocess missing stdio pipes"}

    def _deadline_remaining() -> float:
        return max(0.5, min(line_timeout_s, deadline - time.monotonic()))

    try:
        hs = _mcp_handshake_initialized(proc, _deadline_remaining)
        if not hs.get("ok"):
            return hs
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        return _mcp_jsonrpc_request_line(
            proc,
            req,
            _deadline_remaining,
            no_response_err="mcp tools/call: no response",
            rpc_error_label="tools/call",
        )
    except Exception as e:
        logger.warning("mcp_session_call_tool: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        _mcp_close_stdio_process(proc)



def mcp_session_list_tools(
    spec: McpStdioServerSpec,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """initialize, notifications/initialized, tools/list."""
    deadline = time.monotonic() + session_timeout_s
    proc = _mcp_spawn_stdio(spec)
    if proc is None:
        return {"ok": False, "error": "mcp subprocess missing stdio pipes"}

    def _deadline_remaining() -> float:
        return max(0.5, min(line_timeout_s, deadline - time.monotonic()))

    try:
        hs = _mcp_handshake_initialized(proc, _deadline_remaining)
        if not hs.get("ok"):
            return hs
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        return _mcp_jsonrpc_request_line(
            proc,
            req,
            _deadline_remaining,
            no_response_err="mcp tools/list: no response",
            rpc_error_label="tools/list",
        )
    except Exception as e:
        logger.warning("mcp_session_list_tools: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        _mcp_close_stdio_process(proc)


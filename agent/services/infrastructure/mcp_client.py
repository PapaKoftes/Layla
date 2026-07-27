"""
MCP stdio client building blocks (opt-in; agent-loop wiring is incremental).

Use this module for JSON-RPC over newline-delimited messages to a subprocess.
See tests/test_mcp_client_stdio.py for a minimal fake server.
"""

from __future__ import annotations

import atexit
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("layla")

# Transport aliases accepted in mcp_stdio_servers[].transport (streamable-HTTP has a few spellings).
_HTTP_TRANSPORTS = frozenset({"http", "streamable-http", "streamable_http", "streamablehttp"})


@dataclass(frozen=True)
class McpStdioServerSpec:
    """One configured MCP server.

    Two transports are supported (SDK-backed when the official ``mcp`` package is installed):
      * ``stdio`` (default) — launched as a subprocess (``command`` + ``args``).
      * ``http`` — streamable-HTTP endpoint at ``url`` (no subprocess).

    The name is kept for backward compatibility (it long predates the HTTP transport).
    """

    name: str
    command: str
    args: tuple[str, ...] = ()
    transport: str = "stdio"
    url: str = ""

    @property
    def is_http(self) -> bool:
        return self.transport in _HTTP_TRANSPORTS or bool(self.url)

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> McpStdioServerSpec | None:
        cmd = (d.get("command") or "").strip()
        url = (d.get("url") or "").strip()
        transport = (str(d.get("transport") or "").strip().lower()) or ("http" if url else "stdio")
        is_http = transport in _HTTP_TRANSPORTS or bool(url)
        # A spec must be launchable: stdio needs a command; http needs a url. Otherwise skip it
        # (mirrors the pre-existing "no command → skipped" contract that plugins rely on).
        if is_http:
            if not url:
                return None
        elif not cmd:
            return None
        raw_args = d.get("args") or []
        if not isinstance(raw_args, list):
            raw_args = []
        args = tuple(str(x) for x in raw_args)
        return cls(
            name=name,
            command=cmd,
            args=args,
            transport="http" if is_http else "stdio",
            url=url,
        )


# BL-153: MCP-only plugins — servers declared in a plugin's plugin.yaml `mcp_servers`
# block are registered here at load time and merged into the active server set.
_plugin_mcp_servers: list[dict[str, Any]] = []


def register_plugin_mcp_servers(servers: list[dict]) -> int:
    """Register MCP stdio servers contributed by plugins (idempotent by name)."""
    added = 0
    have = {s.get("name") for s in _plugin_mcp_servers}
    for s in servers or []:
        if isinstance(s, dict) and s.get("command") and s.get("name") not in have:
            _plugin_mcp_servers.append(dict(s))
            have.add(s.get("name"))
            added += 1
    return added


def clear_plugin_mcp_servers() -> None:
    _plugin_mcp_servers.clear()


def load_mcp_stdio_servers(cfg: dict) -> list[McpStdioServerSpec]:
    """Parse `mcp_stdio_servers` from config + any plugin-declared MCP servers."""
    if not cfg.get("mcp_client_enabled"):
        return []
    raw = cfg.get("mcp_stdio_servers")
    raw = raw if isinstance(raw, list) else []
    # Operator-configured servers (mcp_stdio_servers) run under mcp_client_enabled —
    # that is the operator's explicit choice. Plugin-DECLARED servers, however, ship a
    # subprocess command inside third-party plugin code, so they additionally require
    # plugin code-execution consent (plugins_enabled) — otherwise an untrusted plugin
    # could launch an arbitrary process the moment the MCP client is switched on.
    plugin_servers = list(_plugin_mcp_servers) if cfg.get("plugins_enabled") else []
    if _plugin_mcp_servers and not cfg.get("plugins_enabled"):
        logger.warning(
            "mcp_client: ignoring %d plugin-declared MCP server(s) because plugins_enabled is off",
            len(_plugin_mcp_servers),
        )
    out: list[McpStdioServerSpec] = []
    seen: set[str] = set()
    for i, item in enumerate([*raw, *plugin_servers]):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"server_{i}")
        if name in seen:
            continue
        spec = McpStdioServerSpec.from_dict(name, item)
        if spec:
            out.append(spec)
            seen.add(name)
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



def _raw_mcp_session_list_resources(
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



def _raw_mcp_session_read_resource(
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



def _raw_mcp_session_call_tool(
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



def _raw_mcp_session_list_tools(
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


# ─────────────────────────────────────────────────────────────────────────────
# Persistent SDK-backed sessions (Plan item 14).
#
# The raw `_raw_mcp_session_*` helpers above spawn a fresh subprocess, handshake,
# do one request, and tear the subprocess down — a full respawn PER CALL. When the
# official MCP Python SDK (`mcp`, v1.x) is installed we instead hold one persistent
# `ClientSession` per configured server and reuse the live connection across calls.
#
# Bridging sync callers (Layla's tool dispatch is synchronous) to the SDK's async
# `ClientSession` is done with a single dedicated asyncio loop running on a daemon
# thread. Each session is owned by exactly ONE long-lived "runner" coroutine that
# enters `stdio_client(...)` / `ClientSession(...)` and then parks on a close event —
# so the anyio context managers are entered and exited in the same task (anyio
# requires that). Individual calls are submitted onto the same loop with
# `run_coroutine_threadsafe`, so they reuse the already-open session.
#
# Degrade gracefully: if `mcp` is not importable, the public `mcp_session_*`
# functions fall back to the raw per-call path so nothing breaks.
# ─────────────────────────────────────────────────────────────────────────────

_SDK_CACHE: dict[str, Any] = {}


def _sdk() -> dict[str, Any] | None:
    """Lazily import the official MCP SDK client bits. Returns a dict of symbols, or None."""
    if "loaded" not in _SDK_CACHE:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            bits: dict[str, Any] = {
                "ClientSession": ClientSession,
                "StdioServerParameters": StdioServerParameters,
                "stdio_client": stdio_client,
                "streamablehttp_client": None,
            }
            try:
                from mcp.client.streamable_http import streamablehttp_client

                bits["streamablehttp_client"] = streamablehttp_client
            except Exception as e:  # optional transport; stdio still works
                logger.debug("mcp streamable-http client unavailable: %s", e)
            _SDK_CACHE["bits"] = bits
        except Exception as e:
            logger.debug("MCP SDK (mcp) not installed — using raw stdio fallback: %s", e)
            _SDK_CACHE["bits"] = None
        _SDK_CACHE["loaded"] = True
    return _SDK_CACHE.get("bits")


def _spec_key(spec: McpStdioServerSpec) -> tuple:
    return (spec.name, spec.transport, spec.command, spec.args, spec.url)


class _PersistentSession:
    """One live MCP ClientSession, kept open by a parked runner coroutine on the pool loop."""

    def __init__(self, spec: McpStdioServerSpec) -> None:
        self.spec = spec
        self.session: Any = None
        self.error: BaseException | None = None
        self._closed: Any = None  # asyncio.Event, created on the loop inside _run
        self._run_fut: Any = None  # concurrent.futures.Future for the runner
        self._ready = threading.Event()  # cross-thread: set once session is live or failed
        self._done = threading.Event()  # cross-thread: set once the runner has fully torn down

    async def _run(self, sdk: dict[str, Any], init_timeout_s: float) -> None:
        import asyncio

        self._closed = asyncio.Event()
        try:
            spec = self.spec
            if spec.is_http:
                client = sdk.get("streamablehttp_client")
                if client is None:
                    raise RuntimeError(
                        "streamable-http transport needs a newer mcp SDK (mcp.client.streamable_http)"
                    )
                transport_cm = client(spec.url)
            else:
                params = sdk["StdioServerParameters"](command=spec.command, args=list(spec.args))
                transport_cm = sdk["stdio_client"](params)
            async with transport_cm as streams:
                read, write = streams[0], streams[1]
                async with sdk["ClientSession"](read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=init_timeout_s)
                    self.session = session
                    self._ready.set()
                    await self._closed.wait()
        except BaseException as e:  # noqa: BLE001 — surface any init/transport failure to the caller
            self.error = e
            self._ready.set()
        finally:
            self.session = None
            self._done.set()


class _McpClientPool:
    """Process-wide pool of persistent MCP client sessions, one per configured server."""

    def __init__(self) -> None:
        self._loop: Any = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._sessions: dict[tuple, _PersistentSession] = {}
        self._sessions_lock = threading.Lock()
        # Observability for tests + diagnostics: how many real sessions/subprocesses we spawned.
        self.spawn_count = 0

    def _ensure_loop(self) -> Any:
        import asyncio

        with self._start_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()

            def _run_loop() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            t = threading.Thread(target=_run_loop, name="mcp-client-loop", daemon=True)
            t.start()
            self._loop = loop
            self._thread = t
            return loop

    def _live(self, sess: _PersistentSession | None) -> bool:
        return sess is not None and not sess._done.is_set() and sess.session is not None

    def _get_session(self, spec: McpStdioServerSpec, *, init_timeout_s: float) -> _PersistentSession:
        import asyncio

        key = _spec_key(spec)
        with self._sessions_lock:
            existing = self._sessions.get(key)
            if self._live(existing):
                return existing  # type: ignore[return-value]
            if existing is not None:
                self._sessions.pop(key, None)
                self._close_session(existing)
            loop = self._ensure_loop()
            sdk = _sdk()
            if sdk is None:
                raise RuntimeError("MCP SDK not available")
            sess = _PersistentSession(spec)
            sess._run_fut = asyncio.run_coroutine_threadsafe(
                sess._run(sdk, init_timeout_s), loop
            )
            if not sess._ready.wait(timeout=init_timeout_s + 2.0):
                self._close_session(sess)
                raise TimeoutError(f"mcp session init timed out for {spec.name!r}")
            if sess.error is not None:
                self._close_session(sess)
                raise sess.error
            self._sessions[key] = sess
            self.spawn_count += 1
            return sess

    def _close_session(self, sess: _PersistentSession) -> None:
        loop = self._loop
        try:
            if loop is not None and sess._closed is not None:
                loop.call_soon_threadsafe(sess._closed.set)
            elif loop is not None and sess._run_fut is not None:
                loop.call_soon_threadsafe(sess._run_fut.cancel)
        except Exception:
            pass
        sess._done.wait(timeout=5.0)

    def _run_coro(self, coro: Any, timeout_s: float) -> Any:
        import asyncio

        loop = self._loop
        if loop is None:
            raise RuntimeError("mcp client loop not running")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout_s)

    def _evict(self, spec: McpStdioServerSpec) -> None:
        key = _spec_key(spec)
        with self._sessions_lock:
            sess = self._sessions.pop(key, None)
        if sess is not None:
            self._close_session(sess)

    def call_tool(
        self, spec: McpStdioServerSpec, tool_name: str, arguments: dict[str, Any], *, timeout_s: float
    ) -> Any:
        sess = self._get_session(spec, init_timeout_s=timeout_s)
        try:
            return self._run_coro(sess.session.call_tool(tool_name, arguments or {}), timeout_s)
        except Exception:
            self._evict(spec)
            raise

    def list_tools(self, spec: McpStdioServerSpec, *, timeout_s: float) -> Any:
        sess = self._get_session(spec, init_timeout_s=timeout_s)
        try:
            return self._run_coro(sess.session.list_tools(), timeout_s)
        except Exception:
            self._evict(spec)
            raise

    def list_resources(self, spec: McpStdioServerSpec, *, timeout_s: float) -> Any:
        sess = self._get_session(spec, init_timeout_s=timeout_s)
        try:
            return self._run_coro(sess.session.list_resources(), timeout_s)
        except Exception:
            self._evict(spec)
            raise

    def read_resource(self, spec: McpStdioServerSpec, uri: str, *, timeout_s: float) -> Any:
        sess = self._get_session(spec, init_timeout_s=timeout_s)
        try:
            return self._run_coro(sess.session.read_resource(uri), timeout_s)
        except Exception:
            self._evict(spec)
            raise

    def close_all(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for sess in sessions:
            self._close_session(sess)
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        self._loop = None


_POOL = _McpClientPool()
# Tear persistent sessions (and their subprocesses) down on interpreter exit.
atexit.register(_POOL.close_all)


def _model_to_dict(result: Any) -> dict[str, Any]:
    """Convert an SDK pydantic result to the plain JSON-RPC-shaped dict callers expect."""
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json", by_alias=True)
        except Exception:
            pass
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


# ── Public session API — persistent SDK sessions when available, raw fallback otherwise ──


def mcp_session_call_tool(
    spec: McpStdioServerSpec,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """tools/call over a persistent, reused session (SDK) or a one-shot subprocess (fallback)."""
    arguments = arguments if isinstance(arguments, dict) else {}
    if _sdk() is not None:
        try:
            result = _POOL.call_tool(spec, tool_name, arguments, timeout_s=session_timeout_s)
            d = _model_to_dict(result)
            return {"ok": True, "mcp": d, "raw": d}
        except Exception as e:
            logger.warning("mcp_session_call_tool: SDK path failed for %r (%s); raw fallback", spec.name, e)
    return _raw_mcp_session_call_tool(
        spec, tool_name, arguments, line_timeout_s=line_timeout_s, session_timeout_s=session_timeout_s
    )


def mcp_session_list_tools(
    spec: McpStdioServerSpec,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """tools/list over a persistent, reused session (SDK) or a one-shot subprocess (fallback)."""
    if _sdk() is not None:
        try:
            result = _POOL.list_tools(spec, timeout_s=session_timeout_s)
            d = _model_to_dict(result)
            return {"ok": True, "mcp": d, "raw": d}
        except Exception as e:
            logger.warning("mcp_session_list_tools: SDK path failed for %r (%s); raw fallback", spec.name, e)
    return _raw_mcp_session_list_tools(spec, line_timeout_s=line_timeout_s, session_timeout_s=session_timeout_s)


def mcp_session_list_resources(
    spec: McpStdioServerSpec,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """resources/list over a persistent, reused session (SDK) or a one-shot subprocess (fallback)."""
    if _sdk() is not None:
        try:
            result = _POOL.list_resources(spec, timeout_s=session_timeout_s)
            d = _model_to_dict(result)
            return {"ok": True, "mcp": d, "raw": d}
        except Exception as e:
            logger.warning("mcp_session_list_resources: SDK path failed for %r (%s); raw fallback", spec.name, e)
    return _raw_mcp_session_list_resources(spec, line_timeout_s=line_timeout_s, session_timeout_s=session_timeout_s)


def mcp_session_read_resource(
    spec: McpStdioServerSpec,
    uri: str,
    *,
    line_timeout_s: float = 45.0,
    session_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """resources/read over a persistent, reused session (SDK) or a one-shot subprocess (fallback)."""
    uri = (uri or "").strip()
    if not uri:
        return {"ok": False, "error": "uri is required"}
    if _sdk() is not None:
        try:
            result = _POOL.read_resource(spec, uri, timeout_s=session_timeout_s)
            d = _model_to_dict(result)
            return {"ok": True, "mcp": d, "raw": d}
        except Exception as e:
            logger.warning("mcp_session_read_resource: SDK path failed for %r (%s); raw fallback", spec.name, e)
    return _raw_mcp_session_read_resource(
        spec, uri, line_timeout_s=line_timeout_s, session_timeout_s=session_timeout_s
    )


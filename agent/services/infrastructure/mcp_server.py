"""
Expose Layla AS an MCP server (Plan item 14, inbound direction).

Other agents / tools connect to this server and call a CURATED, SAFE subset of
Layla's registry tools plus her memory recall. Built on the official MCP Python
SDK (`mcp`, v1.x); imported lazily so the rest of the app runs without the extra.

SAFETY POSTURE (this is an inbound exposure — treat it as hostile-reachable):

  * OPT-IN. The whole server refuses to build unless ``mcp_server_enabled`` is
    true in config (default off). An inbound server is a real attack surface, so
    it must be switched on deliberately — never on by accident.

  * READ-ONLY ALLOWLIST. Only names in ``SAFE_MCP_TOOLS`` are ever exposed, and
    each is re-checked at expose time against the registry's own danger flags and
    the tool-permission WRITE/EXEC sets. A tool that is destructive (or later
    becomes destructive) is filtered out even if it is left in the allowlist —
    the allowlist can only ever SHRINK the exposed set, never smuggle a write in.

  * FORCED FAIL-CLOSED EXECUTION. Every MCP-originated call runs with
    ``allow_write=allow_run=False`` (via the thread-local tool-permission context
    AND ``run_tool(allow_run=False)``), mirroring the remote transports' stance.
    So even if a destructive tool somehow reached dispatch, the executor's
    backstop refuses it.

  * UNKNOWN TOOLS REFUSED. call_tool rejects anything outside the exposed set with
    an explicit error rather than attempting dispatch.
"""
from __future__ import annotations

import functools
import inspect
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_MAX_RESULT_CHARS = 200_000

# ── Curated safe surface ─────────────────────────────────────────────────────
# Read-ish, non-destructive tools + memory recall. This is an ALLOWLIST: a tool is
# exposed only if it is BOTH listed here AND passes the danger re-check in
# ``exposed_tool_names()``. Keep destructive tools (write_file/shell/run_python/
# git_commit/send_*/etc.) out — they must never be reachable over MCP.
SAFE_MCP_TOOLS: frozenset[str] = frozenset({
    # Memory recall (the headline inbound capability)
    "search_memories", "memory_search", "memory_get", "vector_search", "memory_stats",
    # Safe file / document reads
    "read_file", "list_dir", "tail_file", "file_info", "glob_files", "diff_files",
    "hash_file", "json_query", "yaml_read", "read_toml", "xml_parse",
    "read_pdf", "read_docx", "read_excel", "read_pptx", "read_notebook",
    "understand_file", "workspace_map",
    # Safe git reads (status/history/inspection only — no commit/push/clone)
    "git_status", "git_diff", "git_log", "git_branch", "git_blame",
})

_MEMORY_RECENT_URI = "layla://memory/recent"


def _server_sdk() -> dict[str, Any] | None:
    """Lazily import the official MCP SDK server bits. Returns a dict of symbols, or None."""
    try:
        import mcp.types as types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server

        return {"Server": Server, "stdio_server": stdio_server, "types": types}
    except Exception as e:
        logger.debug("MCP SDK (mcp) server bits unavailable: %s", e)
        return None


def _danger_sets() -> tuple[set[str], set[str], set[str]]:
    """(runtime_safety.DANGEROUS_TOOLS, WRITE_TOOLS, EXEC_TOOLS) — best-effort, never raises."""
    dangerous: set[str] = set()
    write_tools: set[str] = set()
    exec_tools: set[str] = set()
    try:
        import runtime_safety
        dangerous = set(getattr(runtime_safety, "DANGEROUS_TOOLS", []) or [])
    except Exception as e:
        logger.debug("mcp_server: could not read DANGEROUS_TOOLS: %s", e)
    try:
        from services.tools import tool_permissions as _tp
        write_tools = set(getattr(_tp, "_WRITE_TOOLS", frozenset()))
        exec_tools = set(getattr(_tp, "_EXEC_TOOLS", frozenset()))
    except Exception as e:
        logger.debug("mcp_server: could not read WRITE/EXEC tool sets: %s", e)
    return dangerous, write_tools, exec_tools


def exposed_tool_names() -> list[str]:
    """Names actually exposed over MCP: the allowlist ∩ (non-destructive, registered) tools.

    Defence-in-depth: even a name left in SAFE_MCP_TOOLS is dropped here if the registry marks
    it dangerous / require_approval, or if it appears in the WRITE/EXEC permission sets. The
    exposed set can therefore only ever be SAFER than the allowlist, never wider.
    """
    try:
        from layla.tools.registry import TOOLS
    except Exception as e:
        logger.warning("mcp_server: tool registry unavailable: %s", e)
        return []
    dangerous, write_tools, exec_tools = _danger_sets()
    out: list[str] = []
    for name in sorted(SAFE_MCP_TOOLS):
        entry = TOOLS.get(name)
        if not isinstance(entry, dict) or not entry.get("fn"):
            continue
        if entry.get("dangerous") or entry.get("require_approval"):
            logger.debug("mcp_server: dropping %r — registry marks it dangerous/require_approval", name)
            continue
        if name in dangerous or name in write_tools or name in exec_tools:
            logger.debug("mcp_server: dropping %r — present in a destructive tool set", name)
            continue
        out.append(name)
    return out


def _annotation_json_type(annotation: Any) -> str | None:
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}
    return mapping.get(annotation)


def _tool_input_schema(fn: Any) -> dict[str, Any]:
    """Derive a permissive JSON Schema from the tool function signature (discovery aid)."""
    props: dict[str, Any] = {}
    required: list[str] = []
    try:
        sig = inspect.signature(fn)
        for pname, p in sig.parameters.items():
            if pname == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            jtype = _annotation_json_type(p.annotation)
            props[pname] = {"type": jtype} if jtype else {}
            if p.default is inspect._empty:
                required.append(pname)
    except (TypeError, ValueError):
        pass
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _run_safe_tool(tool_name: str, arguments: dict[str, Any], sandbox_root: str) -> dict[str, Any]:
    """Execute one exposed tool with MCP's forced read-only permission context.

    Runs on a worker thread (offloaded by the async handler). Sets the thread-local
    tool-permission context to allow_write=allow_run=False so the executor's backstop
    refuses anything destructive, then dispatches through the standard executor.
    """
    from core.executor import run_tool
    try:
        from services.tools.tool_permissions import clear_tool_permissions, set_tool_permissions
        set_tool_permissions(allow_write=False, allow_run=False)
        _have_ctx = True
    except Exception:
        _have_ctx = False
    try:
        return run_tool(tool_name, arguments, sandbox_root=sandbox_root or None, allow_run=False)
    finally:
        if _have_ctx:
            try:
                clear_tool_permissions()
            except Exception:
                pass


def build_layla_mcp_server(cfg: dict[str, Any] | None = None, *, force: bool = False) -> Any:
    """Build the inbound MCP server exposing Layla's safe tools + memory recall.

    Raises RuntimeError if the SDK is missing, or if ``mcp_server_enabled`` is off
    (unless ``force`` — used only for in-process tests, never by the CLI entry).
    """
    sdk = _server_sdk()
    if sdk is None:
        raise RuntimeError(
            "MCP SDK not installed. Install the optional extra: pip install 'mcp>=1.0,<2.0'"
        )
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    if not force and not cfg.get("mcp_server_enabled"):
        raise RuntimeError(
            "mcp_server_enabled is off — inbound MCP server refused. "
            "Set mcp_server_enabled: true in runtime_config.json to opt in (default off by design)."
        )

    Server = sdk["Server"]
    types = sdk["types"]
    exposed = exposed_tool_names()
    sandbox_root = ""
    try:
        raw_root = str(cfg.get("sandbox_root") or "").strip()
        if raw_root:
            sandbox_root = str(Path(raw_root).expanduser())
    except Exception:
        sandbox_root = ""

    server = Server(
        "layla",
        version="1.0.0",
        instructions=(
            "Layla exposes a read-only subset of her capabilities over MCP: memory recall "
            "and safe file/git inspection tools. All calls run fail-closed (no writes, no "
            "code execution)."
        ),
    )

    async def _list_tools() -> list[Any]:
        from layla.tools.registry import TOOLS
        tools = []
        for name in exposed:
            entry = TOOLS.get(name) or {}
            desc = str(entry.get("description") or name)
            tools.append(
                types.Tool(
                    name=name,
                    description=desc,
                    inputSchema=_tool_input_schema(entry.get("fn")),
                )
            )
        return tools

    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[Any]:
        import anyio

        if name not in exposed:
            payload = {"ok": False, "error": f"tool {name!r} is not exposed over MCP"}
            return [types.TextContent(type="text", text=json.dumps(payload))]
        result = await anyio.to_thread.run_sync(
            functools.partial(_run_safe_tool, name, dict(arguments or {}), sandbox_root)
        )
        text = json.dumps(result, default=str)[:_MAX_RESULT_CHARS]
        return [types.TextContent(type="text", text=text)]

    async def _list_resources() -> list[Any]:
        return [
            types.Resource(
                uri=_MEMORY_RECENT_URI,
                name="Layla recent memory",
                description="Layla's recent stored learnings (read-only memory recall).",
                mimeType="application/json",
            )
        ]

    async def _read_resource(uri: Any) -> str:
        import anyio

        if str(uri) != _MEMORY_RECENT_URI:
            raise ValueError(f"unknown resource {uri!r}")
        recall_tool = "search_memories" if "search_memories" in exposed else (
            exposed[0] if exposed else ""
        )
        if not recall_tool:
            return json.dumps({"ok": False, "error": "no memory recall tool available"})
        result = await anyio.to_thread.run_sync(
            functools.partial(_run_safe_tool, recall_tool, {"query": "recent", "n": 10}, sandbox_root)
        )
        return json.dumps(result, default=str)[:_MAX_RESULT_CHARS]

    # Register the handlers functionally (not via @decorator syntax): referencing each handler
    # by name here is what keeps them live for the symbol-liveness gate, which does not know the
    # MCP SDK's decorators register them. validate_input=False on call_tool — the tool functions
    # and the executor validate their own args and return structured errors, so we do not want the
    # SDK rejecting a call against a permissively-derived schema.
    server.list_tools()(_list_tools)
    server.call_tool(validate_input=False)(_call_tool)
    server.list_resources()(_list_resources)
    server.read_resource()(_read_resource)

    return server


def run_stdio(server: Any) -> None:
    """Serve the given MCP server over stdio (blocking). Used by the standalone CLI entry."""
    import anyio

    sdk = _server_sdk()
    if sdk is None:
        raise RuntimeError("MCP SDK not installed")
    stdio_server = sdk["stdio_server"]

    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_serve)

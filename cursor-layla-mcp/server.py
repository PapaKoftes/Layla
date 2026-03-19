"""MCP server for Cursor <-> local Layla integration.

Run with:
    python cursor-layla-mcp/server.py
"""
import anyio
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

LAYLA_BASE = os.environ.get("LAYLA_BASE_URL", "http://127.0.0.1:8000")


def _infer_workspace_root() -> str:
    """Use provided workspace_root if present; else infer repo root (git top-level or cwd)."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def _normalize_workspace_root(workspace_root: str) -> str:
    wr = (workspace_root or "").strip() or _infer_workspace_root()
    try:
        return str(Path(wr).expanduser().resolve())
    except Exception:
        return wr


app = Server("layla")


def _post(url: str, body: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _agent_sync(payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    return _post(LAYLA_BASE + "/agent", payload, timeout=timeout)


def _agent_stream_sync(payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    """Call /agent with stream=true and collect SSE chunks into final text + metadata."""
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    req = urllib.request.Request(
        LAYLA_BASE + "/agent",
        data=json.dumps(stream_payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    text_parts: list[str] = []
    tool_starts: list[str] = []
    ux_states: list[str] = []
    done_obj: dict[str, Any] = {}
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            try:
                obj = json.loads(data_str)
            except Exception:
                continue
            tok = obj.get("token")
            if isinstance(tok, str):
                text_parts.append(tok)
            tool = obj.get("tool_start")
            if isinstance(tool, str):
                tool_starts.append(tool)
            ux = obj.get("ux_state")
            if isinstance(ux, str):
                ux_states.append(ux)
            if obj.get("done"):
                done_obj = obj
                break
    content = done_obj.get("content")
    if not isinstance(content, str):
        content = "".join(text_parts)
    return {
        "response": content,
        "tool_starts": tool_starts,
        "ux_states": done_obj.get("ux_states", ux_states),
        "memory_influenced": done_obj.get("memory_influenced", []),
        "reasoning_mode": done_obj.get("reasoning_mode"),
    }


def _format_tool_trace(state: dict[str, Any]) -> str:
    steps = (state or {}).get("steps") or []
    if not isinstance(steps, list) or not steps:
        return ""
    lines = ["", "Tool trace:"]
    for s in steps[:25]:
        action = s.get("action", "?")
        result = s.get("result")
        snippet = json.dumps(result, ensure_ascii=False)[:220] if isinstance(result, (dict, list)) else str(result)[:220]
        lines.append(f"- {action}: {snippet}")
    if len(steps) > 25:
        lines.append(f"- ... ({len(steps) - 25} more steps)")
    return "\n".join(lines)


def _learn_sync(content: str, learning_type: str = "fact") -> str:
    data = _post(LAYLA_BASE + "/learn/", {"content": content, "type": learning_type}, timeout=30)
    if data.get("ok"):
        return data.get("message", "Saved.")
    return data.get("error", "Failed.")


@app.list_tools()
async def handle_list_tools() -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="chat_with_layla",
                title="Chat with Layla",
                description=(
                    "Send a message to your local Layla agent. She can read files, "
                    "list dirs, and optionally write/run commands. Always pass 'context' "
                    "(open files, selected code) so she can work on what you have open. "
                    "Set allow_write/allow_run true only if you explicitly asked her to "
                    "edit or run something."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The user's message or question to Layla.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Workspace context: open file paths and contents, or selected code.",
                        },
                        "workspace_root": {
                            "type": "string",
                            "description": "Root path for Layla's file/command tools (e.g. ~/projects/myrepo).",
                        },
                        "allow_write": {
                            "type": "boolean",
                            "description": "If true, Layla may write files. Set only when user asked for edits.",
                            "default": False,
                        },
                        "allow_run": {
                            "type": "boolean",
                            "description": "If true, Layla may run shell commands. Set only when user asked for execution.",
                            "default": False,
                        },
                        "aspect_id": {
                            "type": "string",
                            "description": "Aspect to invoke: morrigan (engineer), nyx (researcher), echo (companion), eris (chaos/banter), cassandra (unfiltered oracle/reactive), lilith (ethics/core/nsfw). Leave empty for auto-select.",
                            "default": "",
                        },
                        "show_thinking": {
                            "type": "boolean",
                            "description": "If true, Layla deliberates across aspects before answering. Use for complex decisions.",
                            "default": False,
                        },
                        "stream": {
                            "type": "boolean",
                            "description": "If true, use Layla SSE streaming and return the assembled response.",
                            "default": False,
                        },
                        "include_trace": {
                            "type": "boolean",
                            "description": "If true, include tool trace from state.steps in the returned text.",
                            "default": True,
                        },
                    },
                },
            ),
            types.Tool(
                name="add_learning",
                title="Teach Layla (add learning)",
                description=(
                    "Add a fact, preference, or correction to Layla's long-term memory. "
                    "Use when the user says 'remember this', 'learn this', or 'add to your memory'. "
                    "Layla grows over time."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "What to remember: fact, preference, correction, or instruction.",
                        },
                        "type": {
                            "type": "string",
                            "description": "One of: fact, preference, correction. Default: fact.",
                            "default": "fact",
                        },
                    },
                },
            ),
            types.Tool(
                name="get_context",
                title="Collect workspace context",
                description=(
                    "Build a context bundle for Cursor-native prompts using current selection, file content, "
                    "and optional project context from Layla."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workspace_root": {"type": "string", "description": "Workspace root path."},
                        "path": {"type": "string", "description": "Optional file path to include."},
                        "selected_text": {"type": "string", "description": "Optional selected text from editor."},
                        "include_project_context": {"type": "boolean", "default": True},
                    },
                },
            ),
            types.Tool(
                name="search_workspace",
                title="Search workspace codebase",
                description=(
                    "Run Layla code search for a symbol/query using the workspace index and search_codebase capability."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Symbol name or short code query."},
                        "workspace_root": {"type": "string", "description": "Workspace root path."},
                        "k": {"type": "integer", "description": "Result budget hint.", "default": 6},
                        "context": {"type": "string", "description": "Optional extra context."},
                    },
                },
            ),
            types.Tool(
                name="apply_patch",
                title="Apply patch via Layla",
                description=(
                    "Ask Layla to apply a unified patch to a file. This goes through Layla approval policy "
                    "and returns the execution trace."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["original_path", "patch_text"],
                    "properties": {
                        "original_path": {"type": "string", "description": "Target file path."},
                        "patch_text": {"type": "string", "description": "Unified patch body."},
                        "workspace_root": {"type": "string", "description": "Workspace root path."},
                        "dry_run": {"type": "boolean", "default": False, "description": "If true, request analysis only (no write)."},
                    },
                },
            ),
            types.Tool(
                name="start_study_session",
                title="Start a study session with Layla",
                description=(
                    "Ask Layla to run a focused study session on a topic. She will explain "
                    "key concepts, suggest resources, create a study plan, and check "
                    "the workspace for related code."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["topic"],
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The topic to study (e.g. 'asyncio in Python', 'SQLite full-text search').",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional: open files, selected code, or repo summary.",
                        },
                        "workspace_root": {
                            "type": "string",
                            "description": "Optional: root path for the current workspace.",
                        },
                    },
                },
            ),
            types.Tool(
                name="analyze_repo_for_study",
                title="Ask Layla what to study for this repo",
                description=(
                    "Ask Layla to analyze a repository and suggest study topics, "
                    "identify knowledge gaps, and prioritize what to learn next."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["workspace_root"],
                    "properties": {
                        "workspace_root": {
                            "type": "string",
                            "description": "Root path of the repository to analyze.",
                        },
                    },
                },
            ),
            types.Tool(
                name="get_pending_approvals",
                title="Get Layla's pending approvals",
                description=(
                    "List all actions Layla is waiting for approval on. "
                    "Returns a list of pending approval IDs and what action each is for."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="approve_action",
                title="Approve a Layla action",
                description=(
                    "Approve a pending Layla action by its ID. "
                    "Use get_pending_approvals to see what's waiting. "
                    "This lets Layla proceed with file writes, code execution, or shell commands."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["approval_id"],
                    "properties": {
                        "approval_id": {
                            "type": "string",
                            "description": "The approval UUID from get_pending_approvals.",
                        },
                    },
                },
            ),
            types.Tool(
                name="get_memories",
                title="Search Layla's memories",
                description=(
                    "Search Layla's long-term memory (learnings, semantic recall) for relevant past knowledge. "
                    "Use when you need to recall what Layla has learned or what the user told her."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for relevant memories.",
                        },
                        "n": {
                            "type": "integer",
                            "description": "Max number of memories to return. Default 8.",
                            "default": 8,
                        },
                    },
                },
            ),
            types.Tool(
                name="schedule_layla_task",
                title="Schedule a Layla task",
                description=(
                    "Schedule a tool to run in the background: once after delay, or recurring via cron. "
                    "Use schedule_task tool on Layla's side. Requires Layla API to support it."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["tool_name"],
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Tool name to run (e.g. discord_send, run_tests).",
                        },
                        "args": {
                            "type": "object",
                            "description": "Arguments for the tool as JSON.",
                            "default": {},
                        },
                        "delay_seconds": {
                            "type": "number",
                            "description": "Run once after N seconds. Default 0.",
                            "default": 0,
                        },
                        "cron_expr": {
                            "type": "string",
                            "description": "Cron: 'min hour dom month dow' e.g. '*/5 * * * *' for every 5 min.",
                            "default": "",
                        },
                    },
                },
            ),
        ]
    )


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    args = arguments or {}

    # ── add_learning ──────────────────────────────────────
    if name == "add_learning":
        content = args.get("content", "").strip()
        kind = args.get("type", "fact") or "fact"
        if not content:
            return [types.TextContent(type="text", text="No content to learn.")]
        try:
            result = await anyio.to_thread.run_sync(
                lambda: _learn_sync(content, kind)
            )
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Learn failed: {e}")]

    # ── chat_with_layla ───────────────────────────────────
    if name == "chat_with_layla":
        message = args.get("message", "")
        if not message:
            return [types.TextContent(type="text", text="No message provided.")]
        context = args.get("context", "") or ""
        workspace_root = args.get("workspace_root", "") or ""
        allow_write = args.get("allow_write") is True
        allow_run = args.get("allow_run") is True
        aspect_id = args.get("aspect_id", "") or ""
        show_thinking = bool(args.get("show_thinking", False))
        stream = bool(args.get("stream", False))
        include_trace = bool(args.get("include_trace", True))
        payload = {
            "message": message,
            "context": context,
            "workspace_root": _normalize_workspace_root(workspace_root),
            "allow_write": allow_write,
            "allow_run": allow_run,
            "aspect_id": aspect_id,
            "show_thinking": show_thinking,
        }
        try:
            if stream:
                data = await anyio.to_thread.run_sync(lambda: _agent_stream_sync(payload))
            else:
                data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload))
            response = data.get("response", "")
            if include_trace:
                state = data.get("state") or {}
                response = (response or "") + _format_tool_trace(state)
            return [types.TextContent(type="text", text=response or "")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Layla unreachable: {e}. Is the server running on port 8000?")]

    # ── get_context ───────────────────────────────────────
    if name == "get_context":
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        selected_text = (args.get("selected_text", "") or "").strip()
        path = (args.get("path", "") or "").strip()
        include_project_context = bool(args.get("include_project_context", True))
        chunks: list[str] = [f"workspace_root: {workspace_root}"]
        if path:
            try:
                q = urllib.parse.urlencode({"path": path})
                fc = _get(f"{LAYLA_BASE}/file_content?{q}")
                if fc.get("exists"):
                    chunks.append(f"file_path: {fc.get('path') or path}")
                    chunks.append("file_content:\n" + (fc.get("content") or "")[:12000])
                else:
                    chunks.append(f"file_path: {path} (not found)")
            except Exception as e:
                chunks.append(f"file_context_error: {e}")
        if selected_text:
            chunks.append("selected_text:\n" + selected_text[:8000])
        if include_project_context:
            try:
                pc = _get(LAYLA_BASE + "/project_context")
                chunks.append("project_context:\n" + json.dumps(pc, ensure_ascii=False)[:8000])
            except Exception as e:
                chunks.append(f"project_context_error: {e}")
        return [types.TextContent(type="text", text="\n\n".join(chunks))]

    # ── search_workspace ──────────────────────────────────
    if name == "search_workspace":
        query = (args.get("query", "") or "").strip()
        if not query:
            return [types.TextContent(type="text", text="No query provided.")]
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        k = int(args.get("k") or 6)
        context = (args.get("context", "") or "").strip()
        try:
            # Keep the workspace index fresh; best-effort.
            await anyio.to_thread.run_sync(lambda: _post(LAYLA_BASE + "/workspace/index", {"workspace_root": workspace_root}, timeout=60))
        except Exception:
            pass
        msg = (
            "Use the search_codebase/code intelligence tools to search the workspace for this symbol/query: "
            f"{query}\n"
            f"Return concise results with file paths and why each result is relevant. Limit roughly {max(2, min(20, k))} items."
        )
        payload = {
            "message": msg,
            "context": context,
            "workspace_root": workspace_root,
            "allow_write": False,
            "allow_run": False,
            "aspect_id": "morrigan",
            "show_thinking": False,
        }
        try:
            data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload, timeout=240))
            text = (data.get("response") or "") + _format_tool_trace(data.get("state") or {})
            return [types.TextContent(type="text", text=text or "No results.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"search_workspace failed: {e}")]

    # ── apply_patch ───────────────────────────────────────
    if name == "apply_patch":
        original_path = (args.get("original_path", "") or "").strip()
        patch_text = args.get("patch_text", "")
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        dry_run = bool(args.get("dry_run", False))
        if not original_path or not patch_text:
            return [types.TextContent(type="text", text="original_path and patch_text are required.")]
        if dry_run:
            msg = (
                "Analyze this patch for correctness and safety only. Do not write files.\n"
                f"Target: {original_path}\nPatch:\n{patch_text}"
            )
            allow_write = False
        else:
            msg = (
                "Apply this patch using the apply_patch tool.\n"
                f"Target: {original_path}\nPatch:\n{patch_text}"
            )
            allow_write = True
        payload = {
            "message": msg,
            "workspace_root": workspace_root,
            "allow_write": allow_write,
            "allow_run": False,
            "aspect_id": "morrigan",
            "show_thinking": False,
        }
        try:
            data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload, timeout=300))
            text = (data.get("response") or "") + _format_tool_trace(data.get("state") or {})
            return [types.TextContent(type="text", text=text or "No response.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"apply_patch failed: {e}")]

    # ── start_study_session ───────────────────────────────
    if name == "start_study_session":
        topic = args.get("topic", "").strip()
        if not topic:
            return [types.TextContent(type="text", text="No topic provided.")]
        context = args.get("context", "") or ""
        workspace_root = args.get("workspace_root", "") or ""
        try:
            _post(LAYLA_BASE + "/study_plans", {"topic": topic}, timeout=10)
        except Exception:
            pass
        message = (
            f"Study session on: {topic}.\n"
            "1. Explain the key concepts clearly.\n"
            "2. List the most important things to understand.\n"
            "3. Suggest 3-5 good resources (docs, tutorials, examples).\n"
            "4. Create a short study plan (steps to learn this well).\n"
            "5. If a workspace is provided, check for related code and mention how it connects."
        )
        try:
            response = await anyio.to_thread.run_sync(
                lambda: _chat_sync(message, context, workspace_root, False, False)
            )
            if response and isinstance(response, str) and response.strip():
                try:
                    _post(
                        LAYLA_BASE + "/study_plans/record_progress",
                        {"topic": topic, "note": response.strip()[:500]},
                        timeout=10,
                    )
                except Exception:
                    pass
            return [types.TextContent(type="text", text=response or "")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Study session failed: {e}")]

    # ── analyze_repo_for_study ────────────────────────────
    if name == "analyze_repo_for_study":
        workspace_root = args.get("workspace_root", "").strip()
        if not workspace_root:
            return [types.TextContent(type="text", text="No workspace_root provided.")]
        message = (
            f"Analyze the repository at: {workspace_root}\n"
            "1. List the main programming languages and frameworks used.\n"
            "2. List the key libraries (from imports, requirements, package.json, etc.).\n"
            "3. Identify the main patterns or architectural decisions.\n"
            "4. Identify 3-5 knowledge gaps someone working on this repo might have.\n"
            "5. Suggest a prioritized study plan. List each suggested study topic on its own line, "
            "each line starting with a number (e.g. 1. ), a bullet (- or *), or 'Topic: '. "
            "Example:\n1. Python asyncio\n2. FastAPI\n- SQLite\nTopic: REST API design"
        )
        try:
            response = await anyio.to_thread.run_sync(
                lambda: _chat_sync(message, "", workspace_root, False, False)
            )
            # Parse response for study topics and create study plans via API
            topics = []
            for line in (response or "").splitlines():
                line = line.strip()
                if not line or len(line) < 2:
                    continue
                if line[0].isdigit():
                    rest = line.lstrip("0123456789.) ")
                    if rest:
                        topics.append(rest.strip())
                    continue
                if line.startswith("-") or line.startswith("*"):
                    rest = line.lstrip("-* ").strip()
                    if rest:
                        topics.append(rest)
                    continue
                if line.lower().startswith("topic:"):
                    rest = line[6:].strip()
                    if rest:
                        topics.append(rest)
            seen = set()
            unique = []
            for t in topics:
                k = t.lower().strip()
                if k and k not in seen and len(t) < 200:
                    seen.add(k)
                    unique.append(t)
            for topic in unique[:10]:
                try:
                    _post(LAYLA_BASE + "/study_plans", {"topic": topic}, timeout=10)
                except Exception:
                    pass
            return [types.TextContent(type="text", text=response)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Repo analysis failed: {e}")]

    # ── get_pending_approvals ─────────────────────────────
    if name == "get_pending_approvals":
        try:
            resp = _get(LAYLA_BASE + "/approvals")
            items = resp.get("approvals") or resp.get("items") or []
            if not items:
                return [types.TextContent(type="text", text="No pending approvals.")]
            lines = []
            for item in items:
                lines.append(f"ID: {item.get('id','?')}  tool: {item.get('tool','?')}  args: {str(item.get('args',''))[:80]}")
            return [types.TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Could not fetch approvals: {e}")]

    # ── approve_action ────────────────────────────────────
    if name == "approve_action":
        approval_id = args.get("approval_id", "").strip()
        if not approval_id:
            return [types.TextContent(type="text", text="No approval_id provided.")]
        try:
            result = _post(LAYLA_BASE + "/approve", {"id": approval_id})
            ok = result.get("ok") or result.get("status") == "approved"
            msg = "Approved." if ok else f"Approval failed: {result}"
            return [types.TextContent(type="text", text=msg)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Approve failed: {e}")]

    # ── get_memories ───────────────────────────────────────
    if name == "get_memories":
        query = args.get("query", "").strip()
        if not query:
            return [types.TextContent(type="text", text="No query provided.")]
        n = int(args.get("n") or 8)
        try:
            import urllib.parse
            url = LAYLA_BASE + "/memories?" + urllib.parse.urlencode({"q": query, "n": n})
            resp = _get(url)
            items = resp.get("memories") or []
            if not items:
                return [types.TextContent(type="text", text="No relevant memories found.")]
            return [types.TextContent(type="text", text="\n".join(f"- {m}" for m in items[:n]))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Memory search failed: {e}")]

    # ── schedule_layla_task ─────────────────────────────────
    if name == "schedule_layla_task":
        tool_name = args.get("tool_name", "").strip()
        if not tool_name:
            return [types.TextContent(type="text", text="No tool_name provided.")]
        try:
            result = _post(LAYLA_BASE + "/schedule", {
                "tool_name": tool_name,
                "args": args.get("args") or {},
                "delay_seconds": float(args.get("delay_seconds") or 0),
                "cron_expr": (args.get("cron_expr") or "").strip(),
            })
            if result.get("ok"):
                return [types.TextContent(type="text", text=f"Scheduled: {result.get('job_id', '?')} ({result.get('schedule', '')})")]
            return [types.TextContent(type="text", text=f"Schedule failed: {result.get('error', result)}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Schedule failed: {e}")]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


def main() -> int:
    async def arun():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    anyio.run(arun)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

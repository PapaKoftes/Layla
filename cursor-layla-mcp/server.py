"""MCP server for Cursor <-> local Layla integration.

Run with:
    python cursor-layla-mcp/server.py
"""
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import anyio
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


def _chat_sync(
    message: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    aspect_id: str = "",
) -> str:
    """Simple synchronous chat wrapper used internally by study/analyze tools."""
    payload = {
        "message": message,
        "context": context,
        "workspace_root": _normalize_workspace_root(workspace_root),
        "allow_write": allow_write,
        "allow_run": allow_run,
        "aspect_id": aspect_id,
    }
    data = _agent_sync(payload, timeout=300)
    return data.get("response", "")


@app.list_tools()
async def handle_list_tools() -> types.ListToolsResult:
    from tool_definitions import build_tools_result
    return build_tools_result()


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
        persona_focus = str(args.get("persona_focus", "") or "").strip()
        show_thinking = bool(args.get("show_thinking", False))
        stream = bool(args.get("stream", False))
        include_trace = bool(args.get("include_trace", True))
        _epm = str(args.get("engineering_pipeline_mode", "") or "").strip().lower()
        _cr = str(args.get("clarification_reply", "") or "").strip()
        payload = {
            "message": message,
            "context": context,
            "workspace_root": _normalize_workspace_root(workspace_root),
            "allow_write": allow_write,
            "allow_run": allow_run,
            "aspect_id": aspect_id,
            "persona_focus": persona_focus,
            "show_thinking": show_thinking,
        }
        if _epm in ("chat", "plan", "execute"):
            payload["engineering_pipeline_mode"] = _epm
        if _cr:
            payload["clarification_reply"] = _cr
        try:
            if stream:
                data = await anyio.to_thread.run_sync(lambda: _agent_stream_sync(payload))
            else:
                data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload))
            response = data.get("response", "")
            state = data.get("state") or {}
            if state.get("status") == "pipeline_needs_input":
                qs = state.get("questions") or []
                if isinstance(qs, list) and qs:
                    response = (
                        (response or "")
                        + "\n\n[Pipeline needs input — send clarification_reply on next call with same goal]\n"
                        + "\n".join(str(q) for q in qs if str(q).strip())
                    )
            if include_trace:
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
            resp = _get(LAYLA_BASE + "/pending")
            items = resp.get("pending") or resp.get("items") or []
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
            payload = {
                "tool_name": tool_name,
                "args": args.get("args") or {},
                "delay_seconds": float(args.get("delay_seconds") or 0),
                "cron_expr": (args.get("cron_expr") or "").strip(),
            }
            try:
                result = _post(LAYLA_BASE + "/schedule", payload)
            except Exception:
                # Compatibility fallback for deployments mounting router under /agent.
                result = _post(LAYLA_BASE + "/agent/schedule", payload)
            if result.get("ok"):
                return [types.TextContent(type="text", text=f"Scheduled: {result.get('job_id', '?')} ({result.get('schedule', '')})")]
            return [types.TextContent(type="text", text=f"Schedule failed: {result.get('error', result)}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Schedule failed: {e}")]

    # ── layla_status ──────────────────────────────────────
    if name == "layla_status":
        try:
            data = _get(LAYLA_BASE + "/version", timeout=5)
            version = data.get("version", "?")
            health = _get(LAYLA_BASE + "/health", timeout=5)
            model_loaded = health.get("model_loaded", False)
            uptime = round(float(health.get("uptime_seconds", 0)), 1)
            status = health.get("status", "?")
            lines = [
                f"Layla is UP (v{version})",
                f"Status: {status}",
                f"Model loaded: {model_loaded}",
                f"Uptime: {uptime}s",
                f"Tools registered: {health.get('tools_registered', '?')}",
                f"Learnings: {health.get('learnings', '?')}",
            ]
            return [types.TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Layla appears to be DOWN or unreachable: {e}\nStart with: cd agent && uvicorn main:app --host 127.0.0.1 --port 8000")]

    # ── layla_wakeup ──────────────────────────────────────
    if name == "layla_wakeup":
        try:
            data = _get(LAYLA_BASE + "/wakeup", timeout=30)
            greeting = data.get("greeting") or data.get("message") or ""
            plans = data.get("study_plans") or []
            lines = []
            if greeting:
                lines.append(greeting)
            if plans:
                lines.append(f"\nActive study plans ({len(plans)}):")
                for p in plans[:5]:
                    lines.append(f"  - {p.get('topic', '?')} [{p.get('status', '?')}]")
            return [types.TextContent(type="text", text="\n".join(lines) or "Wakeup complete.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Wakeup failed: {e}")]

    # ── layla_health ──────────────────────────────────────
    if name == "layla_health":
        deep = bool(args.get("deep", False))
        url = LAYLA_BASE + ("/health?deep=true" if deep else "/health")
        try:
            data = _get(url, timeout=30)
            import json as _json
            return [types.TextContent(type="text", text=_json.dumps(data, indent=2, ensure_ascii=False))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Health check failed: {e}")]

    # ── deliberate ────────────────────────────────────────
    if name == "deliberate":
        question = (args.get("question", "") or "").strip()
        if not question:
            return [types.TextContent(type="text", text="No question provided.")]
        context = args.get("context", "") or ""
        workspace_root = args.get("workspace_root", "") or ""
        msg = f"Show me your thinking. Deliberate on this: {question}"
        payload = {
            "message": msg,
            "context": context,
            "workspace_root": _normalize_workspace_root(workspace_root),
            "allow_write": False,
            "allow_run": False,
            "aspect_id": "",
            "show_thinking": True,
        }
        try:
            data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload, timeout=300))
            return [types.TextContent(type="text", text=data.get("response", "") or "No response.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Deliberation failed: {e}")]

    # ── run_code ──────────────────────────────────────────
    if name == "run_code":
        code = (args.get("code", "") or "").strip()
        if not code:
            return [types.TextContent(type="text", text="No code provided.")]
        workspace_root = args.get("workspace_root", "") or ""
        msg = f"Run this Python code using the run_python tool and return the output:\n```python\n{code}\n```"
        payload = {
            "message": msg,
            "workspace_root": _normalize_workspace_root(workspace_root),
            "allow_write": False,
            "allow_run": True,
            "aspect_id": "morrigan",
            "show_thinking": False,
        }
        try:
            data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload, timeout=120))
            text = (data.get("response") or "") + _format_tool_trace(data.get("state") or {})
            return [types.TextContent(type="text", text=text or "No output.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"run_code failed: {e}")]

    # ── get_model_catalog ─────────────────────────────────
    if name == "get_model_catalog":
        category_filter = (args.get("category", "") or "").strip().lower()
        try:
            import json as _json
            cat_path = Path(__file__).resolve().parent.parent / "agent" / "models" / "model_catalog.json"
            catalog = _json.loads(cat_path.read_text(encoding="utf-8"))
            models = catalog.get("models", [])
            if category_filter:
                models = [m for m in models if (m.get("category") or "").lower() == category_filter]
            lines = [f"{'Name':<45} {'Cat':<10} {'Size':<8} {'VRAM':>5}GB  {'Uncensored':<12} Description"]
            lines.append("-" * 120)
            for m in models:
                unc = "YES" if m.get("uncensored") else "no"
                rec = " ★" if m.get("recommended") else ""
                lines.append(
                    f"{(m['name'] + rec):<45} {(m.get('category') or ''):<10} {(m.get('size') or ''):<8} "
                    f"{str(m.get('vram_required', '?')):>5}    {unc:<12} {m.get('desc', '')}"
                )
            return [types.TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Catalog load failed: {e}")]

    # ── ask_aspect ────────────────────────────────────────
    if name == "ask_aspect":
        aspect = (args.get("aspect", "") or "").strip().lower()
        message = (args.get("message", "") or "").strip()
        if not aspect or not message:
            return [types.TextContent(type="text", text="aspect and message are required.")]
        context = args.get("context", "") or ""
        workspace_root = args.get("workspace_root", "") or ""
        allow_write = args.get("allow_write") is True
        allow_run = args.get("allow_run") is True
        stream = bool(args.get("stream", False))
        payload = {
            "message": message,
            "context": context,
            "workspace_root": _normalize_workspace_root(workspace_root),
            "allow_write": allow_write,
            "allow_run": allow_run,
            "aspect_id": aspect,
            "show_thinking": False,
        }
        try:
            if stream:
                data = await anyio.to_thread.run_sync(lambda: _agent_stream_sync(payload))
            else:
                data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload))
            return [types.TextContent(type="text", text=data.get("response", "") or "")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"ask_aspect failed: {e}")]

    # ── delegate_task ─────────────────────────────────────
    # Send a task to Layla as a background agent job. Returns a task_id.
    # Cursor AI (or another agent) can then poll with poll_task.
    if name == "delegate_task":
        goal = (args.get("goal", "") or "").strip()
        if not goal:
            return [types.TextContent(type="text", text="goal is required.")]
        aspect_id = (args.get("aspect_id", "") or "").strip()
        allow_write = args.get("allow_write") is True
        allow_run = args.get("allow_run") is True
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        context = (args.get("context", "") or "").strip()
        try:
            payload = {
                "message": goal,
                "context": context,
                "workspace_root": workspace_root,
                "allow_write": allow_write,
                "allow_run": allow_run,
                "aspect_id": aspect_id or "morrigan",
                "background": True,
            }
            result = _post(LAYLA_BASE + "/agent/tasks", payload, timeout=15)
            task_id = result.get("task_id") or result.get("id")
            if task_id:
                return [types.TextContent(
                    type="text",
                    text=f"Task delegated. task_id={task_id}\nUse poll_task to check status.",
                )]
            # Fallback: run synchronously if background tasks not supported
            data = await anyio.to_thread.run_sync(
                lambda: _agent_sync({
                    "message": goal,
                    "context": context,
                    "workspace_root": workspace_root,
                    "allow_write": allow_write,
                    "allow_run": allow_run,
                    "aspect_id": aspect_id or "morrigan",
                }, timeout=300)
            )
            return [types.TextContent(type="text", text=data.get("response", "") or "Task completed.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"delegate_task failed: {e}")]

    # ── poll_task ──────────────────────────────────────────
    if name == "poll_task":
        task_id = (args.get("task_id", "") or "").strip()
        if not task_id:
            return [types.TextContent(type="text", text="task_id is required.")]
        try:
            import json as _json
            data = _get(LAYLA_BASE + f"/agent/tasks/{task_id}", timeout=10)
            status = data.get("status", "?")
            result = data.get("result") or data.get("response") or ""
            error = data.get("error", "")
            lines = [f"Task {task_id}: {status}"]
            if result:
                lines.append(f"\nResult:\n{result[:2000]}")
            if error:
                lines.append(f"\nError: {error}")
            return [types.TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [types.TextContent(type="text", text=f"poll_task failed: {e}")]

    # ── parallel_aspects ──────────────────────────────────
    # Ask the same question to multiple aspects simultaneously.
    # Returns merged responses labeled by aspect. Useful for multi-perspective
    # analysis where Cursor AI orchestrates the synthesis.
    if name == "parallel_aspects":
        message = (args.get("message", "") or "").strip()
        if not message:
            return [types.TextContent(type="text", text="message is required.")]
        aspects = args.get("aspects") or ["morrigan", "nyx"]
        if isinstance(aspects, str):
            aspects = [a.strip() for a in aspects.split(",") if a.strip()]
        aspects = aspects[:4]  # cap at 4 to avoid overwhelming the local LLM
        context = (args.get("context", "") or "").strip()
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        allow_write = False  # parallel calls are always read-only
        allow_run = False

        import threading as _threading

        results: dict[str, str] = {}
        errors: dict[str, str] = {}

        def _ask_one(aspect: str) -> None:
            try:
                payload = {
                    "message": message,
                    "context": context,
                    "workspace_root": workspace_root,
                    "allow_write": allow_write,
                    "allow_run": allow_run,
                    "aspect_id": aspect,
                    "show_thinking": False,
                }
                data = _agent_sync(payload, timeout=120)
                results[aspect] = (data.get("response") or "").strip()
            except Exception as exc:
                errors[aspect] = str(exc)

        threads = [_threading.Thread(target=_ask_one, args=(a,), daemon=True) for a in aspects]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=130)

        lines = [f"Parallel responses for: {message[:120]}"]
        for aspect in aspects:
            lines.append(f"\n── {aspect.upper()} ──")
            if aspect in errors:
                lines.append(f"[ERROR: {errors[aspect]}]")
            else:
                lines.append(results.get(aspect, "[no response]"))
        return [types.TextContent(type="text", text="\n".join(lines))]

    # ── agent_handoff ─────────────────────────────────────
    # Pass context + goal from one conversation/agent to a new Layla run.
    # Enables clean handoffs: "take what we've discussed and start a new task."
    if name == "agent_handoff":
        handoff_context = (args.get("context", "") or "").strip()
        new_goal = (args.get("goal", "") or "").strip()
        if not new_goal:
            return [types.TextContent(type="text", text="goal is required for handoff.")]
        aspect_id = (args.get("aspect_id", "") or "").strip()
        workspace_root = _normalize_workspace_root(args.get("workspace_root", "") or "")
        allow_write = args.get("allow_write") is True
        allow_run = args.get("allow_run") is True
        import uuid as _uuid
        new_conversation_id = str(_uuid.uuid4())
        payload = {
            "message": new_goal,
            "context": handoff_context,
            "workspace_root": workspace_root,
            "allow_write": allow_write,
            "allow_run": allow_run,
            "aspect_id": aspect_id or "morrigan",
            "conversation_id": new_conversation_id,
        }
        try:
            data = await anyio.to_thread.run_sync(lambda: _agent_sync(payload, timeout=300))
            text = (data.get("response") or "")
            return [types.TextContent(
                type="text",
                text=f"[Handoff → conversation {new_conversation_id}]\n\n{text}",
            )]
        except Exception as e:
            return [types.TextContent(type="text", text=f"agent_handoff failed: {e}")]

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

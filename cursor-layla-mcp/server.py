# MCP server: exposes tools so Cursor can talk to the local Layla agent.
# Run with: python server.py  (requires mcp package; use agent venv and pip install mcp)
import anyio
import json
import os
import subprocess
import urllib.request
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

app = Server("layla")


def _post(url: str, body: dict, timeout: int = 180) -> dict:
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


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
    show_thinking: bool = False,
) -> str:
    data = _post(LAYLA_BASE + "/agent", {
        "message": message,
        "context": context,
        "workspace_root": (workspace_root or "").strip() or _infer_workspace_root(),
        "allow_write": allow_write,
        "allow_run": allow_run,
        "aspect_id": aspect_id,
        "show_thinking": show_thinking,
    })
    return data.get("response", "")


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
        try:
            response = await anyio.to_thread.run_sync(
                lambda: _chat_sync(message, context, workspace_root, allow_write, allow_run, aspect_id, show_thinking)
            )
            return [types.TextContent(type="text", text=response)]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Layla unreachable: {e}. Is the server running on port 8000?")]

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

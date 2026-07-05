"""Tool definitions for the Cursor<->Layla MCP server (BL-030 split).

The full ListToolsResult (every tool schema) lived inline in server.handle_list_tools,
the single biggest reason server.py was ~1300 lines. Extracted here; server delegates.
"""
from __future__ import annotations

from mcp import types


def build_tools_result() -> types.ListToolsResult:
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
                        "persona_focus": {
                            "type": "string",
                            "description": "Optional second aspect id to merge into the system prompt for extra depth (e.g. morrigan + persona_focus nyx for coding with research tone). Primary aspect_id still owns tools and display.",
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
                        "engineering_pipeline_mode": {
                            "type": "string",
                            "description": "When runtime engineering_pipeline_enabled: chat (default), plan (clarifier+planner only), or execute (full pipeline). Ignored when feature off.",
                            "default": "",
                        },
                        "clarification_reply": {
                            "type": "string",
                            "description": "Answers to prior clarification questions (same message/goal as before).",
                            "default": "",
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
            types.Tool(
                name="layla_status",
                title="Layla server status",
                description=(
                    "Check if the Layla server is up and responding. Returns version, model loaded status, "
                    "and uptime. Use this first if you are unsure whether Layla is running."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="layla_wakeup",
                title="Wake up Layla (session start)",
                description=(
                    "Trigger Layla's wakeup sequence. Echo greets, reports what was studied recently, "
                    "and lists active study plans. Call at the start of a new session."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="layla_health",
                title="Layla full health check",
                description=(
                    "Return detailed health data: DB status, model loaded, tools registered, "
                    "learnings count, study plans, vector store, token usage, cache stats. "
                    "Use ?deep=true for a full Chroma vector probe."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "deep": {
                            "type": "boolean",
                            "description": "If true, also probe the Chroma vector store.",
                            "default": False,
                        },
                    },
                },
            ),
            types.Tool(
                name="deliberate",
                title="Force Layla multi-aspect deliberation",
                description=(
                    "Force all six Layla aspects to weigh in on a question before concluding. "
                    "Morrigan, Nyx, Echo, Eris, Cassandra, and Lilith each speak, then Morrigan concludes. "
                    "Use for architectural decisions, ethical questions, or anything worth thinking hard about."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["question"],
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question or decision to deliberate on.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional context (code, file content, background).",
                            "default": "",
                        },
                        "workspace_root": {"type": "string", "default": ""},
                    },
                },
            ),
            types.Tool(
                name="run_code",
                title="Run Python code via Layla sandbox",
                description=(
                    "Execute a Python snippet in Layla's sandboxed runner. "
                    "Requires allow_run approval. Returns stdout, stderr, and exit code. "
                    "Good for quick calculations, data transforms, or testing logic."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to run.",
                        },
                        "workspace_root": {"type": "string", "default": ""},
                    },
                },
            ),
            types.Tool(
                name="get_model_catalog",
                title="List Layla's available models",
                description=(
                    "Return the full model catalog with names, categories, hardware requirements, "
                    "and download URLs. Categories: general, coding, reasoning, creative, fast, flagship."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Filter by category: general, coding, reasoning, creative, fast, flagship. Empty = all.",
                            "default": "",
                        },
                    },
                },
            ),
            types.Tool(
                name="ask_aspect",
                title="Ask a specific Layla aspect directly",
                description=(
                    "Route your message directly to one named aspect. "
                    "morrigan=engineer/code, nyx=researcher/analysis, echo=companion/memory, "
                    "eris=creative/chaos, cassandra=blunt oracle, lilith=ethics/authority/nsfw."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["aspect", "message"],
                    "properties": {
                        "aspect": {
                            "type": "string",
                            "description": "Aspect ID: morrigan, nyx, echo, eris, cassandra, lilith.",
                        },
                        "message": {"type": "string", "description": "Your message to that aspect."},
                        "context": {"type": "string", "default": ""},
                        "workspace_root": {"type": "string", "default": ""},
                        "allow_write": {"type": "boolean", "default": False},
                        "allow_run": {"type": "boolean", "default": False},
                        "stream": {"type": "boolean", "default": False},
                    },
                },
            ),
            # ── Multi-agent tools ──────────────────────────────
            types.Tool(
                name="delegate_task",
                title="Delegate a task to Layla as a background agent",
                description=(
                    "Send a goal to Layla as a background agent task. "
                    "Returns a task_id immediately. Use poll_task to check status and get the result. "
                    "Enables Cursor AI + Layla multi-agent workflows: Cursor orchestrates, Layla executes."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["goal"],
                    "properties": {
                        "goal": {"type": "string", "description": "The task or goal for Layla to work on."},
                        "aspect_id": {
                            "type": "string",
                            "description": "Which aspect should handle this task (default: morrigan).",
                            "default": "morrigan",
                        },
                        "context": {"type": "string", "default": ""},
                        "workspace_root": {"type": "string", "default": ""},
                        "allow_write": {"type": "boolean", "default": False},
                        "allow_run": {"type": "boolean", "default": False},
                    },
                },
            ),
            types.Tool(
                name="poll_task",
                title="Check status of a delegated Layla task",
                description="Poll the status and result of a task previously delegated to Layla via delegate_task.",
                inputSchema={
                    "type": "object",
                    "required": ["task_id"],
                    "properties": {
                        "task_id": {"type": "string", "description": "The task_id returned by delegate_task."},
                    },
                },
            ),
            types.Tool(
                name="parallel_aspects",
                title="Ask multiple Layla aspects simultaneously",
                description=(
                    "Send the same question to multiple aspects in parallel and get all responses. "
                    "Cursor AI can synthesize the perspectives. "
                    "Example: ask morrigan + nyx for code review + research context at the same time. "
                    "Always read-only (allow_write and allow_run are disabled for safety)."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {"type": "string", "description": "The question or task to send to all aspects."},
                        "aspects": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of aspect IDs to query (max 4). Default: [morrigan, nyx].",
                            "default": ["morrigan", "nyx"],
                        },
                        "context": {"type": "string", "default": ""},
                        "workspace_root": {"type": "string", "default": ""},
                    },
                },
            ),
            types.Tool(
                name="agent_handoff",
                title="Hand off context and start a new Layla conversation",
                description=(
                    "Pass accumulated context from the current conversation to a new Layla task. "
                    "Creates a fresh conversation_id so the new task starts clean but informed. "
                    "Use when pivoting: 'take what we discussed about X and now do Y'."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["goal"],
                    "properties": {
                        "goal": {"type": "string", "description": "The new goal for the handed-off task."},
                        "context": {
                            "type": "string",
                            "description": "Context from the prior conversation to carry forward.",
                            "default": "",
                        },
                        "aspect_id": {"type": "string", "default": "morrigan"},
                        "workspace_root": {"type": "string", "default": ""},
                        "allow_write": {"type": "boolean", "default": False},
                        "allow_run": {"type": "boolean", "default": False},
                    },
                },
            ),
        ]
    )

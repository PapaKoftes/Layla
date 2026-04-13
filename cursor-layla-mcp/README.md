# cursor-layla-mcp

MCP server that lets Cursor (or any MCP-compatible client) talk directly to your local **Layla** agent.  
The Layla web server must be running on `http://127.0.0.1:8000`.

---

## Quick start

```powershell
# Start Layla first (from repo root)
cd agent
uvicorn main:app --host 127.0.0.1 --port 8000
```

The MCP server is launched automatically by Cursor when it is configured in `mcp.json` (see below).

---

## Cursor `mcp.json` — copy this exactly

File lives at: `C:\Users\<you>\.cursor\mcp.json`

```json
{
  "mcpServers": {
    "layla": {
      "command": "C:\\Users\\<you>\\<path-to-repo>\\agent\\venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\<you>\\<path-to-repo>\\cursor-layla-mcp\\server.py"],
      "env": {
        "LAYLA_BASE_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

> **Note**: Use the venv python so all MCP dependencies (`mcp`, `anyio`) are available.

## Make Layla show in Cursor model dropdown

This is separate from MCP tools. To use Layla as the **actual chat model** in Cursor:

1. Open Cursor settings → Models
2. Set OpenAI-compatible base URL to `http://127.0.0.1:8000`
3. Enter any non-empty API key (for example: `layla-local`)
4. Add/select model name `layla`

Layla exposes OpenAI-compatible endpoints:
- `GET /v1/models`
- `POST /v1/chat/completions` (streaming supported)

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LAYLA_BASE_URL` | `http://127.0.0.1:8000` | Base URL of the Layla web server |

---

## All tools

### Core conversation

| Tool | Required | Optional | Description |
|---|---|---|---|
| `chat_with_layla` | `message` | `context`, `workspace_root`, `allow_write`, `allow_run`, `aspect_id`, `show_thinking`, `stream`, `include_trace` | Send any message to Layla. Main tool. |
| `ask_aspect` | `aspect`, `message` | `context`, `workspace_root`, `allow_write`, `allow_run`, `stream` | Route directly to one aspect: `morrigan`, `nyx`, `echo`, `eris`, `cassandra`, `lilith`. |
| `deliberate` | `question` | `context`, `workspace_root` | Force all 6 aspects to deliberate, then Morrigan concludes. Best for hard decisions. |

### Memory

| Tool | Required | Optional | Description |
|---|---|---|---|
| `add_learning` | `content` | `type` (fact/preference/correction) | Persist a learning to Layla's long-term memory. |
| `get_memories` | `query` | `n` | Search Layla's semantic memory for relevant past knowledge. |

### Workspace & code

| Tool | Required | Optional | Description |
|---|---|---|---|
| `get_context` | — | `workspace_root`, `path`, `selected_text`, `include_project_context` | Build a context bundle from file/selection/project context. |
| `search_workspace` | `query` | `workspace_root`, `k`, `context` | Search codebase using Layla's code intelligence. |
| `apply_patch` | `original_path`, `patch_text` | `workspace_root`, `dry_run` | Apply or analyze a patch through Layla's approval-gated toolchain. |
| `run_code` | `code` | `workspace_root` | Execute Python in Layla's sandbox. Requires approval. |

### Learning & study

| Tool | Required | Optional | Description |
|---|---|---|---|
| `start_study_session` | `topic` | `context`, `workspace_root` | Run a focused study session on a topic. |
| `analyze_repo_for_study` | `workspace_root` | — | Analyze a repo, create study plans for knowledge gaps. |

### Approvals

| Tool | Required | Optional | Description |
|---|---|---|---|
| `get_pending_approvals` | — | — | List all actions waiting for approval. |
| `approve_action` | `approval_id` | — | Approve a pending action so Layla can proceed. |

### System

| Tool | Required | Optional | Description |
|---|---|---|---|
| `layla_status` | — | — | Quick check: is Layla up, version, model loaded, uptime. |
| `layla_wakeup` | — | — | Trigger session start. Echo greets, study plans listed. |
| `layla_health` | — | `deep` | Full health data. `deep=true` probes the vector store too. |
| `get_model_catalog` | — | `category` | List all available models. Filter by: `general`, `coding`, `reasoning`, `creative`, `fast`, `flagship`. |
| `schedule_layla_task` | `tool_name` | `args`, `delay_seconds`, `cron_expr` | Schedule a background tool run. |

---

## Aspect reference

| Aspect | ID | Best for |
|---|---|---|
| ⚔ Morrigan | `morrigan` | Engineering, code, debugging, architecture |
| ✦ Nyx | `nyx` | Research, deep explanations, analysis |
| ◎ Echo | `echo` | Memory, patterns, continuity, check-ins |
| ⚡ Eris | `eris` | Creative ideas, brainstorming, banter |
| ⌖ Cassandra | `cassandra` | Blunt first-pass critique, hot takes |
| ⊛ Lilith | `lilith` | Ethics, safety, high-stakes decisions, NSFW register |

Leave `aspect_id` empty on `chat_with_layla` for auto-routing based on your message keywords.

---

## Usage examples

**General chat (auto-routed):**
```
chat_with_layla: { "message": "explain this function", "context": "<file content>" }
```

**Code-focused, Morrigan direct:**
```
ask_aspect: { "aspect": "morrigan", "message": "refactor this to be async", "context": "...", "allow_write": true }
```

**Deliberate on an architecture decision:**
```
deliberate: { "question": "Should I use Redis or SQLite for session state?" }
```

**Run a quick Python test:**
```
run_code: { "code": "import json; print(json.dumps({'ok': True}))" }
```

**Check what models are available for coding:**
```
get_model_catalog: { "category": "coding" }
```

# cursor-layla-mcp

MCP server that lets Cursor (or any MCP-compatible client) call your local **Layla** agent as tools. The Layla web server must be running on `http://127.0.0.1:8000`.

## Quick start

```bash
# From repo root (agent venv must have mcp installed)
python cursor-layla-mcp/server.py
```

Or use `.\start-layla.ps1`, which starts both the web server and the MCP server.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `LAYLA_BASE_URL` | `http://127.0.0.1:8000` | Base URL of the Layla web server |

## Tools exposed

| Tool | Required | Optional | Description |
|---|---|---|---|
| `chat_with_layla` | `message` | `context`, `workspace_root`, `allow_write`, `allow_run`, `aspect_id`, `show_thinking`, `stream`, `include_trace` | Send a message to Layla |
| `get_context` | — | `workspace_root`, `path`, `selected_text`, `include_project_context` | Build a context bundle from file/selection/project context |
| `search_workspace` | `query` | `workspace_root`, `k`, `context` | Search codebase using Layla's code intelligence / search tools |
| `apply_patch` | `original_path`, `patch_text` | `workspace_root`, `dry_run` | Apply or analyze a patch via Layla approval-gated toolchain |
| `add_learning` | `content` | `type` (fact/preference/correction) | Persist a learning to Layla's memory |
| `start_study_session` | `topic` | `context`, `workspace_root` | Run a focused study session |
| `analyze_repo_for_study` | `workspace_root` | — | Analyze a repo and create study plans |

## How to use from Cursor

**Do not** type plain chat messages directly into an MCP transport — the protocol expects JSON-RPC.

Instead, invoke the **`chat_with_layla`** tool from Cursor's agent panel, passing your message in the `message` argument. Always include `context` (open file content or selected code) so Layla can work on what you have open.

```json
{
  "tool": "chat_with_layla",
  "arguments": {
    "message": "Refactor this function to use async/await",
    "context": "<file content here>",
    "workspace_root": "/path/to/repo",
    "allow_write": true
  }
}
```

## Cursor MCP config

Add this to Cursor MCP settings:

```json
{
  "mcpServers": {
    "layla": {
      "command": "python",
      "args": ["cursor-layla-mcp/server.py"],
      "env": {
        "LAYLA_BASE_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

# Cursor MCP for Layla (Jinx)

This MCP server lets Cursor call your local Layla agent via **tools**. The Layla web server must be running on http://127.0.0.1:8000.

## How to chat with Jinx from Cursor

**Do not** type "hi jinx" or plain chat in a place that sends raw text to MCP. The MCP protocol expects JSON-RPC; raw text causes `Invalid JSON` errors.

**Do this instead:**

1. **Use the MCP tool**  
   In Cursor, invoke the tool **"Chat with Layla (Jinx)"** (or **chat_with_jinx**) and pass your message in the `message` argument. That sends a proper request to the server and returns Jinx’s reply.

2. **Or use the web UI**  
   Open http://127.0.0.1:8000 (or /ui) in your browser and chat there. No MCP involved.

## Run the MCP server

From repo root:

```bash
python -m pip install -r cursor-jinx-mcp/requirements.txt
python cursor-jinx-mcp/server.py
```

Or use `.\start-layla.ps1`, which starts both the web server and the MCP server (in a separate window).

## Tools exposed

- **chat_with_jinx** – Send a message to Layla. Required: `message`. Optional: `context`, `workspace_root`, `allow_write`, `allow_run`, `aspect_id`, `show_thinking`.
- **add_learning** – Add a fact/preference to her memory. Required: `content`. Optional: `type` (fact/preference/correction).
- **start_study_session** – Run a study session on a topic. Required: `topic`.
- **analyze_repo_for_study** – Analyze a repo and suggest study topics. Required: `workspace_root`.

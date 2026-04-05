# How to use Layla (starter)

- **Run the server:** from `agent/`, `uvicorn main:app --host 127.0.0.1 --port 8000`, or use `START.bat` / `start.sh`.
- **Web UI:** open `http://localhost:8000/ui`. Pick an aspect with `@nyx`, `@morrigan`, etc., or use the aspect control in the header.
- **Projects:** optional `project_id` scopes workspace defaults and a system preamble (see `/projects` API).
- **Approvals:** file writes and shell runs require operator approval unless explicitly allowed in the client (MCP `allow_write` / `allow_run`).
- **Memory:** long-term learnings via `POST /learn/` and SQLite + optional Chroma; conversations persist in `layla.db`.

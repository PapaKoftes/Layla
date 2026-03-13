# Runbooks

Procedures for common setup and extension tasks. See also README.md, ARCHITECTURE.md, and REMOTE_ARCHITECTURE.md.

---

## First run

1. **Python**: Use 3.10+ (tested 3.10–3.12). Create a venv and install deps:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r agent/requirements.txt
   ```

2. **Database**: On first request that touches memory, `layla.db` is created at **repo root** (see ARCHITECTURE.md). No manual step.

3. **Config**: If `agent/runtime_config.json` is missing, copy from `agent/runtime_config.example.json` and set `model_filename` and `sandbox_root` (e.g. a directory path where the agent may write). Do not commit real `remote_api_key` if you enable remote access.

4. **Model**: Place your GGUF model in `models/` (e.g. `models/your-model.gguf`). Set `model_filename` in `agent/runtime_config.json` if the name differs.

5. **Start server** (from repo root or `agent/`):
   ```bash
   cd agent
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

6. **Verify**: Open http://localhost:8000/health — expect `{"ok": true}` (or 503 if DB not yet created). Open http://localhost:8000/ui for the chat UI. Run `python layla.py wakeup` from repo root for CLI wakeup.

7. **Remote (optional)**: To allow access from another machine, set in `runtime_config.json`: `"remote_enabled": true`, `"remote_api_key": "your-secret"`, and start with `uvicorn main:app --host 0.0.0.0 --port 8000`. See docs/REMOTE_ARCHITECTURE.md.

---

## Add a tool

1. **Implement the tool** in `agent/jinx/tools/` (or extend `agent/jinx/tools/registry.py`). Tool entry: `{"fn": callable, "dangerous": bool, "require_approval": bool, "risk_level": "low"|"medium"|"high"}`.

2. **Register** in `agent/jinx/tools/registry.py`: add the entry to the `TOOLS` dict keyed by tool name (e.g. `"my_tool"`).

3. **Wire into the agent loop** in `agent/agent_loop.py`: add a branch for the new tool’s intent (same pattern as `read_file`, `write_file`, etc.). Use `decision_schema` / `_VALID_TOOLS` so the LLM can choose it.

4. **Approval**: If the tool writes files or runs code, set `require_approval: True` and `dangerous: True` so the approval flow applies. See `runtime_safety.DANGEROUS_TOOLS` and `main.py` approval handling.

5. **Tests**: Add a test in `agent/tests/` that mocks the LLM and asserts the tool is invoked (and approval required when applicable).

---

## Add an aspect

1. **Create personality file**: Add `personalities/<id>.json` (e.g. `personalities/nyx.json`) with at least:
   - `id`, `name`
   - `role` or `voice` (short description)
   - `systemPromptAddition` (optional)
   See existing files in `personalities/` for structure.

2. **Register in orchestrator**: In `agent/orchestrator.py`, ensure the aspect is loaded (e.g. via `_load_aspects()` from the personalities directory). Add trigger phrases or explicit routing if needed (see `.cursor/rules/layla-assistant.mdc` for trigger table).

3. **Optional**: Add to deliberation roster, study bias, or decision bias in the orchestrator so the aspect is used for multi-aspect prompts when `show_thinking` is true.

4. **Docs**: Update `.cursor/rules/layla-assistant.mdc` (or equivalent) if the aspect is user-facing so Cursor/MCP knows the new aspect id.

---

## Add knowledge

1. **Static docs**: Add `.md` or `.txt` files under `knowledge/` (repo root). Optional front matter in markdown:
   ```yaml
   ---
   priority: core | support | flavor
   domain: coding | personality | research
   ---
   ```

2. **Indexing**: With `use_chroma: true` in `agent/runtime_config.json`, the server indexes `knowledge/` at startup (and on refresh). To force reindex, touch or edit a file under `knowledge/`; the next agent request can trigger `refresh_knowledge_if_changed`.

3. **URL sources**: Add entries to `knowledge_sources` in `runtime_config.json` (list of `{"url": "...", "name": "..."}`). Use `agent/download_docs.py` to fetch and optionally merge into `knowledge/` or a local cache.

4. **PDF**: Place `.pdf` files under `knowledge/`. If `pypdf` is installed (`pip install pypdf`), they are indexed like `.md`/`.txt` (no front matter; first 50 pages). Without pypdf, PDFs are skipped.

5. **Notion**: Export pages to Markdown and put the files under `knowledge/`. A future Notion API loader is optional (see MILESTONES M6).

---

## Proactive suggestions (wakeup)

- **Initiative**: Set `"wakeup_include_initiative": true` in `runtime_config.json` to append one rule-based suggestion (e.g. study plans, lifecycle stage) to the wakeup greeting.
- **Discovery one-liner**: Set `"wakeup_include_discovery_line": true` to append a single line from project discovery (first opportunity or idea). Uses the same LLM call as GET `/project_discovery`; on failure or empty result, no line is added.

---

## Trace ID (debugging)

Set `"trace_id_enabled": true` in `agent/runtime_config.json`. Every response will include an `X-Trace-Id` header (propagated from request or newly generated). Use it to correlate logs and requests across services.

# Runbooks

Procedures for common setup and extension tasks. See also README.md, ARCHITECTURE.md, and REMOTE_ARCHITECTURE.md.

---

## First run

**Easy way (recommended):** Double-click `INSTALL.bat` (Windows) or run `bash install.sh` (Linux/macOS). The installer creates a venv, installs deps, runs the hardware wizard, and can download a model for you. Linux install flow thanks to Kai.

**Manual:**

1. **Python 3.11+**: Create a venv and install deps:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows: source .venv/bin/activate on Linux/macOS
   pip install -r agent/requirements.txt
   ```

2. **Hardware config**: Run `python agent/first_run.py` — detects your GPU/RAM, recommends a model, writes `agent/runtime_config.json` with optimal settings.

3. **Model**: Download a `.gguf` file into `models/`. See `MODELS.md` for recommendations and download links. Set `model_filename` in `agent/runtime_config.json`.

4. **Start server**: Double-click `START.bat` (Windows) / run `bash start.sh`, or manually:
   ```bash
   cd agent
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

5. **Verify**: Open http://localhost:8000/health — expect `{"ok": true}`. Open http://localhost:8000/ui for the chat UI.

7. **Remote (optional)**: To allow access from another machine, set in `runtime_config.json`: `"remote_enabled": true`, `"remote_api_key": "your-secret"`, and start with `uvicorn main:app --host 0.0.0.0 --port 8000`. See docs/REMOTE_ARCHITECTURE.md.

---

## Add a tool

1. **Implement the tool** in `agent/layla/tools/registry.py`. Tool entry: `{"fn": callable, "dangerous": bool, "require_approval": bool, "risk_level": "low"|"medium"|"high"}`.

2. **Register** in `agent/layla/tools/registry.py`: add the entry to the `TOOLS` dict keyed by tool name (e.g. `"my_tool"`).

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

## Add a skill

1. **Edit the registry**: In `agent/layla/skills/registry.py`, add an entry to `SKILLS`:
   ```python
   "my_skill": {
       "description": "What this skill does",
       "tools": ["tool1", "tool2", "tool3"],
       "execution_steps": ["Step 1", "Step 2"],
   }
   ```
2. **Ensure tools exist**: All tools in the list must be in `layla/tools/registry.TOOLS`.
3. **Planner integration**: Skills are automatically injected into the planner prompt when `skills_enabled: true` in config. No agent_loop changes needed — skills are planning hints.

---

## Add a plugin

1. **Create plugin directory**: `plugins/<name>/` (e.g. `plugins/my_plugin/`).
2. **Add manifest**: Create `plugins/<name>/plugin.yaml`:
   ```yaml
   name: my_plugin
   description: Short description
   skills:
     - name: my_skill
       description: What it does
       tools: [tool1, tool2]
   tools: []
   dependencies: []
   ```
3. **Optional tools**: Add `plugins/<name>/tools.py` with a `register(registry)` function that adds entries to the TOOLS dict.
4. **Restart**: Plugins are loaded at server startup. See [docs/plugins.md](plugins.md) for full documentation.

---

## Proactive suggestions (wakeup)

- **Initiative**: Set `"wakeup_include_initiative": true` in `runtime_config.json` to append one rule-based suggestion (e.g. study plans, lifecycle stage) to the wakeup greeting.
- **Discovery one-liner**: Set `"wakeup_include_discovery_line": true` to append a single line from project discovery (first opportunity or idea). Uses the same LLM call as GET `/project_discovery`; on failure or empty result, no line is added.

---

## Trace ID (debugging)

Set `"trace_id_enabled": true` in `agent/runtime_config.json`. Every response will include an `X-Trace-Id` header (propagated from request or newly generated). Use it to correlate logs and requests across services.

---

## Prompt and context tuning

The system uses a centralized context manager (`services/context_manager.py`) for token budgets and deduplication.

1. **Enable/disable budget enforcement**: Set `"prompt_budget_enabled": true` (default) to enforce per-section token limits. Set to `false` to use legacy unbounded assembly.

2. **Custom budgets**: Set `"prompt_budgets"` to a dict of section names and token limits, e.g.:
   ```json
   "prompt_budgets": {
     "system_instructions": 1000,
     "agent_state": 500,
     "memory": 800,
     "knowledge_graph": 400,
     "knowledge": 600
   }
   ```
   Sections: `system_instructions`, `agent_state`, `current_goal`, `memory`, `knowledge_graph`, `knowledge`.

3. **Observability**: When budgets are enabled, `log_prompt_assembled` emits total_tokens, sections count, and truncated sections. Check logs for `[prompt_assembled]` events.

4. **Memory retrieval**: Uses vector + BM25 + FTS5 + cross-encoder reranking + confidence/recency boost. Learnings with higher confidence and more recent `created_at` rank higher. Config: `semantic_k`, `learnings_n`, `knowledge_chunks_k`.

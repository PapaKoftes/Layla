# Runbooks

Procedures for common setup and extension tasks. See also README.md, ARCHITECTURE.md, and REMOTE_ARCHITECTURE.md.

**Config:** [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) — full list of `runtime_config.json` keys for advanced users.

**Ethics:** [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md) — core ethical AI principles; all behavior must align.

**Discord:** [DISCORD_SETUP.md](DISCORD_SETUP.md) — hook Layla to your Discord server (webhook, no bot).

**OpenClaw (optional sidecar):** [OPENCLAW_ALIGNMENT.md](OPENCLAW_ALIGNMENT.md) maps OpenClaw concepts to Layla. [OPENCLAW_BRIDGE.md](OPENCLAW_BRIDGE.md) describes pointing an OpenClaw-style gateway at `POST /agent`. Layla-native onboarding is under **First run** below; no Node stack required for core use.

**Tool policy & markdown skills:** `tools_profile`, `tools_allow`, `tools_deny`, `tool_loop_detection_enabled`, `http_cache_ttl_seconds`, `inference_fallback_urls`, `browser_persistent_profiles` — see `agent/runtime_config.example.json` and [OPENCLAW_ALIGNMENT.md](OPENCLAW_ALIGNMENT.md). Optional AgentSkills-style files: repo [`skills/`](../skills/README.md) or `markdown_skills_dir` in config.

---

## First run

**Easy way (recommended):** Run `install.ps1` (Windows PowerShell) or `bash install.sh` (Linux/macOS). The installer creates a venv, installs deps, runs the hardware wizard, and can download a model for you. Linux install flow thanks to Kai.

**First-time installation guide:**

1. **Python 3.11+**: The installer checks this. If missing, install from python.org or your package manager.

2. **Run the installer**:
   - **Windows**: `powershell -ExecutionPolicy Bypass -File install.ps1` or double-click `INSTALL.bat`
   - **Linux/macOS**: `bash install.sh`

3. **Hardware detection**: The installer (`agent/install/installer_cli.py`) detects CPU model, cores, RAM, GPU, VRAM, and CUDA/ROCm/Metal support. It classifies your hardware into tiers (cpu_tier, ram_tier, gpu_tier).

4. **Model recommendation**: Uses `agent/models/model_catalog.json` to recommend the best compatible model. Jinx, Dolphin, Hermes, Qwen, and lightweight fallbacks are included.

5. **Model download**: Optionally downloads the recommended model to `~/.layla/models/` using `huggingface_hub` (when installed) or direct URL. Progress bar shown.

6. **Runtime config**: Auto-generates `agent/runtime_config.json` with `n_ctx`, `n_threads`, `n_gpu_layers`, `parallel_tasks`, and `models_dir` tuned for your hardware.

7. **Start server**: Double-click `START.bat` (Windows) / run `bash start.sh`, or manually:
   ```bash
   cd agent
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

8. **Verify**: Open http://localhost:8000/health — expect `{"ok": true}`. Open http://localhost:8000/ui for the chat UI.

9. **Remote (optional)**: To allow access from another machine, set in `runtime_config.json`: `"remote_enabled": true`, `"remote_api_key": "your-secret"`, and start with `uvicorn main:app --host 0.0.0.0 --port 8000`. See docs/REMOTE_ARCHITECTURE.md.

**Manual install (no installer):**

1. Create venv and install deps: `python -m venv .venv` then `pip install -r agent/requirements.txt`
2. Run `python agent/install/installer_cli.py` or `python agent/first_run.py` for config
3. Download a `.gguf` into `~/.layla/models/` or `models/`. See `MODELS.md`.
4. Start: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`

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

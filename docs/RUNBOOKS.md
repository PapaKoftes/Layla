# Runbooks

Procedures for common setup and extension tasks. See also README.md, ARCHITECTURE.md, and REMOTE_ARCHITECTURE.md.

Read [`PROJECT_BRAIN.md`](../PROJECT_BRAIN.md) first for stable context; use module sweeps for subsystem depth.

**Module second sweeps:** [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md) — skeleton for `*_MODULE_SECOND_SWEEP.md` reports; tracking table [MODULE_SWEEP_STATUS.md](MODULE_SWEEP_STATUS.md).

**Config:** [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) — full list of `runtime_config.json` keys for advanced users.

**Ethics:** [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md) — core ethical AI principles; all behavior must align.

**Discord:** [DISCORD_SETUP.md](DISCORD_SETUP.md) — hook Layla to your Discord server (webhook, no bot).

**OpenClaw (optional sidecar):** [OPENCLAW_ALIGNMENT.md](OPENCLAW_ALIGNMENT.md) maps OpenClaw concepts to Layla. [OPENCLAW_BRIDGE.md](OPENCLAW_BRIDGE.md) describes pointing an OpenClaw-style gateway at `POST /agent`. Layla-native onboarding is under **First run** below; no Node stack required for core use.

**Claude Code Unpacked (slash → HTTP):** [CCUNPACKED_ALIGNMENT.md](CCUNPACKED_ALIGNMENT.md) section 3 maps common Claude Code–style commands to Layla routes and tools.

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

## Project memory and long-horizon repo work

Layla can keep a **versioned JSON map** under each workspace: **`.layla/project_memory.json`** (sandbox-scoped). It holds a structural file listing, optional **plan** / **todos** / **decisions**, optional schema-v2 **`modules`**, **`issues`**, and **`plans`** (mirrored plan metadata), and is summarized into the system head when the file exists (`project_memory_*` keys in `runtime_config.example.json`).

**Typical flow (planning-first)**

1. **Cognition digest** (optional): `sync_repo_cognition` or `POST /workspace/cognition/sync` — doc-first snapshot in SQLite (injected when `repo_cognition_inject_enabled`).
2. **Structural scan**: tool **`scan_repo`** (or **`POST /agent`** with **`understand_mode: true`** and **`workspace_root`**) — writes/updates `.layla/project_memory.json` without running the full agent loop. Optional **`understand_index_semantic: true`** enables semantic indexing during the bundled cognition sync.
3. **Draft plan**: **`plan_mode: true`** on `POST /agent` — returns **`plan`** (legacy list) plus **`plan_id`** and **`plan_steps`**; a row is stored in SQLite **`layla_plans`**. Edit via **`PATCH /plans/{id}`** if needed. When `project_memory_persist_plan` is true and `workspace_root` is set, the plan is also stored under `project_memory.plan`.
4. **Review / approve**: Web UI **Workspace → Plans**, or **`POST /plans/{id}/approve`**. Approving mirrors a short summary into **`project_memory.plans`** when the workspace is sandbox-allowed.
5. **Execute**: **`POST /plans/{id}/execute`** — body: **`allow_write`**, **`allow_run`**, optional **`default_max_retries`** or **`step_max_retries`** (0–3, default 1) for governance retries when a step fails validation or looks low-confidence; stored plan steps may also set **`max_retries`** per step (capped 0–3). The server runs **`execute_plan(..., step_governance=True)`**: non-empty **`tools`** on a step become a **hard allowlist** for that step’s `autonomous_run`; **`validate_step_outcome`** and **`low_confidence_response`** gate success; JSON response includes **`all_steps_ok`** and the SQLite row ends **`done`** only if all steps pass, otherwise **`blocked`**. For **`POST /execute_plan`** / **`POST /agent`** with **`plan_id`**, behavior follows those routes. Use **`POST /agent`** with **`plan_id`** under **`planning_strict_mode`** for durable-plan tool gating.
   - **Ephemeral in-loop plans** (long goal → `should_plan` → `create_plan` → `execute_plan` inside **`autonomous_run`**): **`in_loop_plan_governance_enabled`** defaults **true** — same governance/retries as **`/execute_plan`** (**`in_loop_plan_default_max_retries`**); nested steps receive **`plan_approved`** when the outer request already set **`plan_approved`** or **`allow_write`** or **`allow_run`**. Response may include **`all_steps_ok`**. Set **`in_loop_plan_governance_enabled: false`** for legacy in-loop behavior (no per-step governance).
   - **`plan_governance_require_nonempty_step_tools`**: when **true**, **`POST /plans/{id}/approve`** and **`POST /plan/{id}/approve`** reject steps of type **edit** / **test** / **build** / **refactor** / **cad** with an empty **`tools`** list. With **`in_loop_plan_governance_enabled`** enabled, in-loop **`create_plan`** rows that are analysis-like get default read-only **`tools`** from **`plan_step_default_read_tools`** (mutating types are not auto-filled); steps are tagged **`_tools_auto_filled`** for transparency.
   - **Edit/test validation**: when the agent run recorded **`state.steps`**, governed **edit** steps require a successful **`apply_patch`**, **`write_file`**, or **`write_files_batch`** tool with **`result.ok: true`**; **test** steps require **`run_tests`** with **`ok`** or **shell**/**run_python** output that mentions **pytest**/**unittest**/**tox**. If there were no tool steps, Layla still uses text heuristics on the final reply. **`plan_governance_reject_auto_filled_tools`**: set **true** to refuse any step whose **`tools`** were auto-filled (forces explicit tool lists).
6. **Continuous worker**: **`POST /agent/background`** (or **`POST /agents/spawn`**) with **`continuous: true`**, optional **`plan_id`**, **`max_iterations`** (default 20, capped), **`iteration_delay_seconds`** — repeats `autonomous_run` until iterations exhausted, cooperative cancel, or **`plan.status`** is **`done`** or **`blocked`**. Works in **thread** mode and **subprocess** mode (`background_job_worker.py`).

**Strict planning mode:** Set **`planning_strict_mode: true`** in `runtime_config.json` when you want mutating / run-class tools to be refused unless the run is bound to an **approved** plan (`plan_id` on `POST /agent` or execution via **`/plans/.../execute`** / **`execute_plan`**). Exceptions for repo mapping: **`scan_repo`**, **`update_project_memory`**.

### File-backed plans (`/plan/*`, optional)

For JSON-on-disk plans with rich **Pydantic** steps (deps, tool hints, `paused`/`failed` states), use **`POST /plan/create`** with **`workspace_root`**, then **`POST /plan/{id}/add_steps`**, **`POST /plan/{id}/approve?workspace_root=`**, **`POST /plan/{id}/execute_next`** (foreground), or **`POST /plan/{id}/run_continuous`** (background). **`run_continuous` is rejected with HTTP 400** (`error`: **`file_plan_continuous_requires_thread_workers`**) when **`background_use_subprocess_workers`** is **true** — use in-process thread workers for file-plan step loops, or disable subprocess background mode. Plans live under **`.layla_plans/{plan_id}.json`**. Background jobs that set **`file_plan_id`** use **`services/engine_plans.run_plan_iteration`**: each tick either refines the plan (draft, or **`planning_strict_mode`** while not approved — analysis-only) or runs the next approved step via **`autonomous_run`**, then updates **`.layla/project_memory.json`** (`last_iteration`, `signals.last_step_count`). This is **separate** from SQLite **`/plans`** and **`layla_plans`**; pick one model per workflow or use both for different clients. Optional **`.layla/relationship_codex.json`**: helpers in **`services/relationship_codex.py`** (not loaded into prompts unless you wire it).

Tools **`scan_repo`** and **`update_project_memory`** are **dangerous** / **approval-gated** like other workspace writes.

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
   - `systemPromptAddition` (injected into the system head for that aspect)
   See existing files in `personalities/` for structure.

2. **Voice contract & prompt shape** (recommended): At the top of `systemPromptAddition`, use a short **VOICE CONTRACT** (2–4 lines the model should embody). Then structured sections:
   - **## Core** — what this facet is responsible for
   - **## Chat style** — tone, pacing, formatting
   - **## Hard limits** — approval/sandbox awareness, refusal boundaries, privacy/consent (especially for Echo-style continuity and Lilith ethics)
   Optional fields like `traits`, `triggers`, `decision_bias`, `nsfw_triggers`, `systemPromptAdditionNsfw` stay as today; do not remove keys the orchestrator expects unless you update `agent/orchestrator.py`.

3. **Register in orchestrator**: In `agent/orchestrator.py`, ensure the aspect is loaded (e.g. via `_load_aspects()` from the personalities directory). Add trigger phrases or explicit routing if needed (see `.cursor/rules/layla-assistant.mdc` for trigger table).

4. **Optional**: Add to deliberation roster, study bias, or decision bias in the orchestrator so the aspect is used for multi-aspect prompts when `show_thinking` is true.

5. **Docs**: Update `.cursor/rules/layla-assistant.mdc` (or equivalent) if the aspect is user-facing so Cursor/MCP knows the new aspect id.

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

6. **Chat exports / backups**: Put JSON or JSONL under your **sandbox**, then use tool **`ingest_chat_export_to_knowledge`** (or see [BACKUP_INGESTION_AND_ELASTICSEARCH.md](BACKUP_INGESTION_AND_ELASTICSEARCH.md)). Output is `knowledge/_ingested/chats/*.md` for normal indexing. Audio: transcribe with **`stt_file`**, then ingest or paste into `knowledge/`.

---

## Operator-local psychology texts (copyright + ethics)

Layla can **retrieve** psychology-oriented material from `knowledge/` like any other doc, but **you** are responsible for **copyright and redistribution**.

1. **Do not commit** full commercial manuals (e.g. DSM, proprietary textbooks) unless you have explicit rights and add a `!knowledge/...` exception in `.gitignore` on purpose. Default `knowledge/` is gitignored — keeping files **local-only** is the safe default.

2. **Your own notes** (summaries in your words, study bullets, collaboration preferences) **can** be committed if you add the appropriate `!knowledge/filename.md` exception.

3. **Indexing**: Same as [Add knowledge](#add-knowledge): with `use_chroma: true`, restart or touch files so `refresh_knowledge_if_changed` reindexes. Optional front matter:
   ```yaml
   ---
   priority: core
   domain: personality
   ---
   ```
   Reflective user messages also widen Chroma retrieval (see `_needs_knowledge_rag` in `agent/agent_loop.py`).

4. **Non-clinical boundary**: Layla is **not** a clinician. Product rules forbid assigning **psychiatric diagnoses** or **DSM/ICD labels** to the operator. See `docs/ETHICAL_AI_PRINCIPLES.md` §11 and `knowledge/echo-psychology-frameworks.md`.

5. **Config**: `direct_feedback_enabled` (blunt collaboration, opt-in) and `pin_psychology_framework_excerpt` (Echo/Lilith pinned reminder) — see `docs/CONFIG_REFERENCE.md`.

**Full reconsideration** (in-repo knowledge, optional libs, research tools, what to avoid): [`docs/OPERATOR_PSYCHOLOGY_SOURCES.md`](OPERATOR_PSYCHOLOGY_SOURCES.md).

---

## Geometry programs (CAD-style ops)

Layla can execute **versioned JSON programs** (`GeometryProgram` v1) that map to optional kernels: **ezdxf** (2D DXF), **cadquery** (3D export via subprocess), **OpenSCAD** (CLI), **trimesh** (mesh info), and an optional **HTTP bridge** for an operator-hosted CAD-sequence service.

1. **Schema**: `agent/layla/geometry/schema.py` — ops such as `dxf_begin`, `dxf_line`, `dxf_save`, `cq_box`, `openscad_render`, `mesh_info`, `cad_bridge_fetch`.
2. **Tools**: `geometry_validate_program` (safe), `geometry_execute_program` (writes under workspace; **approval** + `dangerous` like `generate_gcode`), `geometry_list_frameworks` (import/CLI probes).
3. **Config**: `geometry_frameworks_enabled`, `openscad_executable`, `geometry_subprocess_timeout_seconds`, `geometry_external_bridge_url`, `geometry_external_bridge_allow_insecure_localhost` in `runtime_config.json` (see `runtime_config.example.json`).
4. **Capabilities**: `geometry_kernel_ezdxf`, `geometry_kernel_cadquery`, `geometry_kernel_trimesh` in `agent/capabilities/registry.py` for discovery.
5. **Deps**: `pip install ezdxf` (minimum for DXF path); cadquery / trimesh / OpenSCAD are optional per op.

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

## Background workers: OS resources, shared inference, containers

Applies when `background_use_subprocess_workers` is `true` in `runtime_config.json` (`POST /agent/background`, `/agents/spawn`). Default remains in-process threads with cooperative cancel.

### Enforcement scope (Job Objects, cgroups, foreground)

| Surface | Subprocess worker | Thread background | Foreground `/agent` |
|---------|-------------------|-------------------|---------------------|
| Windows Job Object (memory / optional CPU %) | Yes, when `background_worker_windows_job_limits_enabled` | No | No |
| POSIX `RLIMIT_AS` / optional `RLIMIT_CPU` in worker | Yes, in child before LLM load | No | No |
| Linux cgroup v2 helper (`background_worker_cgroup_auto_enabled`) | Yes, parent moves child PID into a leaf cgroup when writable | No | No |

**cgroups are not Job Objects:** cgroups v2 can combine memory, CPU, and (with controllers) I/O; Windows Job Object limits in Layla are **best-effort ctypes** and may not match cgroup semantics. For production hard caps, prefer **systemd**, **Docker/Podman**, or a **delegated cgroup** subtree.

### Centralized inference service (zero duplicate GGUF)

Run **one** OpenAI-compatible or Ollama server (e.g. `llama-server`, vLLM, LiteLLM, Ollama) and set `llama_server_url` and/or `ollama_base_url` so `inference_backend` resolves to HTTP. The FastAPI process and every `background_job_worker.py` child then use **the same remote model** — no second GGUF load per worker. This is the supported architecture for subprocess-heavy setups.

### Shared inference (avoid duplicate GGUF per worker)

Each `background_job_worker.py` process reads the same `runtime_config.json` and runs `autonomous_run`. If inference resolves to **local** `llama_cpp` (no `llama_server_url` / `ollama_base_url`, or explicit `inference_backend: "llama_cpp"`), **every worker loads its own GGUF** into RAM.

**Recommended:** Run a single shared inference server and point Layla at it:

- **llama.cpp server / vLLM / LiteLLM / OpenAI-compatible**: set `llama_server_url` to the base URL (see `inference_backend` auto-detection in `services/inference_router.py`).
- **Ollama**: set `ollama_base_url` or a `llama_server_url` that includes port `11434`.

**Policy:** `background_subprocess_local_gguf_policy` — `warn` (log), `reject` (refuse enqueue), or `allow` (silent). Use `reject` if you require HTTP inference only.

### External CPU and memory limits (hard containment)

In-app limits are **best-effort** (see below). For **hard** caps, wrap the server or the worker with OS or container limits:

**Linux (systemd):**

```bash
systemd-run --user -p MemoryMax=8G -p CPUQuota=200% \
  --working-directory=/path/to/local-jinx-agent/agent \
  /path/to/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

**Docker / Podman** (see repo root `Dockerfile`; mount models, data, and workspace):

```bash
docker build -t layla:local .
docker run --cpus=4 --memory=8g -p 8000:8000 \
  -v layla-models:/app/models -v layla-data:/app/data \
  -v /your/workspace:/data/workspace:rw \
  layla:local
```

Set `sandbox_root` in `runtime_config.json` to a directory inside the mounted workspace (e.g. `/data/workspace`). Layla does not ship a default seccomp profile; dropping capabilities and read-only root are operator choices.

**Windows:** Use Job Objects externally, or run under WSL2 with the Linux patterns above. Optional in-repo: `background_worker_windows_job_limits_enabled` + `background_worker_windows_job_memory_mb` (best-effort).

**Why not rely on Python `RLIMIT_AS` alone?** On many systems, **mmap**’d model weights do not behave like a simple heap cap. Prefer **cgroups v2** (`MemoryMax`) or container memory limits for predictable RAM enforcement.

### Optional in-repo worker limits

| Key | Purpose |
|-----|---------|
| `background_worker_rlimits_enabled` | Linux/macOS: `setrlimit(RLIMIT_AS)` in the worker **before** `llama_cpp` import |
| `background_worker_rlimit_as_bytes` | Address-space cap in bytes |
| `background_worker_windows_job_limits_enabled` | Windows Job Object limits (ctypes): **memory** + optional **CPU %** hard cap |
| `background_worker_windows_job_memory_mb` | Job memory limit (MiB) |
| `background_worker_windows_job_cpu_percent` | Optional CPU hard cap (1–100); uses `JobObjectCpuRateControlInformation` when supported |
| `background_worker_rlimit_cpu_seconds` | POSIX worker: optional `RLIMIT_CPU` soft cap (seconds) before LLM import |
| `background_worker_cgroup_auto_enabled` | Linux: try to create a leaf cgroup and set `memory.max` / `cpu.max` (needs delegation) |
| `background_worker_cgroup_memory_max_bytes` | e.g. `8589934592` for 8GiB; empty to skip |
| `background_worker_cgroup_cpu_max` | cgroup v2 `cpu.max` string, e.g. `50000 100000` for 50% of one CPU |
| `background_worker_wrapper_command` | Argv prefix, e.g. `bubblewrap` / `firejail` — **operator-supplied** profile; Layla concatenates `wrapper + python + background_job_worker.py` |
| `background_progress_stream_enabled` | Default **true**: persist step progress on tasks (`progress_json`); subprocess workers emit NDJSON `type=progress` lines on **stderr** |
| `background_progress_min_interval_seconds` | Throttle for in-process step notifications |
| `background_progress_max_events` | Max events retained per task (trim oldest) |
| `background_job_max_stderr_bytes` | Cap stderr read while draining worker progress lines |

### Background progress vs foreground streaming

Foreground `POST /agent` with `stream: true` streams the **final** assistant reply over SSE. **Background** tasks expose **incremental tool-step progress** via `GET /agent/tasks` and `GET /agent/tasks/{id}`: `progress_events` (full list), `progress` (same list), and `progress_tail` (last *N* events, `background_progress_tail_max`), backed by SQLite `progress_json`. Subprocess workers write progress as **NDJSON on stderr**; **stdout** remains a single final JSON object. After a subprocess worker exits, Layla **best-effort** removes the leaf cgroup directory when cgroup auto-attach was used.

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

# GUI Audit 04 — Models & Kits · Research · Autonomy · Plans · Approvals

Deep, evidence-based audit. READ-ONLY. Every claim cites `file:line`. Repo root: `C:\Work\Programming\Layla`.
Backend: FastAPI routers under `agent/routers/`, services under `agent/services/`. UI: vanilla ES modules under `agent/ui/`.

**Scope note / correction to the brief:** The brief lists `agent/ui/components/models.js` and "models router under agent/routers/". `models.js` exists; **there is no `agent/routers/models.py`** — all model management is served by `agent/routers/settings.py` (`/setup_status`, `/setup/models`, `/setup/download`, `POST /settings`). Confirmed by directory listing and `sed: can't read agent/routers/models.py`.

---

## Key answers up front (the two questions the brief asked)

1. **Do research-mission depths (map/deep/full) and autonomous mode actually execute — not stubs?**
   - **Research missions: YES, fully implemented.** `map`/`deep`/`full` map to real stage runners in `agent/services/reasoning/research_stages.py` (`stages_for_depth`, `STAGE_RUNNERS`), each calling `autonomous_run` for real read/analyze work and writing to `.research_brain/`. `full` chains base-6 + 9 "intelligence" stages (`research_stages.py:373-380`). Not a stub.
   - **Autonomous investigation: YES it executes — but is gated OFF by default AND has no UI switch to turn it on.** `POST /autonomous/run` runs a real Tier-0 planner loop (`agent/autonomous/controller.py:69`), but the router returns HTTP 403 `autonomous_mode_disabled` unless `cfg["autonomous_mode"]` is true (`autonomous.py:50-51`), and the default is `False` (`runtime_safety.py:324`, and re-forced to `False` at `runtime_safety.py:737`). **`autonomous_mode` is NOT in `EDITABLE_SCHEMA`** (grep count 0), so `/settings/schema` never renders a toggle for it — the settings-full editor renders only schema fields (`settings-full.js:20,63`). Net: the autonomous panel is **UI-present, backend-real, but unreachable from the GUI without hand-editing `runtime_config.json`.**

2. **Is the approvals/governor safety model coherent?**
   - **Approvals: mostly coherent** (pending → approve/deny, TTL expiry, idempotency, grant-session vs grant-pattern). See gaps below (bypass/`safe_mode` not visible in this panel; grant-session command-glob is crude).
   - **Governor: two different, only-loosely-related systems share the word "mode," which is confusing.** `performance_mode` (auto/low/mid/high, config) caps ctx/tool budgets via `system_optimizer.get_effective_config`. The `ResourceGovernor` (WHISPER/BREATHE/SPRINT, idle-based) throttles background work/CPU. Neither is surfaced coherently and their defaults disagree (see §Governor).

---

## 1. MODELS & KITS

### 1.1 Hardware detection + model catalog + switch — `models.js` ↔ `settings.py`

**WHAT:** A persistent Models panel (overlay `#models-overlay`, `index.html:1195`) showing detected hardware, installed `.gguf` files, a downloadable catalog with per-model viability vs RAM, a switch-active-model button, and an SSE download with a progress bar.

**WHY:** Model install/switch previously lived only in the first-run wizard; this surfaces it at runtime (`models.js:1-16` docstring).

**HOW A USER USES IT + every option:**
- Open panel → `openModelsPanel()` (`models.js:35`), bound to `window.openModelsPanel` (`main.js:409`). `refreshModelsPanel()` fires on open.
- **Hardware chips** (`models.js:85-103`): RAM, GPU vendor/VRAM or "CPU inference", plus "Recommended for your hardware" and a suggestion line — from `/setup_status.hardware` and `/setup/models.recommended_key`.
- **Installed list** (`_renderInstalled`, `models.js:105-122`): each installed `.gguf`; the active one gets an "active" badge, others get a **Use** button → `switchActiveModel(idx)`.
- **Catalog** (`_renderCatalog`, `models.js:124-151`): name, `recommended`/`heavy` badges, description, "needs ~N GB", and a **Download** button when `m.url` exists (else "manual"). Non-viable rows dimmed to 0.6 and require a confirm.
- **Switch** (`switchActiveModel`, `models.js:154-173`): `POST /settings {model_filename}`; toast says *"Active model set — restart inference if a model is loaded."* → confirms switch is **not hot** (see §1.4).
- **Download** (`downloadCatalogModel`, `models.js:176-223`): opens `EventSource('/setup/download?url=…&filename=…')`, updates `#models-progress-bar` from `pct`, shows `dl_mb/tot_mb`, on `done` refreshes the panel.

**END-TO-END TRACE (download):**
- `models.js:194` `new EventSource('/setup/download?url=…')`
- → `settings.py:210` `setup_download(url, filename)`
- → SSRF guard `settings.py:216-218` (`is_safe_url`, public http(s) only)
- → resolve `models_dir`, sanitize filename, force `.gguf`, path-escape guard `settings.py:220-237`
- → background thread `urllib.request.urlretrieve` to `<name>.gguf.part` with a progress callback (`settings.py:249-266`)
- → SSE emits `{pct,dl_mb,tot_mb}` each pct change (`settings.py:269-279`)
- → on finish: validate GGUF (`is_valid_gguf`) else unlink `.part` (`settings.py:287-293`); **atomic** `.part → final` rename (`settings.py:296`); write `model_filename` + `models_dir` into config, invalidate cache (`settings.py:300-317`); emit `{done:true,filename}` (`settings.py:320`).

**Resumable?** **No.** `urlretrieve` restarts from byte 0 every call; no `Range`/HTTP-resume, no `.part` reuse across attempts (a new download overwrites/re-creates `.part`). On `onerror` the UI just says "Connection lost — press Refresh and retry" (`models.js:219-222`). *This is the single most notable gap for large 8B–70B GGUF downloads.*

**STATUS: working** (hardware detect, catalog, switch, download all functional end-to-end). Download is **non-resumable** (functional limitation, not broken).

### 1.2 Model params — which are live-tunable

Params live in `EDITABLE_SCHEMA` (category `llm`/`limits`) and are edited by the full settings editor + the `potato` preset (`config_schema.py:11-27`). The relevant knobs: `n_ctx`, `n_gpu_layers`, `n_batch`, `n_threads`, `top_p`, `top_k`, `repeat_penalty`, `temperature`, `completion_max_tokens`.

**Live vs load-time (traced):**
- `POST /settings` → `sync_save_settings` **only writes config + `invalidate_config_cache()`** (`route_helpers.py:48-69`). No model reload, no llama re-init.
- llama reads `n_ctx/n_gpu_layers/n_batch` from `load_config()` **at model-load time** (`llm_gateway.py:510,549-581`). So GPU/context/batch/threads changes take effect **only on next model load / app restart** — matching the switch toast.
- **Per-turn "effective" retuning DOES happen for a subset**: `system_optimizer.get_effective_config` recomputes `n_ctx`, `max_tool_calls`, `research_max_tool_calls`, `semantic_k`, `knowledge_chunks_k`, `knowledge_max_bytes`, `max_plan_depth` under `performance_mode` + live CPU/RAM/GPU pressure (`system_optimizer.py:72-167`). But this shapes **prompt/budget** decisions, not the already-loaded llama KV-cache (the loaded context size is fixed until reload).
- **Sampling params** (`temperature/top_p/top_k/repeat_penalty/completion_max_tokens`) are read per-generation from config, so those ARE effectively live (they are passed at call time, not baked into the model handle).

**Practical answer:** *Sampling* params (temperature/top_p/top_k/repeat_penalty/max_tokens) are live; *structural* params (n_ctx/n_gpu_layers/n_batch/n_threads) require a reload/restart. The UI does not communicate this distinction anywhere except the terse switch toast.

**STATUS: working** (params persist + apply), but **partial UX**: no live/needs-restart labeling; structural changes silently no-op until reload.

### 1.3 Model providers + costs + cot_stats

- **Providers/costs:** No provider/cost surface exists for this cluster. `agent/routers/intelligence.py` has no provider/cost/price logic (grep empty). There is no `/models/providers` route and no UI. Layla is local-first (GGUF), so "providers + costs" is effectively **N/A / not implemented** as a GUI feature.
- **`cot_stats`:** endpoint exists at `system.py:853 GET /agent/cot_stats` (`get_cot_stats` + `split_cot_models`), but **no UI caller** (grep of `agent/ui` empty).

**STATUS:** providers/costs = **not implemented (no UI, no backend for this cluster)**; `cot_stats` = **backend-without-ui**.

### 1.4 Switch-active-model reload gap
`switchActiveModel` sets `model_filename` but the toast admits inference must be restarted (`models.js:164`). There is no "reload model now" button in the panel. **STATUS: partial** — switch is durable but not applied to a live session.

---

## 2. GOVERNOR / PERFORMANCE_MODE

There are **two distinct subsystems** here; the brief's "governor / performance_mode (auto/low/mid/high)" conflates them.

### 2.1 `performance_mode` (auto/low/mid/high) — the config profile

**WHAT/HOW IT CAPS (traced, `system_optimizer.py:72-167`):**
- Resolution: missing/empty → treated as **`mid`** (`system_optimizer.py:92-94`); `auto` → hardware tier from VRAM (or RAM) thresholds (`system_optimizer.py:97-110`): VRAM `<6→low, <12→mid, else high`; RAM `<8→low, <24→mid, else high`.
- **low** (`system_optimizer.py:121-131`): `n_ctx≤2048`, `max_tool_calls≤3`, `research_max_tool_calls≤10`, `semantic_k≤3`, `knowledge_chunks_k≤3`, `knowledge_max_bytes≤2000`, `retrieval_cross_encoder_limit=0`, `max_plan_depth≤1`, `enable_cognitive_workspace=False`, planning off if depth 0.
- **high** (`system_optimizer.py:132-140`): raises the same knobs (ctx up to 8192, tool calls up to 8, research up to 50, plan depth up to 5, cognitive workspace on).
- **mid**: no preset change (`system_optimizer.py:141`).
- On top of the profile, **live pressure tiers** clamp further when CPU>90/RAM>90/GPU>95 (hard) or CPU>75/RAM>80/GPU>85 (soft) (`system_optimizer.py:151-165`).

**What it does NOT change:** it does not switch the model, does not change concurrency (that's the ResourceGovernor), and does not touch the loaded llama context (only future prompt/budget shaping).

**Default inconsistency (bug-class):** three sources disagree.
- `config_schema.py:98` default = `"auto"`.
- `runtime_safety.py:265` default = `"auto"`.
- `system_optimizer.py:92-94` treats missing key as **`mid`** (not auto).
- `config_schema.py:13` `"low"` is the **potato preset** value (not a default) — that one is fine.
Result: if the key is absent, effective behavior is `mid`; if present-but-empty, also `mid`; but the schema/UI advertise `auto`. Minor, but a user reading the setting will not get what the effective engine computes.

**UI:** `performance_mode` is exposed as a normal schema dropdown (`config_schema.py:94-100`, options auto/low/mid/high) and via the **potato** preset button (`/settings/preset`, `settings.py:421`). `/setup_status` echoes `performance_mode` (`settings.py:82,136`).

**STATUS: working** (the caps genuinely apply per turn), with a **default-resolution inconsistency** (schema=auto vs optimizer=mid) worth fixing.

### 2.2 `ResourceGovernor` (WHISPER/BREATHE/SPRINT) — the idle-based throttle

**WHAT (`resource_governor.py`):** OS-input-idle detection (Windows `GetLastInputInfo`, `resource_governor.py:90-101`) drives 3 modes: WHISPER (user active), BREATHE (1–10 min idle), SPRINT (10+ min). Controls background concurrency (`get_max_workers` 1/2/4, `:310-317`), whether background tasks run (`should_run_background`, `:319-332`), whether the heavy model loads (`should_load_model`, `:334-336`), suggested `n_gpu_layers`/`n_batch`/`n_threads` per mode (`:338-369`), and lowers OS process priority in WHISPER (`_apply_process_priority`, `:418-429`). Config keys `resource_governor_enabled` (default True), cpu caps, timeouts (`:132-142`).

**Coupling to model params:** `get_gpu_layers/get_batch_size/get_inference_threads` are *recommendations*; they are consumed by scheduler/worker code, not forced onto a running llama handle. So this governor primarily bounds **background** work, not the foreground chat model.

**UI:** No dedicated GUI surface in this cluster. `to_dict()` (`:392-407`) is built for an API/observability panel; the FEATURE-MAP routes governor state to Doctor/metrics, not here.

**STATUS: working (backend)**, **backend-without-ui** for this cluster's purposes.

**UX COHERENCE PROBLEM:** two "modes" (`performance_mode` low/mid/high vs governor whisper/breathe/sprint) with overlapping vocabulary and overlapping knobs (both touch n_ctx/gpu/batch) but no single place explaining which wins. This is a real comprehension hazard.

---

## 3. RESEARCH

### 3.1 analyse-repo — `POST /research` (`research.py:376`)

**WHAT:** Read-only repo Q&A. `sendResearch()` (`research.js:266`) posts `{message, repo_path, aspect_id, show_thinking, stream}`. Streaming path renders SSE tokens with full phase/stalled UX (`research.js:294-430`); non-stream path shows typing phases (`research.js:432-459`).

**Bounding:** `autonomous_run(..., allow_write=False, allow_run=False, research_mode=True)` (`research.py:390-402`). Prefixed with a strict read-only instruction (`research.py:35-39`). Output saved to `.research_output/last_research.md` + timestamped copies (`research.py:499-517`). Streaming variant re-runs via `stream_reason` (`research.py:404-467`).

**STATUS: working.**

### 3.2 Research MISSION — `POST /research_mission` (`research.py:42`) + depths

**WHAT:** Two modes inside one endpoint:
- **Depth mode** (`mission_depth ∈ {map,deep,full}`): runs staged pipeline. `startResearchMission()` reads the checked `input[name=mission-depth]` (`research.js:39-42`, radios at `index.html:705-707`), `next_stage` from `#next-stage`, and posts `{workspace_root, mission_depth, next_stage, mission_type:'repo_analysis'}` (`research.js:64-73`).
- **Preset mode** (no depth): single `autonomous_run` over a preset objective (`research.py:153-194`).

**What EACH depth actually does (traced `research_stages.py:383-405`):**
- **map** → `["mapping"]` — one stage: map structure/entrypoints/deps, writes `.research_brain/maps/system_map.json` (`run_mapping_stage`, `:154-190`).
- **deep** → `["mapping","investigation"]` — adds doc/pattern investigation → `investigations/notes.md` (`:193-224`).
- **full** → base-6 `(mapping, investigation, verification, contradiction_check, distillation, synthesis)` **+ 9 intelligence stages** appended when `research_intelligence` imports (`research_stages.py:373-380`, `FULL_PIPELINE_ORDER`). Verification runs lab-scoped `run_python` only (`:227-257`); synthesis appends `INSUFFICIENT_ACTIONABLE_INSIGHT` if the usefulness gate fails (`:350-351`).
- Each stage calls `autonomous_run(allow_write=True, allow_run=False, research_mode=True)` sandboxed to `.research_lab` (`_run_stage`, `:121-151`). A stage returning `<500` chars is `no_progress`; **two consecutive** no-progress stages → mission marked `partial` and breaks (`research.py:140-144`).

**How long / bounding:** wall-clock cap **14400s (4h)** for the whole mission (`research.py:93,107-122`); on breach writes `strategic/incomplete.md` and status `stopped`. Each stage inherits the per-run limits from `autonomous_run`.

**Output:** combined markdown of stage sections (`research.py:145`), plus `.research_output/last_research.md` report (`research.py:206-229`), plus mission_state persisted with `completed`/`status`/`last_run` (`research.py:148-152`).

**Board / horizon / state / verify:**
- **state:** `GET /research_mission/state` (`research.py:271`) → status/completed/stage/last_run. UI polls every 5s (`research.js:614-617`, `refreshMissionStatus` `:109`). Shows "resumable" banner when status≠complete (`research.js:132`).
- **verify:** `GET /research_mission/verify` (`research.py:342`) → checks `mission_state.json` + `maps/system_map.json` + `last_research.md` exist → "MISSION PIPELINE READY FOR 24H AUTONOMOUS RUN". **No UI caller found** for `/verify` or `/debug`.
- **board/horizon:** these belong to the **separate** `missions.py` router (`/missions/board`, `/missions/horizon`) — **NOT** the research mission. See §6.

**Resume:** `next_stage` preserves prior state so completed stages aren't re-run (`research.py:96-99`, `stages_for_depth(next_stage=True)` appends the next stage `:397-404`). UI exposes Resume via `startResearchMission(true)`.

**STATUS: working** (depths genuinely execute staged `autonomous_run`s). `/research_mission/verify` + `/debug` = **backend-without-ui** (diagnostics).

### 3.3 Research brain tabs — `showResearchTab` (`research.js:239`)
Reads whitelisted brain files (`RESEARCH_BRAIN_PATHS`, `research.js:231-236`) via `GET /research_brain/file?path=` (path-allowlisted, `research.py:302-312`) plus `/research_output/last`. **STATUS: working.**

---

## 4. AUTONOMOUS INVESTIGATION

### 4.1 `POST /autonomous/run` (`autonomous.py:42`) + `laylaRunAutonomousResearch` (`research.js:515`)

**WHAT:** A read-only ("Tier-0") multi-step planner loop over a repo. UI inputs: `#autonomous-goal`, `#autonomous-confirm` (required), `#autonomous-research-mode`, `#autonomous-max-steps` (default 30, clamp 1–500), `#autonomous-timeout` (default 120, clamp 5–7200) (`research.js:516-531`, HTML `index.html:965-972`).

**The 3 templates + investigation preset (`research.js:474-512`):**
- `laylaInvestigationTemplateTrace` → symbol/API trace across repo.
- `laylaInvestigationTemplateStructure` → repo structure/coupling analysis.
- `laylaInvestigationTemplateBug` → error-path/root-cause hypotheses, verification-steps-only.
- `laylaRunInvestigation` → generic bug/risk sweep. Each preset sets goal + checks research_mode + confirm, then calls `laylaRunAutonomousResearch()`.

**HOW IT'S BOUNDED (traced):**
1. Config gate: `autonomous_mode` must be true → else **403** (`autonomous.py:50-51`). **Default False** (`runtime_safety.py:324,737`).
2. `confirm_autonomous` required → else 400 (`autonomous.py:53-55`).
3. Locality gate: non-local requests forbidden unless `remote_enabled` + path allowlisted (`autonomous.py:57-66`).
4. **Value gate** (`value_gate.py:62-101`): deterministic heuristic. Rejects trivial greetings, direct-action phrasing (`write/create/delete/run/execute/git push/pip install/implement…`, `:24-37`), and short low-leverage asks; needs score ≥3 to proceed. Blocked goals return `source:"blocked"` with "use POST /agent" (`controller.py:78-99`).
5. **Prefetch/reuse short-circuit**: before planning, tries reuse-jsonl → wiki → chroma; a hit returns cached findings with `steps_used:0` (`controller.py:105-197`). This is why the UI summary shows `Source: reused knowledge / wiki / fresh / blocked` (`research.js:579-586`).
6. **Budget** (`budget.py`): `max_steps` and `timeout_seconds` enforced per step; exceeding raises `BudgetExceeded` → `stopped_reason` (`controller.py:215-292`).
7. **Policy allowlist**: only read tools; `allow_write` is derived **only** from `autonomous_wiki_enabled AND autonomous_wiki_export_enabled` (`autonomous.py:80`), `allow_network=False` (`autonomous.py:90`). So even when "enabled," it cannot edit source — at most write a `.layla/wiki` markdown entry when confidence=high and ≥2 files read (`controller.py:31-66`, gated at `_maybe_export_wiki_markdown`).

**HOW RESULTS SURFACE:** synchronous JSON response parsed into a summary block: steps used, stopped reason, budget detail, confidence, source, reused, files accessed (first 12), trace excerpt (`research.js:574-600`); full JSON dumped into `#autonomous-result` (`research.js:597-600`). During the run, the UI polls `/agent/tasks/<taskId>` every 500ms for `progress_tail` (`research.js:543-553`) — the router streams tool events into that task when `progress_task_id` is supplied (`autonomous.py:93-124`, `_append_progress_event`).

**END-TO-END TRACE:**
- `research.js:556` `POST /autonomous/run {goal, workspace_root, max_steps, timeout_seconds, research_mode, confirm_autonomous, progress_task_id}`
- → `autonomous.py:49-66` gates (autonomous_mode/confirm/locality)
- → `autonomous.py:82-91` build `AutonomousTask`
- → `autonomous.py:114-116` `register_inline_progress_task` + `run_autonomous_task`
- → `controller.py:78` value gate → `controller.py:105` prefetch → `controller.py:204-292` planner loop (per-step: `policy.validate_tool_call` → tool fn → cache → audit) → `controller.py:294-333` aggregate + reuse-append + optional wiki export
- → `autonomous.py:117` JSON back; `autonomous.py:123-124` finalize progress task.

**STATUS: backend-real + working, but UI-unreachable by default (ui-without-usable-backend-path).** The panel exists, the loop is real, but no GUI control sets `autonomous_mode=true`, and it is force-reset to False at startup (`runtime_safety.py:737`). **This is the cluster's #1 coherence defect.**

### 4.2 Autonomous execution monitor — `autonomous.js`
`laylaAutoMonitorStart` (`autonomous.js:24`) shows `#auto-monitor-panel` and polls `/agent/tasks/<id>` every 1.5s (`autonomous.js:37-49`), rendering step count, progress bar, trace lines, and an outcome card with score/issues (`autonomous.js:127-154`). It monkeypatches `window.laylaRunAutonomousResearch` to auto-start monitoring (`initAutoMonitorHook`, `:157-174`).
**STATUS: working** (but only meaningful once autonomous is enabled).

### 4.3 Background tasks — `/agent/tasks` (`agent_tasks.py`)
`GET /agent/tasks` merges in-memory `_TASKS` with SQLite rows so completed tasks survive restarts (`agent_tasks.py:157-195`); `GET /agent/tasks/{id}` (`:198`); cancel via DELETE or POST `/cancel` (`:230-241`, cooperative `client_abort_event`). Also `/agent/background` (enqueue), `/resume` (checkpoint resume), `/execute_plan`, `/agent/persistent_tasks/{id}/resume` (coordinator re-entry). Consumed by both research.js polling and autonomous.js. **STATUS: working.**

---

## 5. PLANS

### 5.1 Durable plans (SQLite `layla_plans`) — `plans.py` (prefix `/plans`) ↔ `workspace.js`

**WHAT:** CRUD + lifecycle for durable plans. UI in the Workspace "Plans" tab (`#layla-plans-list`, `index.html:836`).

**Lifecycle + every option (traced):**
- **Create** `POST /plans` (`plans.py:53`): planner generates steps (`planner_create_plan`, `plans.py:78-81`) or accepts provided steps; status `draft`; mirrors to workspace files (`_persist_plan_workspace_files`).
- **List** `GET /plans?workspace_root&status&limit` (`plans.py:102`) → `refreshLaylaPlansPanel` (`workspace.js:249-277`), buttons: **Approve / Execute / ⬡ Gantt / Detail**.
- **Approve** `POST /plans/{id}/approve` (`plans.py:201`): runs `validate_sqlite_plan_before_approval` gate (`plans.py:209-211`) then mirrors to project memory (`plans.py:215-217`). UI: `laylaApprovePlan` (`workspace.js:279-286`).
- **Execute** `POST /plans/{id}/execute` (`plans.py:221`): **requires status `approved`** else 409 (`plans.py:229-233`); reads `allow_write`/`allow_run` from `#allow-write`/`#allow-run` (`workspace.js:290-303`); runs `execute_plan` over `autonomous_run` with step governance + retries, persists step progress, sets status `executing→done/blocked`, appends plan history, **awards XP 20** on success (`plans.py:266-309`). UI: `laylaExecutePlan` (`workspace.js:288-310`).
- **Patch** `PATCH /plans/{id}` (`plans.py:158`): blocked once `executing`/`done` (`plans.py:166-167`); returns step-improvement suggestions.
- **Detail** `GET /plans/{id}` → `laylaExpandPlan` (`workspace.js:312-324`).

### 5.2 Gantt viz — `/plans/{id}/viz` (`plans.py:349`) ↔ `plan-viz.js`
`laylaShowPlanViz(planId)` (`plan-viz.js:20`) fetches `/plans/{id}/viz`, renders a canvas Gantt with dependency-chain x-positions, status colors, duration labels, bezier dependency arrows (`plan-viz.js:52-179`), and a "similar past plans" strip via `/plans/similar` (`plan-viz.js:196-215`, `plans.py:112`). Backend enriches steps with `estimated_duration_ms` (heuristic by tool/keyword, `plans.py:327-346`), `depends_on` (defaults to prior step), `parallel_capable` (any shared predecessor). **STATUS: working.**

### 5.3 File-backed plans — `plan_file.py` (prefix `/plan`)
Endpoints: `/plan/create`, `/plan/{id}`, `/plan/{id}/approve`, `/plan/{id}/add_steps`, `/plan/{id}/execute_next`, `/plan/{id}/run_continuous` (`plan_file.py:10-95`). Mounted (`main.py:820`). **No UI caller** (grep of `agent/ui` empty). **STATUS: backend-without-ui** — the GUI uses only the SQLite `/plans` path; the file-backed `/plan` API is a parallel, GUI-orphaned surface (duplicate-ish capability).

### 5.4 XP-on-step-success link
XP is awarded on **plan completion** (`plans.py:304-308` and `agent_tasks.py:120-125`, +20), on **research mission** (+50, `research.py:233-240`), and on **approval execution** (+15, `approvals.py:105-112`) — all via `maturity_engine.award_xp`, best-effort. There is no per-*step* XP hook in this path (award is at whole-plan granularity). **STATUS: working** (plan-level), brief's "XP-on-step-success" is really XP-on-plan-success.

---

## 6. `missions.py` — the OTHER mission router (board/horizon/lifecycle)

**WHAT:** Full mission lifecycle over SQLite missions: `POST /mission`, `GET /mission/{id}`, `GET /missions`, pause/resume/cancel, `GET /missions/board` (kanban backlog/running/paused/done), `GET /missions/horizon` (long-horizon checkpoints) (`missions.py:27-166`). Mounted (`main.py:888`).

**STATUS: backend-without-ui (never-called from GUI).** Confirmed: the only UI reference to "mission" is `research.js` hitting `/research_mission` (a different router in `research.py`). No `agent/ui` file calls `/mission`, `/missions`, `/missions/board`, or `/missions/horizon`. This is a complete, functional mission-management API with **zero GUI surface** — the brief's "mission board/horizon" is not wired to any screen.

---

## 7. APPROVALS

### 7.1 Queue — `approvals.py` ↔ `research.js:refreshApprovals`

**WHAT:** Pending tool-call approval queue. `refreshApprovals()` (`research.js:143`) polls `GET /pending` (`approvals.py:14`), renders cards with tool name, id, optional unified-diff block, pretty-printed args, and per-card controls (`research.js:156-224`). Also surfaced in the calmer `#approvals-list` slot (`index.html:651`).

**Every option + what it authorizes (traced):**
- **Approve** `POST /approve {id, save_for_session?, grant_pattern?}` (`approvals.py:19`):
  - TTL check: rejects if `expires_at` passed → 410 (`approvals.py:38-55`; TTL from `approval_ttl_seconds`, default 3600, `config_schema.py`).
  - Idempotent: re-approving an executed entry returns the prior result (`approvals.py:34-36`).
  - Executes the tool from `TOOLS` registry, stripping preview-only keys `{goal,diff}` (`approvals.py:89-97`).
  - **grant_pattern** → `add_tool_permission_grant(tool, pattern, scope="permanent")` — a **persistent** path-glob grant for that tool (`approvals.py:68-73`), stored in SQLite.
  - **save_for_session** → `add_session_grant(tool, scope, args)` — **in-memory until process restart**; for command tools it globs the first two tokens (`approvals.py:74-86`, crude: `"git status *"`).
  - Awards XP 15 on success (`approvals.py:105-112`).
- **Deny** `POST /deny {id}` (`approvals.py:117`): marks `denied` so the agent knows (`research.js:207-224`).
- **Session grants:** `GET /session/grants` + `POST /session/grants/clear` (`approvals.py:139-157`). Clear-all exists; **no per-grant revoke UI** and no GUI panel lists active grants (endpoints are backend-without-ui).

**grant-session vs grant-pattern — precise difference:**
- **grant-pattern** = durable (SQLite, "permanent"), tool + path-glob; survives restart; broad.
- **grant-session** = ephemeral (memory), tool (+ crude command glob); cleared on restart or via `/session/grants/clear`.

**STATUS: working** (approve/deny/TTL/idempotency/both grant types all functional).

### 7.2 Bypass / `safe_mode` interaction — coherence check

- The **decision to require approval** is upstream of this panel: `safe_mode` (default True, "require approval for writes/exec", `config_schema.py`) and the bypass-approvals toggle (FEATURE-MAP §C group 6). This panel only *services* the queue; it does not show whether bypass/safe_mode is on. So a user could enable bypass elsewhere and this panel would simply go empty — with **no indication** that approvals are being skipped.
- Remote clients are blocked from flipping `safe_mode`/sandbox via `_REMOTE_PROTECTED_KEYS` (`settings.py:29-41`, enforced `:396-404`) — good.
- **Coherence gap:** the safety story is split across three surfaces (Permissions settings for safe_mode/bypass, this approvals queue, and the separate session-grants API with no UI). There is no single "what is currently authorized / am I in bypass" status. Combined with autonomous_mode having no toggle, the *authorization* model is functional but **not legible** from one place.

---

## STATUS TABLE

| # | Feature | Endpoint(s) / File | Status | Evidence |
|---|---------|--------------------|--------|----------|
| 1 | Hardware detect + catalog + install (models panel) | `settings.py:44,152,210` · `models.js` | **working** | full SSE download trace `settings.py:210-324` |
| 2 | Model download resumability | `/setup/download` | **partial (non-resumable)** | `urlretrieve` from 0, no Range; `settings.py:259`; UI retry-only `models.js:219` |
| 3 | Switch active model | `POST /settings` · `models.js:154` | **partial** | writes only, "restart inference" toast `models.js:164`; no hot reload |
| 4 | Model params live-tunable | `route_helpers.py:48` · `llm_gateway.py:510` | **partial** | sampling live; structural (ctx/gpu/batch/threads) load-time only |
| 5 | Model providers + costs | — | **not implemented** | no route, no UI (intelligence.py empty) |
| 6 | `cot_stats` | `system.py:853` | **backend-without-ui** | no `agent/ui` caller |
| 7 | `performance_mode` low/mid/high caps | `system_optimizer.py:72-167` | **working** (default inconsistency) | schema=auto vs optimizer=mid `:92-94` |
| 8 | ResourceGovernor (whisper/breathe/sprint) | `resource_governor.py` | **working / backend-without-ui** | not surfaced in this cluster |
| 9 | analyse-repo | `POST /research` (`research.py:376`) · `research.js:266` | **working** | read-only run trace `research.py:390-402` |
| 10 | Research mission depth=map | `research_stages.py:389` | **working** | `["mapping"]`, real `autonomous_run` `:154-190` |
| 11 | Research mission depth=deep | `research_stages.py:391` | **working** | `["mapping","investigation"]` `:193-224` |
| 12 | Research mission depth=full | `research_stages.py:373-394` | **working** | base-6 + 9 intelligence stages |
| 13 | Mission state / resume / next_stage | `research.py:271` · `research.js:109` | **working** | 5s poll, resumable banner `research.js:132` |
| 14 | Mission verify / debug | `research.py:315,342` | **backend-without-ui** | no UI caller |
| 15 | Autonomous investigation loop | `autonomous.py:42` · `controller.py:69` | **backend-real, UI-unreachable by default** | 403 unless `autonomous_mode` (default False `runtime_safety.py:324,737`); no schema toggle |
| 16 | Autonomous 3 templates + preset | `research.js:474-512` | **working (blocked by #15 gate)** | trace/structure/bug presets |
| 17 | Value gate / budget bounding | `value_gate.py` · `budget.py` | **working** | score≥3 gate; step/time budget |
| 18 | Autonomous monitor + progress poll | `autonomous.js` · `/agent/tasks` | **working** | 1.5s poll `autonomous.js:37` |
| 19 | Background tasks | `agent_tasks.py` | **working** | SQLite+memory merge `:157-195` |
| 20 | Durable plans CRUD/approve/execute | `plans.py` · `workspace.js:249` | **working** | execute gate `plans.py:229` |
| 21 | Plan Gantt viz + similar | `plans.py:349,112` · `plan-viz.js` | **working** | canvas Gantt `plan-viz.js:52` |
| 22 | File-backed plans `/plan/*` | `plan_file.py` | **backend-without-ui (duplicate)** | no UI caller; SQLite path used instead |
| 23 | Mission lifecycle + board + horizon | `missions.py` | **backend-without-ui (never-called)** | no `agent/ui` caller for `/mission(s)` |
| 24 | XP on plan/mission/approval | `maturity_engine.award_xp` | **working** | +20/+50/+15 `plans.py:307`,`research.py:238`,`approvals.py:110` |
| 25 | Approvals queue approve/deny/TTL | `approvals.py` · `research.js:143` | **working** | TTL 410 `approvals.py:38-55` |
| 26 | grant-session vs grant-pattern | `approvals.py:68-86` | **working** | permanent glob vs in-memory |
| 27 | Session grants list/clear | `approvals.py:139-157` | **backend-without-ui** | clear-all only, no panel |

---

## TOP UX PROBLEMS (ranked)

1. **Autonomous investigation is a dead end from the GUI (why/impact: HIGH).** The panel, 3 templates, monitor, and a real bounded backend all exist, but `autonomous_mode` defaults False (`runtime_safety.py:324`), is force-reset to False at startup (`:737`), and is **absent from `EDITABLE_SCHEMA`** so no settings toggle can enable it. Every click returns 403 `autonomous_mode_disabled`. Users get an error with no path forward. *Fix: add `autonomous_mode` to the schema (Permissions/Safety group) with a clear warning, or auto-prompt to enable on first run.*

2. **A whole mission-management product (board/horizon/pause/resume) has no screen (impact: HIGH — hidden value).** `missions.py` is fully built and mounted but never called by any UI; the kanban board and long-horizon checkpoints are invisible. Meanwhile the *research* "mission" (different router) is the only thing the UI shows, and the two share the word "mission" — maximally confusing. *Fix: either surface the missions board or clearly retire/rename it; disambiguate "research mission" vs "mission."*

3. **Two "modes" with overlapping names and knobs, no single explanation (impact: MED-HIGH).** `performance_mode` (auto/low/mid/high) and the ResourceGovernor (whisper/breathe/sprint) both throttle ctx/gpu/batch/concurrency but from different signals, and the `performance_mode` default is itself inconsistent (schema `auto` vs optimizer `mid`). A user tuning "performance" has no way to know which system is actually shaping a given run. *Fix: one "Performance" panel that shows the resolved effective config + current governor mode.*

4. **Model param changes silently no-op until reload; switch doesn't hot-swap (impact: MED).** Changing `n_gpu_layers`/`n_ctx`/`n_batch`/`n_threads` or switching the active model persists but doesn't apply to the loaded model (`route_helpers.py:48-69`, toast at `models.js:164`). Only sampling params are live. There's no "reload model" affordance and no live/needs-restart labeling. *Fix: label live vs restart params; add a "reload model" button.*

5. **Large-model downloads aren't resumable and fail opaquely (impact: MED).** For 8B–70B GGUFs, a dropped connection restarts from byte 0 (`settings.py:259`) and the UI only says "press Refresh and retry" (`models.js:219`). *Fix: HTTP Range resume + reuse `.part`.*

6. **The authorization/safety model is functional but not legible (impact: MED).** Approve/deny/TTL/grants all work, but "am I in bypass?", "what's currently granted?", and "is safe_mode on?" are spread across three surfaces (Permissions settings, the approvals queue, and a UI-less session-grants API `approvals.py:139-157`). An empty approvals list gives no hint that bypass is silently skipping prompts. *Fix: a single "Permissions status" strip showing safe_mode/bypass state + active grants with per-grant revoke.*

7. **Diagnostic/verify endpoints are stranded (impact: LOW).** `/research_mission/verify`, `/research_mission/debug`, `/agent/cot_stats`, `/session/grants` — all real, none surfaced. Minor, but they represent built-and-forgotten value that belongs in Doctor.

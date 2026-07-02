# GUI Audit 05 — Workspace/Coding + Skills + Agents + Voice + Artifacts

**Scope:** the "Workspace" rail destination (currently the **Library** tab in the rebuilt shell), Skills, spawned Agents + blackboard, execution trace / tasks, Voice (STT/TTS), and Artifacts.
**Method:** read-only trace of `agent/ui/` → `agent/routers/` → `agent/services/`. Every hop cited `file:line`.
**Date:** 2026-07-02. Repo: `C:\Work\Programming\Layla`.

Three headline answers up front:

1. **Is the sandbox actually enforced?** **Yes, and it fails closed.** All workspace file/index endpoints resolve the path and call `inside_sandbox()` (`agent/layla/tools/sandbox_core.py:152`), which uses `Path.relative_to` against a resolved `sandbox_root` and **refuses to run if the root is unset or equals `$HOME`** (`sandbox_core.py:78-90`). No string-prefix tricks.
2. **Are STT/TTS real?** **Yes — both are real, not stubs.** STT = `faster-whisper` (`agent/services/infrastructure/stt.py`), TTS = `kokoro-onnx` with a `pyttsx3` fallback (`agent/services/infrastructure/tts.py`). They degrade gracefully to 503 + structured recovery when the optional deps aren't installed, and the browser has a `speechSynthesis` fallback for TTS.
3. **What is a "skill" concretely?** **Two different things wear the same word.** (a) The **planner's** skills are a hardcoded Python dict `SKILLS` (`agent/layla/skills/registry.py:13`) — 60+ named tool-bundles (description + tool list + `sub_skills` + `execution_steps`), injected as a *prompt hint* so the LLM prefers grouped tools. (b) The **UI's "Skills" panel** lists **markdown `*.md` skills** discovered under the workspace (`.layla/skills/`, `skills/`, `.claude/skills/`) via `/skills` → `services.skills.load_skills` (`agent/services/skills/base.py:44`). These are **two separate registries that never reconcile** (see UX Problem #2).

---

## 1. WORKSPACE PATH + SANDBOX SCOPING

### 1.1 What "workspace" scoping means for file tools
- **WHAT:** `sandbox_root` (config key, `agent/config_schema.py:36` — *"Workspace root. Layla can only read/write within this path."*) is the single containment boundary. Every file/exec/index tool checks membership with `inside_sandbox()`.
- **WHY:** local-first safety — Layla runs with real filesystem + shell tools, so a hard boundary is the primary guard against touching the user's whole disk.
- **HOW ENFORCED (the heart):** `agent/layla/tools/sandbox_core.py`
  - `_get_sandbox()` (`:58`) resolves the effective root. It supports a thread-local override (`set_effective_sandbox`, `:49`) used by research missions (a `.research_lab/workspace`), else reads `cfg["sandbox_root"]`. **Critical safety line:** if the root is empty or equals `$HOME` it raises *"Cannot determine sandbox root — refusing to execute without containment"* (`:78-81`). Cached 2 s per-thread (`:68-70`).
  - `inside_sandbox(path)` (`:152`) → `resolved.relative_to(sandbox)`; on the RuntimeError from `_get_sandbox` it **logs and denies** (`:159-161`); any `ValueError`/exception → deny (`:162-163`). Fails closed.
  - `search_codebase` (`agent/layla/tools/impl/code.py:79-88`) and `run_python` (`:90-99`) both re-check `inside_sandbox` before doing anything.
  - Shell layer additionally has a hard blocklist (`rm`, `del`, `format`, `powershell`, `cmd`, …, `sandbox_core.py:93-97`) and a network denylist (`curl`, `wget`, `ssh`, …, `:100-104`) that apply **even with `allow_run=True`**.
- **What can Layla touch:** only paths under the resolved `sandbox_root` (or the active research-lab override). Everything else is denied at the tool boundary.
- **STATUS:** **working.** The enforcement is real, centralized, and fails closed. The web endpoints that expose file content re-check independently too (`/file_content`, `workspace.py:263-288`, returns 403 if `sandbox_root` unset or path outside).

### 1.2 Workspace-path input + the workspace tools
- **UI:** `#workspace-path` input (`index.html:667`, in Settings) is the shared path field; the Library "Workspace tools" subpage reads it.
- **Refresh awareness** — button `data-action="laylaRefreshWorkspaceAwareness"` (`index.html:791`) → `workspace.js:360` → `POST /workspace/awareness/refresh` (`agent/routers/workspace.py:190-216`). Backend re-checks `inside_sandbox`, then calls `refresh_for_workspace_sync` (re-scans project memory + Chroma index). **What gets indexed:** `.layla/project_memory.json` structural scan + the semantic/Chroma index for that workspace.
  - **HOP TRACE:** `index.html:791` → `main.js` (registers `laylaRefreshWorkspaceAwareness`) → `workspace.js:360-373` → `routers/workspace.py:190` → `services.workspace.workspace_awareness.refresh_for_workspace_sync`.
  - **STATUS:** **working** (guarded: requires workspace path, `showToast('Set workspace path first')` if empty).
- **Project-memory inspector** — `data-action="laylaLoadProjectMemoryInspector"` (`index.html:795`) → `workspace.js:375-392` → `GET /workspace/project_memory?workspace_root=…` (`workspace.py:219-235`). Read-only view of `.layla/project_memory.json`; sandbox-checked. Renders `modules/issues/plans/todos` sections into `#project-memory-inspector`.
  - **STATUS:** **working.**
- **Symbol search** — input `#workspace-symbol-query` + `data-action="laylaWorkspaceSymbolSearch"` (`index.html:799-800`) → `workspace.js:394-406` → `GET /workspace/symbol_search?q=…` (`workspace.py:238-260`) → `search_codebase` (`code.py:79`) → `search_symbols` (`services.workspace.code_intelligence`). **Index backing it:** AST symbol extraction + semantic chunk matches (`k=25`), sandbox-gated. Result is dumped as raw JSON into a `<pre>` (`workspace.js:404`).
  - **STATUS:** **working but raw** (functional; presented as unformatted JSON — see UX Problem #5).

---

## 2. PROJECT CONTEXT + PROJECT PRESETS

### 2.1 Project context editor (name/stage/goals/progress/blockers)
- **WHAT/WHY:** a small persisted "what am I working on" record that Layla injects into the system prompt so a chat turn is project-aware.
- **UI:** `refreshPlatformProjects()` (`workspace.js:67-135`) renders the read view **and** an inline editor (`#pc_name/#pc_stage/#pc_goals/#pc_progress/#pc_blockers` + Save button, `:104-110`). Save handler (`:117-133`) → `POST /project_context`.
- **WHERE THE DATA GOES:** `POST /project_context` (`workspace.py:161-173`) → `sync_set_project_context` (`services/infrastructure/route_helpers.py:96-109`) → `set_project_context(...)` into **SQLite** (`layla.memory.db`). Read back via `GET /project_context` / `GET /platform/projects` → `get_project_context()` (`workspace.py:127-145`).
- **HOW IT FEEDS A CHAT TURN:** `services/prompts/system_head_builder.py` calls `get_project_context()` in **three** places and appends a "Project: … | Lifecycle: …" line into the system head (`:246-249`, `:612-640`; domains also pulled at `:412-414`). So every turn is project-aware whenever a context row exists. This is **always-on**, independent of the discovery-auto-inject flag below.
- **STATUS:** **working.** After save it also calls `window.updateContextChip()` (`workspace.js:131`) to refresh the header chip.

### 2.2 `project_discovery_auto_inject`
- **WHAT:** *separate* from §2.1. When project memory is **sparse**, inject a *deterministic filesystem scan brief* (not the LLM discovery tool) into the system head.
- **TRACE:** config key `project_discovery_auto_inject` (default **False**, `config_schema.py:69`, `runtime_safety.py:473`) → `build_workspace_discovery_brief` (`services/workspace/project_discovery_hooks.py:40-78`). Gate order: flag on (`:41`) → workspace set (`:43`) → `workspace_memory_is_sparse` (`:50`, `:14-37`) → `inside_sandbox` (`:56`) → `discover_project` filesystem scan → emits "[Workspace scan — project memory sparse …]" brief.
- **STATUS:** **working, off by default.** Correctly uses the deterministic `discover_project`, not the paid LLM `run_project_discovery`.

### 2.3 Project select / new (presets)
- **WHAT:** named presets binding a workspace_root + default aspect + skill paths + system preamble (`/projects` CRUD, `agent/routers/projects.py`). The active preset id lives in `localStorage['layla_active_project_id']` (read at `workspace.js:76`).
- **TRACE:** `GET /projects` list (`projects.py:10`), `POST /projects` create (`:20`), `GET/PATCH/DELETE /projects/{id}` (`:40/:53/:67`) → `layla.memory.db` project CRUD. `refreshPlatformProjects` fetches the active preset and shows its `workspace_root` + `aspect_default` (`workspace.js:94-100`).
- **STATUS:** **working (backend)**; UI is **partial** — the panel *displays* the active preset and tells you to "Select a preset in Prefs → Project preset" (`workspace.js:99`), but there is **no create/select preset control inside this panel**; selection lives elsewhere (Prefs). The project *context editor* is here; the project *preset picker* is not. Mild fragmentation.

---

## 3. STUDY PLANS (spaced learning)

- **WHAT:** lightweight "topics Layla should study when you're active." Each plan = topic + status + session count. Not flashcards — a scheduler-driven autonomous-study queue.
- **WHY:** lets Layla do background self-education on things you care about between sessions.
- **HOW A USER USES IT (Library → Study subpage, `index.html:815-857`):**
  - See list — `#study-list`, `refreshStudyPlans()` (`workspace.js:155-169`) → `GET /study_plans` (`routers/study.py:154-190`); session counts derived from the `audit` table (`study.py:166-172`).
  - Quick-pick presets — `#study-presets`, `loadStudyPresetsAndSuggestions()` (`workspace.js:171-188`) → `GET /study_plans/presets` (6 curated topics, `study.py:58-65,124-126`).
  - Workspace suggestions — `#study-suggestions` ← `GET /study_plans/suggestions` (`study.py:129-141`): single-level scan of `sandbox_root` (README title + file-extension heuristics, `study.py:68-106`). No network.
  - Add topic — `#study-input` + `data-action="addStudyPlan"` (`index.html:829-830`) → `workspace.js:190-201` → `POST /study_plans` (`study.py:221-236`).
  - **Topic-from-chat** — two buttons (`index.html:824-825`): `studyTopicFromChatInput` (`workspace.js:203-211`, reads `#msg-input`) and `studyTopicFromLastUserMessage` (`workspace.js:213-225`, reads last user bubble) → `POST /study_plans/derive_topic` (`study.py:144-151`) → heuristic `_derive_topic_from_message` (`study.py:109-121`, **no LLM**) → then `addStudyPlan`.
- **HOW SCHEDULED:** config `scheduler_study_enabled` (default True, `config_schema.py:89`), `scheduler_interval_minutes` (30), `scheduler_recent_activity_minutes` (90). The actual study run happens in **`GET /wakeup`** (`study.py:262-511`): if `active_plans` and `get_run_autonomous_study()` is set, it picks the least-recently-studied plan (`study.py:410`) and runs it (`run_study(plan)`, `:412`), optionally recording capability practice. (The scheduler service periodically hits wakeup; the wakeup route is the execution point.)
- **STATUS:** **working.** Delete exists (`DELETE /study_plans/{id}`, `study.py:193-204`) but there is **no delete button in the UI** — plans can be added and listed but not removed from the panel (backend-without-ui for delete). Minor gap.

---

## 4. SKILLS + SKILL-PACKS

### 4.1 What a skill *is* (two registries)
- **Planner skills (hardcoded):** `SKILLS: dict` in `agent/layla/skills/registry.py:13-572` — e.g. `analyze_repo`, `debug_code`, `write_python_module`, `data_analysis`, … Each entry = `{description, tools[], sub_skills[], execution_steps[]}`. **Purely declarative.** `get_skills_prompt_hint(cfg)` (`registry.py:584-608`) turns them into a prompt block ("Skills (prefer these over raw tools…)"). **These `execution_steps` are never executed programmatically** — they're prose in the prompt; the LLM still chooses tools itself. `resolve_skill_chain`/`get_skill_dependencies` (`:611-629`) exist but only compute an ordering; grep shows no runtime caller executes a chain (only the prompt-hint path is wired).
  - **Where invoked:** `services/planning/planner.py:351-352` imports and calls `get_skills_prompt_hint(cfg)` → injected into the planning prompt. Gated by `skills_enabled` (default True, `registry.py:589`).
  - It also appends **markdown** skills via `load_markdown_skills_prompt` (`registry.py:600-607` → `services/skills/markdown_skills.py:77-104`, reads `SKILL.md` frontmatter under `<repo>/skills` or `markdown_skills_dir`).
- **UI "Skills" panel (markdown only):** Library → Plugins subpage (`index.html:923-926`), `data-action="refreshSkillsList"` → `workspace.js:231-243` → **`GET /skills`** (`routers/system.py:94-111`) → `services.skills.load_skills(sandbox_root)` (`agent/services/skills/base.py:44-76`). Discovers `*.md` in `.layla/skills/`, `skills/`, `.claude/skills/`, `.cursor/skills/`. Returns `{name, triggers, description, path}`.
  - Runtime use of markdown skills: `pick_skills_for_goal` / `skills_prompt_block` (`base.py:79-105`) score skills by trigger/desc match against the goal and inject the best 1–2 into the system head (`system_head_builder.py:701-705`).
- **THE DISCONNECT:** the panel calls `/skills` (markdown) and shows `s.name`/`s.description`, but `/platform/plugins` shows `skills_added` counting the **hardcoded** dict via a *different* import (`from layla.skills.registry import SKILLS`, `workspace.py:69-71`). A user opening "Skills" sees the markdown set (**usually empty** in a fresh workspace) while the plugin count shows ~60 — with no explanation. See UX Problem #2.
- **STATUS:** planner-hint path **working**; markdown-skills list path **working**; **the two are semantically split and the UI surfaces the emptier one** → **partial/confusing**.

### 4.2 Skill-packs + rl/preferences
- **Backend exists:** `agent/services/skills/skill_packs.py`, `skill_manifest.py`, `skill_registry.py`, `skill_sandbox.py`, `skill_rollback.py`, `plugin_loader.py` — a fuller skill-pack/plugin system (manifest, sandbox, rollback).
- **UI:** **none in this cluster.** No `data-action` references skill-packs, install, or skill rl/preferences. There is a "Plugin status" read-only count only (`#platform-plugins`, `workspace.js:53-65`).
- **STATUS:** **backend-without-ui** (skill-packs / rollback / rl-preferences are code-complete but unsurfaced here).

---

## 5. SPAWNED AGENTS + BLACKBOARD

- **WHAT:** `POST /agents/spawn` (`agent/routers/agents.py:21-48`) queues an `autonomous_run` in a daemon thread at **agent-tier priority** (`kind="tiny_agent"`), returning `agent_id`/`task_id` and a `poll_path` of `/agent/tasks/{id}`. It is a thin wrapper over the same `enqueue_threaded_autonomous` used by `/agent/background` (`agents.py:7,25`; runner at `services/infrastructure/agent_task_runner.py:171`). Each agent gets its own `conversation_id` unless one is passed (`agents.py:44-46`). So a "tiny agent" = a background autonomous goal-run — same engine, different priority tag.
- **Blackboard:** `GET /agents/blackboard/{job_id}` (`agents.py:14-18`) → `shared_state.blackboard_get(job_id)` — a shared key/value scratchpad tiny agents can write to and others can read (cross-agent coordination).
- **WHAT THEY CAN DO:** whatever `autonomous_run` can — the full tool set, still bounded by the same sandbox + `allow_write`/`allow_run` flags passed in the request.
- **UI:** **NONE.** Grep across `agent/ui/` for `agents/spawn`, `agents/blackboard`, `spawn`, `blackboard` → **no matches**. The only "agents" surface is `#agents-resource-panel` (`refreshAgentsPanel`, `workspace.js:525-539`), which just shows **resource limits** (`max_active_runs`, `performance_mode`, CPU/RAM caps) from `GET /health?deep=true` — **it does not list, spawn, or inspect any agent.**
- **STATUS:** **backend-without-ui.** `/agents/spawn` + `/agents/blackboard` are fully implemented and callable (and reachable from the LLM's own tools/skills), but there is **no user-facing way to spawn a tiny agent or view the blackboard** from this cluster. The "Agents" panel is a misnomer — it's a resource gauge.

---

## 6. EXECUTION TRACE / TASKS PANEL

- **WHERE:** Dashboard tab (`data-rcp="status"`), `#exec-trace-json` (`index.html:471`) and `#tasks-list-json` (`index.html:479`), refreshed by `wsRefreshExecutionPanels()` (`workspace.js:474-512`).
- **Execution trace:** `GET /debug/state` → dumps the coordinator snapshot JSON into `<pre>` (`workspace.js:478-481`).
- **Tasks:** parallel fetch of `GET /debug/tasks?limit=40` (persisted coordinator tasks) **and** `GET /agent/tasks` (background/tiny-agent runs) (`workspace.js:486-489`). Background tasks render as cards with status/goal; running/queued ones get a **Cancel** button (`workspace.js:500-503`).
- **Cancel background task:** `cancelBackgroundTask(id)` (`workspace.js:514-519`) → `DELETE /agent/tasks/{id}` (`routers/agent_tasks.py:230-234`) → `_cancel_background_task_impl` (`agent_task_runner.py:869-897`). **Real cancel:** sets the thread's `cancel_event` (cooperative abort) and, for subprocess workers, hard-kills the process with a grace period (`:882-890`); idempotent on already-finished tasks (`:879-880`); updates SQLite (`:892-894`).
- **STATUS:** **working**, but presented as **raw JSON** (`exec-trace` and the persisted-tasks block are `JSON.stringify` dumps, `workspace.js:480,508`). Functional, developer-grade. See UX Problem #5.

---

## 7. VOICE (mic → STT → send; reply → TTS)

### 7.1 Mic → text → send (STT)
- **UI:** `#mic-btn` `data-action="toggleMic"` (`index.html:414`) → `voice.js:68` `toggleMic` → `startMic()` (`:76-101`, `getUserMedia` + `MediaRecorder`, `audio/webm`) → on stop, `transcribeAndSend(blob)` (`:117-144`) → `POST /voice/transcribe` with the raw `audio/webm` body.
- **Backend:** `routers/voice.py:14-38` → `is_stt_ready()` gate → `transcribe_bytes` in a thread (`voice.py:34`). Returns `{ok, text}` or **503 + structured recovery** when whisper isn't loaded (`voice.py:23-33`).
- **STT engine (REAL):** `services/infrastructure/stt.py` — `faster_whisper.WhisperModel`, model from `cfg["whisper_model"]` (default `base`, `stt.py:29,60`), `device=auto` (CUDA→float16, else int8, `:64-67`), `vad_filter=True` to skip silence (`:100`). On import failure it tries `ensure_feature("faster_whisper")` self-install (`:44-56`) and returns structured recovery if that fails.
- **After transcription:** the client fills `#msg-input`, calls `toggleSendButton()` then **auto-`send()`** (`voice.js:129-134`) — mic is a full one-shot dictate-and-send.
- **STATUS:** **working** (real STT; graceful 503 when dep missing). `whisper_model` options in the schema are `tiny/base/small/medium` (`config_schema.py:86`) — matches the prompt's spec.

### 7.2 Reply → speak (TTS)
- **UI trigger:** on assistant reply, `app.js:506` (streaming full text) and `app.js:542` (non-stream response) call `window.speakText(...)` **iff `window._ttsEnabled`**. Research replies do the same (`research.js:95,427,459`).
- **speakText:** `voice.js:147-172` → `POST /voice/speak` `{text, aspect_id}` → decodes the returned WAV via WebAudio and plays it; **on any failure falls back to browser `speechSynthesis`** with per-aspect rate/pitch (`speakReply`, `voice.js:24-31`, `TTS_VOICE_STYLES` `:14-21`).
- **Backend:** `routers/voice.py:41-85` → maps aspect → speed (`_ASPECT_SPEEDS`, `:61-64`) → `speak_to_bytes(text, speed_override)` in a thread → returns `audio/wav`, or **503 + recovery** when no engine (`:68-81`).
- **TTS engine (REAL):** `services/infrastructure/tts.py` — primary `kokoro-onnx` (`_init_kokoro`, `:48-88`, voice from `cfg["tts_voice"]` default `af_heart`, speed from `cfg["tts_speed"]`), fallback `pyttsx3` system voice (`_init_pyttsx3`, `:91-109`). `speak_to_bytes` (`:194-238`) writes WAV via `soundfile` (kokoro) or a temp file (pyttsx3). Self-install attempted via `ensure_feature("kokoro_tts"/"pyttsx3_tts")`.
- **Speak-replies toggle:** checkbox `#tts-toggle`/`#tts-toggle2` `data-on-change="toggleTts"` (`index.html:585,685`) → `main.js:436-439` sets `window._ttsEnabled` + `localStorage['layla_tts']` and mirrors both checkboxes. Persisted (`voice.js:41`).
- **STATUS:** **working**, with **two real defects:**
  1. **Volume slider is dead for server TTS.** `laylaVoiceVolumeChange` stores `window._laylaVoiceVolume` + `localStorage['layla_voice_volume']` (`perf.js:145-152`) but `speakText` plays the buffer through `source.connect(audioCtx.destination)` **with no GainNode** (`voice.js:158-164`) — the volume value is never applied. TTS always plays at 100%.
  2. **Speed slider is also unused for server TTS.** Server speed comes only from the per-aspect map (`voice.py:61-64`); the user's `#voice-speed-range` / `layla_voice_speed` (`perf.js:136-143`) and the config `tts_speed` are not passed on the reply path. (`tts_speed` *is* read at engine init, so it applies as a static default, but the live slider does nothing.)
  3. **Minor:** `speakText`'s internal guard checks the **module-local** `_ttsEnabled` (`voice.js:148`) which `toggleTts` never updates (it updates only `window._ttsEnabled`). Call sites all pre-check `window._ttsEnabled`, so replies still speak — but the two flags can drift.
- **Config/service voice-list mismatch:** schema `tts_voice` options = `af_heart, af_sky, am_adam, bf_emma, bm_george` (`config_schema.py:85`), but the service catalog `AVAILABLE_VOICES` (`tts.py:35-45`) has `af_bella/af_sarah/am_michael/bf_sarah/bm_lewis` and **no `af_sky`**. `af_sky` is offered in settings but is not a known kokoro voice here → likely silently ignored/falls back.

---

## 8. ARTIFACTS (client-side code extraction)

- **WHAT:** scrapes fenced code blocks out of Layla's messages into an "Artifacts" panel with copy / edit-and-send.
- **WHERE:** Artifacts tab (`data-rcp="artifacts"`, `index.html:931`), `#artifacts-list` (`:940`).
- **TRACE (all client-side):** `laylaExtractArtifacts(text)` regex ```` ```lang\n…``` ```` (`artifacts.js:15-28`); `laylaArtifactsScan()` walks `.msg.layla .msg-bubble` and dedupes by content (`:30-47`); `laylaIngestArtifacts(responseText)` auto-adds on each reply and badges the tab (`:49-66`); render `_renderArtifactsList` (`:74-97`). Actions: `laylaArtifactCopy` (clipboard, `:100-114`), `laylaArtifactEdit` → fills `#artifact-edit-overlay` (`:116-126`), `laylaArtifactSendEdit` → pastes `"Update this code:\n```…```"` into `#msg-input` for review (`:140-152`), `laylaArtifactRemove` (`:154-158`).
- **Auto-scan pref:** `laylaArtifactsAutoScan` / `laylaToggleArtifactsAutoScan` via `localStorage['layla_artifacts_autoscan']` (`perf.js:173-182`); lazy first-scan on tab open (`perf.js:85-92`).
- **CONFIRM CLIENT-ONLY:** grep for a `/artifacts` route → **none**. No server endpoint; nothing is persisted server-side. "Send edits back" just repopulates the composer — it does **not** write files or call a backend. Purely client-side. **Confirmed.**
- **STATUS:** **working** (client-only, as intended). Note the edit overlay's "Send edit" doesn't actually *send* — it pastes into the input and shows "review and send" (`artifacts.js:150`); the button label "Edit & send" slightly over-promises.

---

## STATUS TABLE

| # | Feature | Backend | UI | Status | Evidence |
|---|---------|---------|----|--------|----------|
| 1 | Sandbox enforcement (`sandbox_root`) | `sandbox_core.py:58-90,152-163` | n/a | **working** (fails closed) | refuses if root unset/`$HOME`; `relative_to` check |
| 2 | Workspace awareness refresh | `workspace.py:190-216` | `index.html:791` | **working** | sandbox-checked, re-indexes |
| 3 | Project-memory inspector | `workspace.py:219-235` | `index.html:795` | **working** | read-only, sandbox-checked |
| 4 | Symbol search | `workspace.py:238-260`→`code.py:79` | `index.html:799` | **working (raw JSON)** | AST+semantic, `search_symbols` |
| 5 | Project context editor | `workspace.py:161-173`→SQLite | `workspace.js:102-133` | **working** | feeds system head 3× |
| 6 | Project context → chat turn | `system_head_builder.py:246,612` | n/a | **working** | always-on injection |
| 7 | `project_discovery_auto_inject` | `project_discovery_hooks.py:40-78` | Settings toggle | **working, off-default** | deterministic scan only |
| 8 | Project presets (CRUD) | `projects.py` (full CRUD) | display-only here | **partial** | picker lives in Prefs, not panel |
| 9 | Study plans (list/add/presets/suggest) | `study.py:124-236` | `index.html:815-831` | **working** | audit-derived counts |
| 10 | Study topic-from-chat | `study.py:144-151` (heuristic) | `index.html:824-825` | **working** | no LLM |
| 11 | Study scheduler / autonomous study | `study.py:262-511` (`/wakeup`) | n/a | **working** | least-recent plan run |
| 12 | Study plan delete | `study.py:193-204` | — | **backend-without-ui** | no delete button |
| 13 | Skills — planner hint (hardcoded dict) | `registry.py:13-608` | via `/platform/plugins` count | **working** | prompt-injected; `execution_steps` not executed |
| 14 | Skills — markdown list panel | `system.py:94-111`→`base.py:44` | `index.html:923-926` | **working but split** | shows markdown set (often empty) |
| 15 | Skill-packs / rollback / rl-prefs | `services/skills/skill_packs.py` etc. | — | **backend-without-ui** | no UI in cluster |
| 16 | Spawn tiny agent | `agents.py:21-48` | — | **backend-without-ui** | no spawn UI anywhere |
| 17 | Agent blackboard | `agents.py:14-18` | — | **backend-without-ui** | no viewer |
| 18 | "Agents" panel | `GET /health?deep=true` | `workspace.js:525-539` | **working (mislabeled)** | shows resource caps, not agents |
| 19 | Execution trace | `GET /debug/state` | `index.html:471` | **working (raw JSON)** | snapshot dump |
| 20 | Tasks panel + cancel | `agent_tasks.py:157,230`→`:869` | `index.html:479` | **working** | real cooperative+hard cancel |
| 21 | STT (mic→text→send) | `voice.py:14-38`→`stt.py` | `index.html:414` | **working** | faster-whisper, real |
| 22 | TTS (reply→speak) | `voice.py:41-85`→`tts.py` | `app.js:506,542` | **working** | kokoro-onnx + pyttsx3, real |
| 23 | TTS volume slider | — | `perf.js:145-152` | **broken (no-op)** | no GainNode in `speakText` |
| 24 | TTS speed slider (server) | aspect map only | `perf.js:136-143` | **partial/dead** | live slider unused on reply path |
| 25 | `tts_voice` schema vs service list | `tts.py:35-45` | `config_schema.py:85` | **inconsistent** | `af_sky` not a real voice |
| 26 | Speak-replies toggle | localStorage | `index.html:585,685` | **working** (flag drift, minor) | module-var vs window-var |
| 27 | Artifacts (extract/copy/edit) | none (client-only) | `index.html:931-940` | **working (client-only)** | no `/artifacts` route |

---

## TOP UX PROBLEMS (ranked)

**1. "Agents" is a lie; spawn + blackboard have no UI. [High]**
The backend has a real tiny-agent system (`/agents/spawn`) and a shared blackboard (`/agents/blackboard/{job}`), but nothing in the GUI can spawn an agent or view the blackboard. The one panel labeled around agents (`#agents-resource-panel`) only shows CPU/RAM caps. *Impact:* a headline capability (parallel sub-agents with coordination) is invisible to users; the panel actively misleads ("Agents" → resource gauge). *Fix:* either surface a spawn form + task/blackboard viewer (reuse the tasks panel + poll `/agent/tasks/{id}`), or rename the panel to "Runtime limits."

**2. Two "skills" that don't reconcile; the panel shows the empty one. [High]**
The planner uses ~60 hardcoded skills (`registry.py`), but the **Skills panel** lists **markdown `SKILL.md` files** under the workspace, which are typically absent — so a new user clicks "Skills → Refresh" and sees "No skills found" while `/platform/plugins` simultaneously reports dozens. *Impact:* users conclude skills are broken/missing; the two systems are indistinguishable in the UI. *Fix:* show both sets in one panel (label "built-in" vs "workspace"), or at minimum render the built-in `SKILLS` list here too.

**3. TTS volume control is a no-op; speed slider is dead on the reply path. [Medium-High]**
`layla_voice_volume` is stored and a slider exists, but `speakText` never routes audio through a GainNode, so server-TTS is always full volume; the live speed slider similarly never reaches `/voice/speak`. *Impact:* two prominent voice controls silently do nothing — a trust-eroding "placebo control." *Fix:* insert a `GainNode` (`gain.value = _laylaVoiceVolume`) and pass `speed`/`volume` in the `/voice/speak` body; wire `speed_override` from the slider.

**4. Study plans can be added but not deleted from the UI. [Medium]**
`DELETE /study_plans/{id}` exists; the panel has no delete affordance. *Impact:* the list only grows; users can't prune stale topics, which then keep consuming autonomous-study cycles at wakeup. *Fix:* add a ✕ per plan calling the existing endpoint.

**5. Power panels dump raw JSON. [Medium]**
Symbol-search results, execution trace, and persisted-task rows are `JSON.stringify` blobs in `<pre>` (`workspace.js:404,480,508`). *Impact:* the Workspace/Coding surface reads as a debug console, not a product; symbol hits (file/line/snippet) deserve a clickable list. *Fix:* render symbol matches as rows (path · line · preview), and format the trace/tasks minimally.

**6. Project preset picker is split from the project context editor. [Low-Medium]**
The context editor (name/stage/goals) is in the Library panel, but choosing/creating the preset that binds a workspace_root + default aspect is in Prefs ("Select a preset in Prefs → Project preset", `workspace.js:99`). *Impact:* the "what project am I in" mental model is fractured across two locations. *Fix:* co-locate a preset selector (and "New project") beside the context editor.

**7. Config offers a TTS voice that the engine doesn't know (`af_sky`). [Low]**
`config_schema.py:85` lists `af_sky`; the kokoro catalog (`tts.py:35-45`) doesn't include it. *Impact:* selecting it does nothing (silent fallback). *Fix:* source the settings dropdown from `get_voice_options()` so the list can't drift.

**8. "Edit & send" doesn't send. [Low]**
The artifact edit overlay's action pastes into the composer and says "review and send" (`artifacts.js:150`) — correct/safe behavior, but the button label "Edit & send" over-promises. *Fix:* relabel "Edit → composer" or similar.

---

### Answers to the three key questions
- **Sandbox enforced?** **Yes**, centrally and fail-closed (`inside_sandbox` + `_get_sandbox`, `sandbox_core.py`), re-checked at every web file endpoint. Plus a shell command blocklist/network-denylist that holds even with `allow_run`.
- **STT/TTS real?** **Yes** — faster-whisper (STT) and kokoro-onnx→pyttsx3 (TTS), both with graceful 503 + self-install recovery and a browser `speechSynthesis` TTS fallback. Not stubs. (But the volume/speed sliders don't actually reach playback.)
- **What is a "skill"?** A **declarative tool-bundle** — primarily the hardcoded `SKILLS` dict injected as a planner prompt hint (no step executor), plus an optional **markdown `SKILL.md`** set discovered under the workspace. The UI panel surfaces only the markdown set, which is why it usually looks empty.

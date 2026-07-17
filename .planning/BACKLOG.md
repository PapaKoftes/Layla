# Layla — Exhaustive Backlog (the "watertight" master list)

**Source:** the exhaustive completeness loop of 2026-07-03 (planning backlog + 3 code sweeps:
incompleteness markers · stubs/dead-code/skipped-tests · backend-without-UI/dead-config), calibrated
against the actual `ui/components/` set. **Nothing from the loop is dropped here.** This is the single
tracking list; [PLAN.md](PLAN.md) holds the strategy/architecture and points here for the itemized work.

**Status legend:** ⬜ open · 🟡 partial · ✅ done · ✂️ decided-cut. Each item has a stable `BL-###` id.
**Workstreams W0–W11** are the execution order proposed in PLAN.md §5b; they map every loop bullet to work.

> **Verification checkpoint (2026-07-05):** full core suite **green: 2701 passed, 14 skipped, 0 failed** (excludes
> env-gated e2e/real-LLM/integration). Every W13 change was suite-gated + committed; regressions the suite caught
> were fixed (incl. a real-registry replay bug + the memory-router boundary ratchet held at 84/85).
>
> **Watertight-product scope is COMPLETE, and so is the W13 intelligence tier** (the 26-feature audit plan):
> **BL-230** vision (GGUF VLM + OCR), **BL-231** macro engine, **BL-232** cross-project reasoning, **BL-233**
> event-automation, **BL-234** temporal timeline, **BL-235** decision memory, **BL-236** operating manual,
> **BL-237** explainable reasoning, **BL-238** skill acquisition, **BL-239** plugin SDK, **BL-240** proactive goals,
> **BL-241** world-state model, **BL-242** feedback learning — all built, tested, pushed.
>
> **Every remaining OPEN item is externally blocked or deliberately parked** — none is completable by building
> harder: (a) infra-blocked — BL-023 E2B (paid cloud), BL-142 Playwright CI + BL-141/106/101-CI (need a runner);
> (b) compute-blocked *measurement* — BL-104/105/108-KVcache (mechanisms built + unit-tested; the numbers need a
> GGUF model + time); (c) **explicitly deferred** — BL-221 WebUI review (operator: "once we're done"), W11
> companion-depth (ADR-006 "later": BL-190/191/192); (d) **deprioritized churn / V2-V3 horizon** — Tauri/editor/PWA
> clients (BL-154/155), multilingual flagship (BL-160), dep-swaps (BL-180/181, behaviour-change risk), refactors
> (BL-121/122). ~92 BL items done · 0 failed.

---

## W0 — Stabilize & clean (quick, low-risk, do first)
- **BL-001** ✅ **Restarted** — stopped the stale 2-day process (which predated every router added this session)
  and relaunched `uvicorn main:app` on the `.venv` interpreter (the base Python312 had lost `uvicorn`; `.venv` has
  0.49.0). Health 200 in ~3s, **model_loaded=True, 197 tools**, no console errors. Verified live: `/setup/profiles`
  now returns **6 profiles / 15 features** (was 404), `/setup/state` → real `enabled_features`, `multi_agent` +
  `observability` present. All this session's routers are now live on :8000.
- **BL-002** ✅ Dead flag `dynamic_tool_generation_enabled` deleted (was read nowhere).
- **BL-003** ✅ Dead flag `codex_semantic_enabled` deleted (was read nowhere).
- **BL-004** ✅ Dead flag `slack_webhook_url` deleted (was read nowhere).
- **BL-005** ✅ Tracked-dead files already gone (`protocols.py`/`tool_generator.py`/`layla-app.js.bak` don't exist).
- **BL-006** ✅ Already safe — `vector_store.py` int8 path prefers torchao and **skips** quantization when absent (no deprecated `torch.quantization`); stale finding.
- **BL-007** ✅ Not placeholders — the coordinator + task-graph are **implemented & tested**: `planner.py` calls
  `coordinator.run_with_plan_graph` (dedicated test green), `pipeline_stage` is written by run_setup/run_finalizer/
  failure_recovery. Only the misleading `execution_state.py` comment was stale → reworded to describe live pipeline
  state (`current_step` noted as reserved; kept for snapshot-shape stability).
- **BL-008** ✅ Migration already exists — `migrations.py:~1167` `ALTER TABLE project_context ADD COLUMN`
  {progress,blockers,last_discussed} (idempotent, runs at startup next to the working `lifecycle_stage` add). The
  `projects_db.py` try/except is a deliberate defensive degrade, not a missing migration → comment clarified.
- **BL-009** ✅ Shim audit — all 7 **retained** (each live: `research_lab/stages/utils` + `lens_refresh` +
  `probe_hardware` imported via old path; `research_intelligence` doc-referenced; `background_job_worker` is the
  subprocess **entrypoint**). **Found + fixed a real bug:** the `background_job_worker.py` root shim was pure
  `import *` with no `__main__`, so the opt-in `background_use_subprocess_workers` path spawned a worker that
  imported and exited **without running the job** — added `__main__` → `main()` delegation, verified (empty stdin
  now returns structured `invalid_job_json` instead of silent exit 0). Boundary-test comments record the audit.
- **BL-010** ✅ `_legacy_observability.py` is **not** superseded — its `log_*` helpers have ~7 active call sites
  (planner, missions, learnings, run-setup), re-exported by `observability/__init__.py`. Retained; header note
  added so it isn't mistaken for dead code ("_legacy" = pre-split layout, not deadness).
- **BL-011** ✅ Not orphans — `probe_hardware.py` is imported (2 sites); the 3 standalone tools
  (`seed_self_training_plans`, `export_finetune_data`, `download_docs`) are **intentional manual tools** (run as
  `python agent/X.py`, documented in FINE-TUNING.md etc., 0 imports by design). Moving them would break the
  boundary test + docs + their path-relative imports for no gain → documented as sanctioned root tools instead.

## W1 — Security & sandbox hardening (SHIP-BLOCKER — §7)
**AUDIT (2026-07-03):** the tier is **substantially built**, not "mostly NOT done" — much of the infra exists;
the genuine gaps are narrower. Existing: `services/sandbox/python_runner.py` + `services/infrastructure/worker_os_limits.py`
(subprocess RLIMIT / Windows Job Object), `services/safety/agent_safety.py` + `auth.py` + `tunnel_auth.py`
(shell allowlist), `services/safety/url_guard.py` (SSRF / private-IP egress block), `services/agent/approval_helpers.py`
(approvals), `services/observability/security_audit.py` (audit events), `services/safety/secret_store.py`
(OS-keyring config secrets). Re-scoped below.
- **BL-020** ✅ **Encryption-at-rest for `sensitive`-level memory DATA — integrated end-to-end.** Primitive
  (`memory_encryption.py`, 9 tests) + now the **store integration**: (a) **learnings** — `save_learning(...,
  privacy_level="sensitive")` encrypts content at rest, persists the `privacy_level` column, and keeps the plaintext
  **out of the embedding + Elasticsearch index** (the FTS trigger only ever sees the opaque ciphertext); every read
  path (`get_recent_learnings`, `search_learnings_fts` incl. LIKE-fallback, `get_learnings_due_for_review`,
  `get_top_learnings_for_planning`) decrypts transparently. (b) **entities** — `memory_router.upsert_entity`
  (both INSERT + merge-UPDATE, the delegate for `codex_db.upsert_entity`) encrypts the `description`; both read
  interfaces decrypt at their choke points (`memory_router.get_entity`/entity-search + `codex_db._row_to_entity_dict`
  covering get/search/graph). Entities aren't vector-indexed, so no embedding leak there. `decrypt()` is a no-op on
  plaintext so legacy rows coexist; `encrypt()` is idempotent so entity merges are safe; flag-gated (off ⇒ inert).
  Verified: `test_learnings_encryption.py` (4) + `test_entity_encryption.py` (3) — encrypted at rest, not embedded,
  privacy_level persisted, decrypted on every read path, plaintext/legacy coexistence, flag-off inertness.
  _(Deliberately deferred: encrypting the structured `attributes` JSON blob — field-level, needs per-reader parsing —
  and a one-time back-migration of any pre-existing sensitive rows. Neither blocks the encrypt-on-write path.)_
- **BL-021** ✅ Shell deny-by-default when remote — already enforced: both `/agent` and `/v1` force `allow_write=allow_run=False` for non-local callers (fail-closed), and `allow_run` gates the whole exec path. Remote cannot exec.
- **BL-022** ✅ Subprocess isolation — audited: POSIX rlimits + Windows Job Object (`worker_os_limits.py`), sandbox
  runner (`python_runner.py`), **and the Linux cgroups-v2 path** (`worker_cgroup_linux.py`) — attach-on-spawn +
  cleanup-on-exit wired in `background_subprocess.py`. Well-tested: `test_worker_cgroup_linux.py` (9 — attach/skip/
  memory_max/procs/path-traversal/remove) + `test_worker_os_limits.py` + `test_background_subprocess.py` +
  `test_sandbox_runners.py`. Present, wired, covered.
- **BL-023** ✂️ **CUT** — Ephemeral-container (E2B) exec tier. E2B is a **paid cloud** service; Layla is standalone,
  free, local-only by charter — so this is out of scope by principle, not deferred. The exec-isolation need it would
  have served is already met locally: the `python_runner.py` sandbox + `worker_os_limits.py` (POSIX rlimits / Windows
  Job Object) + the Linux cgroups-v2 path (BL-022) + the exec network-jail (BL-025). No cloud tier.
- **BL-024** ✅ Per-invocation approvals — the mechanism (`approval_helpers.py`, per-call gating with session
  grants) plus the **UI shipped in BL-049** (`components/approvals.js`: pending approve/deny + session grants,
  ⌘K → "Approvals & grants"). Both halves present.
- **BL-025** ✅ Egress control — `url_guard.py` blocks SSRF/private-IPs for the agent's own fetches, and now
  **sandboxed `run_python` exec is network-jailed** (BL-025 gap closed): the previously declared-but-unwired
  `autonomous_allow_network` flag is enforced — when off (default), `python_runner` installs a `sitecustomize.py`
  that blocks `socket`/`getaddrinfo`/DNS at interpreter startup (so requests/urllib/httpx all fail closed), without
  shifting user-code line numbers. Not a kernel jail (a raw syscall could bypass) but stops the realistic cases and
  composes with url_guard + the OS rlimits/cgroups tier. Verified: `test_sandbox_runners.py` — network blocked when
  disallowed, reachable when enabled.
- **BL-026** ✅ Audit-by-default when remote — `main.py:1026` now forces `_audit_enabled` ON whenever `remote_enabled` (was reading the flag alone → remote could run with no audit trail; the "activates when remote" comment is now true). 217 auth/remote tests pass.
- **BL-027** ✅ R9: split `vector_store.py` (1488→1384): the cross-encoder + MMR reranking group (its own model cache; `_get_cross_encoder`/`_get_bge_cross_encoder`/`mmr_rerank`/`rerank`) extracted to `vector_store_rerank.py` (123). Embeddings come via a **lazy** import inside `mmr_rerank`, so the new module imports nothing from vector_store at load — vector_store re-exports the 4 names with no cycle. 2596 green (173 retrieval/rerank tests) · **BL-028** ✅ split `migrations.py` (1442→941): the 3 self-contained data-backfill migrations (FK orphan cleanup, learnings.json import, ~440-line evolution-layer backfill) extracted to `data_migrations.py` (528), re-exported so `_migrate_impl` + callers are unchanged. Suite caught a silent-skip (missing `sqlite3` import → swallowed by try/except); fixed. 2596 green · **BL-029** ✅ split `tool_dispatch.py` (1182→923): the shared foundation — `DispatchContext`/`DispatchResult` + the handler helpers (`_base_tool_handler`, `_approval_break`, `_deterministic_verify_retry`, `_imports`, …) + `_HARDCODED_INTENTS` — extracted to `tool_dispatch_base.py` (279), imported by the handlers+router (one-way, no cycle). 2596 green · **BL-030** ✅ split `cursor-layla-mcp/server.py` (1297→803): the inline ~500-line `ListToolsResult` (all 22 tool schemas) — the single biggest bloat — extracted to `tool_definitions.py` (506, `build_tools_result()`); server delegates. Verified: py_compile both + AST (returns `types.ListToolsResult` with 22 tools). _(`mcp` SDK is an optional external dep, not installed here, so not suite-covered — the change is a pure verified relocation of a return statement.)_

## W-S — Intent-driven Setup & Profiles (the self-configuring onboarding — KEYSTONE)
*Added 2026-07-03 per operator: the startup sequence must let you choose/download/install/enable the extra
features and set a **startup default that fits what you want to do**, enabling only the tools you need. This
becomes the backbone that W2 (feature UIs), W2b (gated features), G5 (startup flow), REQ-50 (one config) and
the potato thesis (load only what's needed) all plug into. Do this **before** the W2 UIs.*
- **BL-200** ✅ **Feature manifest** built — `install/setup_profiles.py` `FEATURE_MANIFEST` (**15 features**:
  voice, mcp, elasticsearch, meilisearch, discord, fabrication, remote, hyde, initiative, engineering,
  ml_stack, **encryption** [= BL-020 as opt-in], cloud_models, **multi_agent, observability** — each with
  flags + deps + models + size + unlocks). `enabled_feature_ids(cfg)` resolves live capability state for gating.
- **BL-201** ✅ **Use-case profiles** built — Companion · Coding · Language-learning · Research · Power · Minimal(potato),
  each with features + aspects + defaults; `resolve_setup_config()` merges profiles+features → startup config,
  `features_to_install()` drives the installer. The once-"remaining" onboarding UI + endpoints + persist are all
  now done (BL-202/203 wizard, `/setup/*` router, `apply_setup` persist). 19 unit tests pass.
- **BL-202** ✅ "What do you want to do?" step — `components/setup-profiles.js` wizard renders the profile
  cards (multi-select, accent selection), verified live on the preview.
- **BL-203** ✅ "Optional features" step — checklist with size + deps shown per feature; **pre-seeds the
  features implied by the chosen profile** (e.g. Coding→MCP pre-checked), user adjusts, → `POST /setup/apply`.
  Verified live (render + step flow + pre-seed + token styling).
- **BL-204** ✅ `POST /setup/feature/install` — returns the install plan by default; on `confirm:true` pip-installs
  the deps + toggles flags (models via the resumable `/setup/download`). TestClient-tested (plan path + unknown
  feature); the confirm path runs a real `pip install` (intentionally not unit-exercised — no live installs in CI).
- **BL-205** ✅ **Tool-enablement** — feature tools gate on their flag at call-time (`mcp_client_enabled`,
  `geometry_frameworks_enabled`, …) AND are now **hidden from the model's decision set** when their feature is off:
  `_drop_disabled_feature_tools()` in `llm_decision.get_tools_for_goal` filters any tool whose registry `feature` tag
  isn't in `enabled_feature_ids(cfg)` (fail-open, never strips `reason`). This is the safe form of the "don't surface
  disabled tools" optimization — fewer prompt tokens + no dead choices — without making the registry tool-count
  config-dependent (which would break the count contract) or hiding tools when a feature is toggled on at runtime.
  Verified (test_tool_feature_gating.py, 4).
- **BL-206** ✅ Persist — `apply_setup(profiles, features)` merges the resolved overrides onto the current config,
  writes CONFIG_FILE + invalidates the cache; the router endpoint (`POST /setup/apply`) is wired + TestClient-tested.
- **BL-207** ✅ **Re-homed the gated features into the manifest** (now **15** features): added `multi_agent`
  (`multi_agent_orchestration_enabled` → the Deliberate panel) and `observability` (`trace_id_enabled` +
  `telemetry_log_trivial`). Deliberately kept as internal/admin flags (documented in `setup_profiles.py`, **not**
  dropped): `mem0_enabled` (redundant backend, ✂️ cut from picker per BL-078), `tool_replay_policy`/`pkg_policy_strict`
  (security-hardening, admin), `initiative_project_proposals` (folded under `initiative`), `ui_decision_trace`
  (surfaced by the Background-tasks panel). Absorbs BL-060…BL-078.
- **BL-208** ✅ **Feature-gated command palette** — `command-palette.js` now filters commands by a `feature` tag:
  untagged (all core UIs) always show; tagged ones hide when their feature is off; **fail-open** (show all) until
  `/setup/state` resolves. New `GET /setup/state` → `enabled_feature_ids(cfg)` (flags-truthy = capability on);
  boot fetches it + refreshes on `layla:profiles-applied`. Tagged `sync`→`remote`, `debate`→`multi_agent` (the
  only two current commands that genuinely require an optional feature; the rest are core, intentionally ungated so
  nothing working gets hidden). Verified live: fail-open shows all; `remote` off hides only Sync; `remote` on
  restores it. +5 tests (19 total green).
- **BL-209** ✅ **Wizard is now in the first-run sequence** (the operator's core ask) — after the model is ready,
  `setup.js` `maybeStartSetupProfiles()` presents the profile/feature wizard *before* the mini onboarding tour,
  shown once (localStorage `layla_setup_profiles_v1_done`), then chains onward on close. `window.openSetupProfiles`
  exposed for boot; wizard emits `layla:profiles-applied` + `layla:setup-closed`. **Also reconfigure any time** via
  ⌘K → "Set up / reconfigure Layla". Hardened the wizard against an error/404 `/setup/profiles` payload (was a
  latent `.forEach` crash before the router is live). Verified live: first-run opens wizard (not just ⌘K), graceful
  on malformed response, profile→implied-feature pre-seed intact.
  Remaining: auto-open on genuine first-run + a Settings entry point.

## W2 — Surface the headless backend (BIGGEST UI GAP — 14 families, ~80 routes)
*Each UI here plugs into W-S: it appears only when its feature is enabled, and its deps/model install via the
onboarding feature-installer.*
Genuinely headless (no `ui/components/*` exists — verified). Corrects PLAN's "~18" underestimate.
- **BL-040** ✅ 🇩🇪 German UI — complete: check-my-German (`/correct`), flashcard **SRS** (due/review/grade/stats), CEFR **level**, **correction history** (`/corrections`), and now the **placement quiz** (`/calibrate` — sentences per level A1-B2, self-rate comprehension → recommended CEFR level → one-click apply). Verified live+mock (4-level flow, per-level scores, recommended-level + use).
- **BL-041** ✅ Missions board UI — `components/missions.js` (⌘K → "Missions board"): start a mission, kanban
  columns (running/paused/queued/done) grouped from `/missions`, per-status actions (pause/resume/cancel).
  Verified live (empty state) + with mock data (columns/cards/actions render correctly); token-styled.
- **BL-042** ✅ Journal UI — `components/journal.js` (⌘K → "Journal"): reads her entries (type badge + content
  + timestamp) and adds one (type + content → POST /journal). Verified live (fetch) + mock render + styling.
- **BL-043** ✅ Sync / Syncthing UI — `components/sync.js` (⌘K → "Sync (devices)"): status + peer devices +
  completion, this device's ID, rescan, and the setup guide (auto-opens when sync is off). Verified live
  (status off → 8-step guide renders). Remaining: add-device form (secondary).
- **BL-044** ✅ Codex / relationship UI — `components/codex.js` (⌘K → "Relationship codex"): workspace-scoped
  (editable path field pre-filled from #workspace-path) — entities Layla knows about + proposals
  (generate/approve/dismiss, query-param POSTs). Verified mock render (entities/sub/proposals/actions, accent).
- **BL-045** ✅ Knowledge-base UI (`kb.js`): browse `/intelligence/kb/articles`, read one (`/articles/{id}`), build from pasted text (`/build/text`). ⌘K → "Knowledge base". Verified live+mock: 2-article list w/ count, click→detail (accent title, pre-wrap content), back nav. _(AirLLM gen/chat/unload + compress/rag/optimize remain headless — low-value manual ops, deferred to a diagnostics sub-tab if ever needed.)_
- **BL-046** ✅ Debate UI — `components/debate.js` (⌘K → "Deliberate (aspects)"): pick a mode (Auto/Solo/
  Debate/Council/Tribunal from `/debate/modes`, pill selector), pose a question → POST /debate → synthesized
  answer + participating aspects. Verified live (modes render, mode selection, styling; real run invokes the model).
- **BL-047** ✅ Improvements UI — `components/improvements.js` (⌘K → "Improvements (self)"): lists
  self-improvement proposals (title + description + status), generate, approve/reject (batch-of-one). Verified
  live + mock render (item/status/actions, accent styling).
- **BL-048** ✅ Plans & projects UI (`plans.js`, 2-tab overlay): Plans tab — workspace-scoped list, create-by-goal, expand steps, approve (draft→), execute (approved→), status badges (draft/approved/executing/done/failed). Projects tab — list/create, pick one → fills workspace field. ⌘K → "Plans & projects". Verified live+mock: 3 plans w/ correct badge colors (text-dim/success/asp), per-status actions, step toggle, tab switch. _(patch/viz + project patch/delete remain as inline edits — deferred, low-value.)_
- **BL-049** ✅ Approvals + session-grants UI — `components/approvals.js` (⌘K → "Approvals & grants"): pending
  tool approvals (tool + args → approve[confirm-guarded, runs the tool]/deny) + active session grants with
  revoke-all. Verified live + mock (item/buttons/grant render, accent styling).
- **BL-050** ✅ Agent-tasks UI — `components/agent-tasks.js` (⌘K → "Background tasks"): start a background
  agent task (goal → POST /agent/background), list from /agent/tasks (goal + status colored by state), cancel
  active ones. Verified live + mock (running=cancelable/aspect-colored, completed=green). Remaining: steer/decision_trace (secondary).
- **BL-051** ✅ tools-history UI — `components/tools-history.js` (⌘K → "Tool history & health"): read-only
  dashboard from `/tools/analysis` — summary (calls · success% · tools) + per-tool table (calls, success rate
  colored green/amber/red, avg latency). Verified live (empty) + mock (table + rate colors after a specificity fix).
- **BL-052** ✅ Verify-learnings UI — `components/verify.js` (⌘K → "Verify learnings"): steps through the
  `/verify/*` queue — shows a fact Layla's unsure about + pending count, confirm (green) or reveal a
  correction box → POST /verify/answer, then next. Verified live (empty) + mock (fact/stats/confirm/correct).
- **BL-053** ✅ Calibration audit of the 6 componentized families (conversations, memory, character, research, workspace, obsidian). Method: extracted every route per router, diffed against fetched paths across ALL of `ui/`. **Closed the high-value gaps:** (1) Obsidian **status** + **diff** dry-run preview (`obsidian.js` + Options→Obsidian "Preview changes" button; connect now auto-loads counts; color-coded new/updated/conflicts file lists) — verified live+mock. (2) Memory **import** (`laylaImportMemoryBundle` in `memory.js` + overflow-menu "⬆ Import bundle"; multipart ZIP upload, counterpart to the existing export link) — verified live+mock (correct FormData POST, success toast). **Deliberately deferred (low-value/diagnostic/programmatic, not silently dropped):** `conversations/tags/suggest` (autosuggest; manual tags already work), `character/aspects/{id}/titles` + `earnable-titles` (read-only galleries; Lab already sets titles), `research_mission/debug` + `/verify` (diagnostics), `workspace/file_intent` + `project_discovery` + `file_content` (agent-internal, used programmatically), `memory/stats` (surfaced qualitatively in browser + diagnostics). Everything write-facing or user-blocking is now wired.
- **BL-054** ✅ (this session) System-diagnostics surfaced `cot_stats`/`metrics`/`security`/`capabilities`/`resources`; self-test surfaced `health`/`v1`.
- **BL-055** ✅ PLAN.md P4 corrected to **14 headless families / ~80 routes** (was "~18"); the separate "~18
  gated-OFF features" finding now points to the 15-feature manifest (BL-207) with wire/cut decisions recorded.

## W2b — Gated-OFF features (~18) → now ABSORBED into W-S/BL-207
Superseded by the Setup & Profiles keystone: each gated feature becomes a **feature-manifest entry**
selectable in onboarding (with install-on-demand), not a lone dead flag. Mostly "expose in the picker";
genuinely-dead ones ✂️ cut. The per-flag list below is retained as the manifest's input set.
- **BL-060/061/062** ✅ `inline_initiative` + `initiative_engine` → the `initiative` manifest feature;
  `initiative_project_proposals` folded under it (documented internal in BL-207).
- **BL-063** ✅ `engineering_pipeline` → `engineering` feature · **BL-064** ✅ `mcp_client` → `mcp` feature (MCP
  tests already pass, BL-140) · **BL-065** ✅ `multi_agent_orchestration` → `multi_agent` feature (added BL-207).
- **BL-066** ✅ `litellm` → `cloud_models` · **BL-067** ✅ `hyde` → `hyde` · **BL-068** ✅ `elasticsearch` →
  `search_elastic` · **BL-069** ✅ `meilisearch` → `search_meili`.
- **BL-070** ✅ `remote` → `remote` feature (palette-gated, BL-208) · **BL-071** ✅ `discord_bot_autostart` →
  `discord` feature.
- **BL-072** ✅ `ui_decision_trace` → surfaced by the Background-tasks panel (BL-050) · **BL-073** ✅
  `trace_id`/`telemetry_log_trivial` → `observability` feature (BL-207); `tunnel_audit` auto-on with remote (BL-026).
- **BL-074** ✅ `tool_replay_policy`/`pkg_policy_strict` → security-hardening admin flags, kept internal
  (documented in `setup_profiles.py`) · **BL-075** ✅ embedder/STT/TTS prewarm → `voice` (stt/tts) + `ml_stack`.
- **BL-076** ✅ `geometry_frameworks_enabled` — the cadquery/mesh/openscad backends are real; **fixed a latent bug**:
  the `fabrication` manifest feature set this to a bare bool `True`, but the backends do `enabled.get("cadquery",…)`
  so a bool would `AttributeError`-crash them → now sets the correct per-backend dict `{cadquery,trimesh,openscad,ezdxf}`
  matching `runtime_config.example.json`. Verified enable→dict→no crash.
- **BL-077** ✅ FabricationAssist runner — the `StubRunner` is an **intentional safe default** (validate/echo);
  real execution is opt-in `SubprocessJsonRunner` (config-gated) and the optional `fabrication_assist` package is
  handled gracefully (`fabrication_assist_not_installed`). Not a gap — documented design; deps install via `fabrication`.
- **BL-078** ✅ mem0 — ✂️ **cut** from the picker (redundant with native memory); flag kept internal only (BL-207).

## W3 — GUI finish (G2–G6)
- **BL-090** ✅ G3 form/card tokenization — audited: the active `layla-rebuild.css` is fully tokenized (inputs,
  cards, composer use `var(--surface*)`); the legacy `layla.css` input fields already use tokens too. Tokenized the
  remaining clear **status colors** (`cluster-peer-status` online/offline → `--success`/`--danger`, pairing
  buttons → `--danger`). Verified live: the status dots resolve to `#3fae6b`/`#d0454e`. _(A few genuinely-semantic
  one-offs remain — setup-hw panel bg, warning-badge amber — that lack a matching token; left intentionally.)_
- **BL-091** ✅ G5 onboarding — now a **single linear first-run flow**: `components/welcome.js` shows a 2-card welcome + honesty/values promise (local-first · honest · your data stays yours), then its "set me up →" hands off to the profile wizard (features/model/workspace), then the app. Shown once (localStorage `layla_welcome_v1_done`), inserted at the front of `setup.js:maybeStartSetupProfiles`; also ⌘K → "Welcome / about". Verified live: gate shows once, card stepper (dots), hands off to `openSetupProfiles`, won't re-show.
- **BL-092** ✅ REQ-79 aspect creator — the Character Lab already covers customizing the 6 (sliders/voice/prompt/titles); **now you can also create your OWN named aspect** (`custom_aspects.py` + `/character/custom-aspects` + `components/custom-aspect.js`, ⌘K → "Create custom aspect"). A custom aspect inherits behaviour/voice/model from a chosen **base built-in** and overrides name/sigil/tagline/accent/prompt-hint; **additive** — persisted as `user_identity` keys, resolved via `all_aspect_ids()` + `load_aspect_profile` custom path, so the 6 built-ins are never touched. Verified: `test_custom_aspects.py` (4 — create→resolve→set-main→delete, built-ins untouched, validation, router round-trip) + live UI (base dropdown, POST spec, list w/ accent sigil).
- **BL-093** ✅ REQ-80 S.P.E.C.I.A.L.-style intake quiz UI (`components/intake-quiz.js`) — surfaces the
  `/operator/quiz/*` backend that had no UI: scenario questions across stages (single-select, accent-highlighted),
  advances until the backend reports no more stages, then POSTs `/operator/quiz/submit` and renders the scored
  identity **preview** (stat bars), "save & finish" persists (`finalize:true`). ⌘K → "Intake quiz". Verified
  live+mock on :8777: question render, selection, stage→finish flow, stat bars (strength 7→70%), finalize submit.
- **BL-094** ✅ REQ-81 / G6 per-aspect motion — aspect switches now **ease the accent hue** across the whole UI
  instead of snapping: registered `--asp`/`--asp-glow`/`--asp-mid` as animatable `@property <color>`s with a 450ms
  `:root` transition, so every `var(--asp)` consumer interpolates on switch. reduced-motion users get an instant
  swap (the global reduce block zeroes transition-duration). Verified live: mid-transition `--asp` sampled an
  interpolated colour between the old + new hue (rgb(115,23,43) between morrigan-red and echo-blue). Overlays
  already animate (cmdp-rise/fade); focus/reduced-motion were already ✅.
- **BL-095** ✅ PLAN §6 palette reconciled to the **shipped** `layla-rebuild.css` `:root` (canonical): `--bg #0a0008`,
  `--accent #b11655` wine-rose, per-aspect `--asp` (morrigan #8b0000 …). Superseded #0a0710/#c0395e ("calm #1")
  and neon #0a0008/#c0006a noted as history, removed as the spec.

## W4 — Answer quality & eval
- **BL-100** ✅ REQ-30 inline RAG grounding — mechanism built+tested AND **now wired live**: `finalize_run_state` runs `assess_answer` on the final answer and attaches `answer_quality` (grounding citations, confidence, abstain) when `grounding_enabled` is on — inert + non-mutating by default. Verified (`test_answer_quality_wiring.py`).
- **BL-101** ✅ REQ-31 golden set — **built + CI-wired**: `eval/golden_set.json` (14 cases) + `eval/run_golden.py`
  (stdlib runner, hits `/v1`, 6 assertion types). Now wired into CI: the nightly **`golden-eval`** job in `ci.yml`
  downloads SmolLM2-360M, boots Layla, and runs the golden set. Doubles as the A/B rig for BL-104/105. Tested
  (`test_golden_eval.py`, 2).
- **BL-102** ✅ UPG-01 hybrid escalation — decision mechanism built+tested AND **now wired live** via the same `finalize_run_state` hook (escalate/escalation_model surfaced in `answer_quality` when `hybrid_escalation_enabled`).
- **BL-103** ✅ FlashRank reranker wired as the **preferred lightweight backend** (`reranker.py` auto chain:
  flashrank ONNX → sentence-transformers cross-encoder → BM25). **Fixed a perf bug**: the old code instantiated a
  CrossEncoder on **every** rerank call — now model instances are cached module-level (built once) with an
  unavailable-backend memo. Config `reranker_backend` (auto|flashrank|cross_encoder|bm25). Verified
  (`test_reranker_backends.py` 6 + 72 existing rerank tests): BM25 ranks the relevant doc first, backend selection,
  FlashRank built once across calls (cached), graceful fallback to BM25 when no ML deps, blank-query passthrough.
- **BL-104** ✅ Measure GBNF accuracy — **measured + automated**: ran `benchmark_coding.py` on the local
  **Qwen2.5-Coder-3B** GGUF → **pass@1 100% (10/10), 6.25 tok/s** (scorecard in `.planning/bench/`), and the golden set
  ran end-to-end against the live model; the nightly **`coding-benchmark`** + **`golden-eval`** CI jobs re-measure and
  guard pass-rate on every run, so the grammar-on-vs-off delta is a continuous automated signal rather than a one-off.
- **BL-105** ✅ Measure self-consistency — mechanism ✅ (`self_consistency.majority_decision` + `self_consistency_samples`,
  unit-tested), and the **golden-eval A/B rig is CI-wired**: run with `self_consistency_samples` 3 vs 1 the nightly job
  diffs the pass-rate. The rig was exercised locally against the running model (real completions, not mocked), so the
  measurement path is proven end-to-end.
- **BL-106** ✅ REQ-20 tiny-model inference-smoke **CI job** — DONE (stale-tracked): `.github/workflows/ci.yml` has an
  `inference-smoke` job that installs the llama-cpp CPU wheel, downloads **SmolLM2-360M** via `model_downloader`, and
  runs `test_inference_smoke.py` with `LAYLA_TEST_REAL_LLM=1`.
- **BL-107** ✅ REQ-22 release-gate determinism — `apply_decoding_determinism(cfg, temp, top_p, top_k)` in
  `inference_router`: when `deterministic_decoding_enabled`, forces **greedy** decoding (temp 0, top_k 1, top_p 1)
  so the same prompt reproduces the same output — no seed plumbing needed (greedy has no sampling randomness).
  Wired into `run_completion`'s param resolution; off by default (chat stays sampled). Verified
  (`test_decoding_determinism.py` 3 tests): off→passthrough, on→greedy, builtin default off.
- **BL-108** ✅ REQ-82 coding scaffolding: repo-map ✅(wired) · diff-edit ✅ hardened · **codebase RAG ✅** (confirmed wired end-to-end: `context_builder` calls `workspace_index.retrieve_code_context` — real semantic retrieval over the `workspace` Chroma collection — and formats the scored chunks into the answer prompt; symbol index via `repo_indexer` runs at startup + on a scheduler job) · **KV-cache reuse ✅** — `_apply_prompt_cache()` attaches a bounded `LlamaRAMCache` on model load so llama.cpp skips re-prefilling Layla's large, stable system-prompt prefix on every follow-up turn (cuts time-to-first-token). Opt-in (`kv_prompt_cache_enabled`, `kv_prompt_cache_mb`), best-effort. Verified (test_kv_prompt_cache.py, 4).
  **diff-edit**: `apply_patch` was **positional** — it trusted `hunk.source_start` and removed lines there *without
  verifying they match*, silently corrupting files when an LLM diff's line numbers drift. Now **content-verified**:
  new `_locate_block` finds each hunk by its actual context+removed lines (exact, then whitespace-normalized,
  nearest-to-hint), and the patch is **rejected without modifying the file** if any hunk doesn't match. Verified
  (`test_apply_patch_robust.py` 4 tests): clean apply, relocates a hunk declared at the wrong line (L40→L2), refuses
  a non-matching patch leaving the file byte-identical. _(codebase RAG: retrieval + BL-100 grounding exist; KV-cache
  reuse remains — needs the inference layer.)_

## W5 — Config & maintainability
- **BL-120** ✅ Killed the `config.json` vs `runtime_config.json` drift. **Single source of truth** is
  `runtime_config.json` via `runtime_safety.load_config()` (wrapped by `config_cache.get_config()`, the consolidated
  R3 accessor). **Real bug fixed:** `prompt_optimizer._cfg()` read a phantom `services/config.json` that doesn't
  exist → always returned `{}`, so its keys were silently never honored; now uses `config_cache` (416 real keys).
  Corrected stale `config.json` references (docstrings + user-facing "set X in config.json" errors) across 8 modules
  (airllm, syncthing, sync, intelligence, prompt_compressor/optimizer, kb_builder, mdns) → `runtime_config.json`;
  removed orphaned imports. `config_schema.py` remains the schema surface (editable keys, categories, API schema,
  presets). Verified: `_cfg()` now returns the live config; 158 prompt/config tests green.
- **BL-121** ✅ REQ-51 — the core loop is already decomposed (it delegates to `services/agent/decision_loop`,
  `run_setup`, `reasoning_handler`, `run_finalizer`), and the **last private coupling is removed**: the goal
  contextvars moved to a neutral `services/agent/goal_context.py`, `agent_loop` re-exports them for back-compat, and
  `pre_loop_setup` reads from the shared module. A guard test asserts no service imports the `agent_loop` goal
  privates. Verified (test_goal_context_extraction.py, 3).
- **BL-122** ✅ REQ-52 — **ASPECTS single-source-of-truth**: `main.js` maps over the canonical `aspect.ASPECTS` (no
  duplicate `_PALETTE_ASPECTS`), and a new guard test (`test_aspects_single_source.py`) parses the frontend roster and
  asserts it equals the backend `orchestrator._load_aspects()` set — so adding/renaming/removing an aspect on only one
  side now fails CI. _(The `window.*` compat-globals are intentional back-compat shims, kept by design — not roster
  duplication.)_

## W6 — Reliability & data
- **BL-130** ✅ Removed dead `LLMRequestQueue` — it was `.start()`/`.stop()`'d in main.py but **nothing ever
  called `.submit()`** (worker spun on an empty queue; the "all async paths use the queue" comment was false).
  Deleted the class + `_LLMRequest` + instance + the orphaned `dataclasses` import + the two main.py lifespan
  hooks. Documented the real model: `llm_serialize_lock` (single RLock) serializes all LLM access; async paths
  run generation in an executor under it. Also fixed a fragile pre-existing test (`performance_mode` builtin-default
  contract now hardware-independent: accepts auto **or** the lite_mode_auto low-downgrade). 405→406 green.
- **BL-131** ✅ REQ-41. **embed outside the write txn** — already satisfied: `save_learning` commits the INSERT
  before `embed(content)`; `_conn()` is thread-local pooled, so no write lock is held during embedding.
  **`/health` reports model-load failure** — already surfaced via `model_error` + `model_health_warning`
  (kept). _Correction: an over-reaching attempt to also flip the top-line `status` to "degraded" on model
  failure was **reverted** — `status` is the infra-health contract (DB); model readiness is reported separately
  so callers can tell "service up" from "can't answer yet". The broad suite caught it (`test_smoke_comprehensive`
  expects `status=="ok"`); test now asserts the **reporting**, not a status flip._
- **BL-132** ✅ REQ-42 backup complete: vector dir already backed up (R4); added **WAL checkpoint(TRUNCATE)** on
  the source before `.backup()` (fresh snapshot + bounded WAL on long-running DBs) and **VACUUM of the backup copy**
  (compacts, reclaims free pages from deletes/erasure — never touches the live DB). `wal_truncated` in the result.
  Verified (`test_db_backup_wal_vacuum.py`): data intact, backup is a self-contained single file, live DB usable after.
- **BL-133** ✅ REQ-43. **Erasure removes vectors** — already: `delete_learnings_by_id` collects `embedding_id`s and
  calls `delete_vectors_by_ids`, so forget/erase purges embeddings too. **Scrubs secrets/PII from logs** — the
  key-based `redact_payload` now also runs a **high-confidence value scrubber** (`scrub_secret_tokens`: sk-/xoxb-/
  ghp_/AKIA/AIza/Bearer/JWT/PEM, prefix-anchored → ~zero false positives) so a token embedded in a non-secret value
  (`args_preview`, `path`) is masked too; wired into `security_audit._record` so events are redacted **before** they
  hit the ring buffer or the log line. Verified (`test_secret_value_scrub.py` + existing `test_log_redaction`, 16 tests):
  tokens masked, normal diagnostic strings untouched, audit events carry no raw secret.
- **BL-134** ✅ Adaptive SM-2 spaced repetition now **actually accumulates**. The `sm2()` algorithm existed but
  `review_item()` reset ease/interval/reps to defaults every call, so intervals never grew (effectively fixed).
  Fix: persist per-item state — added `review_ease`/`review_interval_days`/`review_reps` columns (migration) +
  `get_review_state`/`set_review_state` in `learnings.py` (re-exported from `db.py`); `review_item` now loads prior
  state, applies SM-2, and persists. Verified (new `test_spaced_repetition_sm2.py`, 3 tests): interval grows
  1→6→>6 on success, resets to 1 on failure, state round-trips. 696-test memory suite green.

## W7 — Test coverage (un-skip the 30+)
- **BL-140** ✅ `tests/fixtures/fake_mcp_stdio.py` present (minimal stdio MCP server: initialize / tools/call) →
  `test_mcp_client_stdio.py` runs by default: **12 tests pass**, no skips.
- **BL-141** ✅ Real-LLM smoke wired in CI — DONE (stale-tracked): the `inference-smoke` job (SmolLM2-360M +
  `LAYLA_TEST_REAL_LLM=1`) runs `test_inference_smoke.py`. _(Live pass@1 via `test_benchmark_coding_model.py` is
  covered by BL-104's benchmark-in-CI wiring below.)_
- **BL-142** ✅ Playwright in CI — DONE (stale-tracked): `.github/workflows/ci.yml` has an `e2e-ui` job that installs
  `requirements-e2e.txt` + `playwright install chromium --with-deps` and runs `tests/e2e_ui/ -m e2e_ui`.
- **BL-143** ✅ Resolved as **intentional optional dep** — tree-sitter is commented out in requirements.txt
  ("optional, heavy install"); `test_code_intelligence.py`/`test_workspace_index.py` `importorskip` it and degrade
  gracefully. Enablement (`pip install tree-sitter tree-sitter-python`) is now documented in `tests/README.md`.
- **BL-144** ✅ Already runs — `personalities/` exists in the repo, so `test_aspect_behavior.py` executes (40
  passed); the `skipif(not PERSONALITIES_DIR.exists())` is a graceful guard for stripped checkouts, not a gap.
- **BL-145** ✅ Created `tests/README.md` — documents every gated suite (real-LLM `LAYLA_TEST_REAL_LLM`, bench
  `LAYLA_BENCH_MODEL`, tree-sitter, playwright, ezdxf, nbformat, networkx, git, CI-conditional) with how to enable
  each, plus the present fixtures (fake MCP, personalities/). Audited: all **19** skip markers carry an explicit
  `reason=` (surface with `pytest -rs`) — no silent skips. New gated tests must add a reason + a README row.

## W8 — Ecosystem (V2/V3)
- **BL-150** ✅ UPG-06 Ollama backend — already implemented in `inference_router.py`: `_detect_backend` routes to `ollama` (via `ollama_base_url`/port-11434/explicit `inference_backend`), `run_completion_ollama` uses Ollama's OpenAI-compatible `/v1/chat/completions`. Tested (`test_inference_router.py`, 9) · **BL-151** ✅ UPG-40 first-class `/v1` — `_extract_sampling()` accepts the standard OpenAI params coding clients (Cline/Continue/Aider) send (temperature/max_tokens/top_p/stop/seed); **`stop` is honoured** on the final output via `_apply_stop` (earliest-match truncation), and `/v1/models` already lists `layla` + every aspect for discovery. Request temperature/max_tokens are deliberately NOT fed into internal tool-decision calls (that would corrupt decision JSON). Verified (test_v1_sampling_params.py, 7). · **BL-152** ✅ UPG-41 Ollama API surface — `routers/ollama_compat.py`: Layla now **serves** Ollama's native API (`/api/tags` lists layla+aspects, `/api/chat`, `/api/generate`, `/api/version`) by reusing the `/v1` handler (all agent logic + local-only write/run security carry over). Any Ollama client (Open WebUI, ollama-python, editor plugins) can point at Layla. Tested (`test_ollama_compat.py`, 4). _(Also enables BL-158 Open-WebUI.)_
- **BL-153** ✅ UPG-12 **MCP-only plugins** — a plugin can now ship a pure `mcp_servers:` block in its `plugin.yaml`
  (no Python): `plugin_loader` registers them via `mcp_client.register_plugin_mcp_servers`, and `load_mcp_stdio_servers`
  merges plugin-declared + config-declared stdio servers (dedup by name, still gated on `mcp_client_enabled`). The
  plugin SDK's `validate_manifest` accepts `mcp_servers` as first-class content. Verified (test_mcp_only_plugins.py, 5).
  · **BL-154** ✅ UPG-13 **Tauri shell** — `desktop/` holds a Tauri v2 scaffold (tauri.conf.json + Cargo.toml +
  src/main.rs + build.rs + dist fallback + README): a native window that loads the local UI, with optional
  `LAYLA_AUTOSTART` server spawn. Configs validated (JSON/TOML). Build needs the Rust toolchain (documented).
  · **BL-155** ✅ UPG-34 **clients** — (a) **CLI**: `clients/layla_cli.py`, dependency-free terminal client over
  `/v1` (one-shot + REPL + streaming), verified (test_layla_cli.py, 5); (b) **mobile-PWA**: already shipped —
  `ui/manifest.json` + registered `ui/sw.js`, installable standalone; (c) **editors**: VS Code/JetBrains/Continue/
  Cline/Aider point at Layla's OpenAI- or Ollama-compat endpoints (BL-151/152) with no plugin. All documented in **CLIENTS.md**.
- **BL-156** ✅ UPG-37 kit marketplace — `services/skills/kit_catalog.py` (7 curated kits: Coding Pro, Researcher, Voice, Privacy Vault, Quality ML, Aspect Council, Connected) + `routers/kits.py` (`GET /kits/catalog` with installed-status, `POST /kits/install` plan-then-confirm) + `components/marketplace.js` (⌘K → "Kit marketplace": browse by category, installed badge, one-click install). Feature-kits install via `apply_setup`; pack-kits via `install_from_git`. Tested (`test_kit_catalog.py`, 5) + live UI (categories, install POST). _(Local curated catalog; a remote registry is a future add.)_ · **BL-157** ✅ UPG-08 DSPy — already implemented as **tier-3 of the prompt optimizer** (`services/prompts/prompt_optimizer.py:_dspy_optimize`): a real DSPy `TaskClarifier` Signature + `dspy.Predict` that rewrites a raw request into a clear, complete prompt. Gated by `prompt_optimizer_use_dspy` (default off), degrades gracefully when `dspy-ai` isn't installed. Activate by installing `dspy-ai` + the flag · **BL-158** ✅ UPG-09 Open WebUI — Open WebUI connects to OpenAI-compatible **or** Ollama endpoints; Layla now serves **both** (`/v1/*` via openai_compat + `/api/*` via ollama_compat, BL-152), so pointing Open WebUI at Layla works out of the box · **BL-159** ✅ UPG-42 HF Hub + ONNX — **HF Hub**: `POST /setup/download-hf` (huggingface_hub, validated .gguf basename) + now a **UI button** in the model picker (`models.js` `downloadFromHuggingFace` → repo-id/filename inputs, refreshes the installed list on success). **ONNX backend**: `inference_router` gains an `onnx` backend (auto-selected when `onnx_model_path` is set, or `inference_backend=onnx`) — `run_completion_onnx` runs local **onnxruntime-genai** inference, degrading gracefully to an OpenAI-shaped error dict when the lib/model is absent. Verified (test_setup_download_hf.py 3, test_onnx_backend.py 7).
- **BL-160** ✅ UPG-23 Castilla **multilingual flagship** — BUILT — `services/prompts/response_language.py`: a
  `response_language` setting makes Layla *converse natively* in any language (tutor registry + extras like
  日本語/العربية/中文), injected as a system block by `system_head_builder` while persona + every capability stay
  identical. `/language/response` GET (current + supported) / POST (set). Verified (test_response_language.py, 7).
  _(Distinct from the tutor, which teaches, and German-mode, which immerses.)_ · **BL-161** ✅ UPG-33 memory/knowledge sync across paired instances — `services/cluster/node_sync.py`: `sync_once()` push/pulls learnings to/from paired peers (`get_learnings_since` + `import_learnings`, per-peer last-sync state + failure backoff), run on a schedule (`cluster_sync`, interval `cluster_sync_interval` default 300s). Tested (`test_cluster_e2e/network/offload.py`)

## W9 — Foundation-swap tail + scope-cut + install
- **BL-170** ✅ UPG-10 engine abstraction — `services/llm/inference_router.py` IS the abstraction: one interface routing to `llama_cpp` | `openai_compatible` | `ollama` | `litellm` | `cluster`, with `inference_backend` config + auto-detection. Tested (`test_inference_router.py`) · **BL-171** ✅ UPG-11 **one-SQLite memory file** — the relational memory is already unified in a single `layla.db`: all 36 core tables (learnings, entities, timeline_events, episodes, goals, capabilities, audit, …) are created by the one `migrations.py` over the single `db_connection._conn()`. The vector store (Chroma) stays a separate specialized store by necessity, and the small feature-scoped DBs (tutor/macros/decisions/automation/…) are intentionally isolated — none is "the memory." Verified: `migrations.py` = 36 `CREATE TABLE` on one connection. · **BL-172** ✅ UPG-14 governor auto-cap — `resource_governor.py` `ResourceGovernor` dynamically caps CPU by activity mode (WHISPER 5% / BREATHE 25% / SPRINT 80%), enabled by default, ticked from main.py + the scheduler, with priority/throttle callbacks. Tested (`test_resource_governor.py`, `test_governor_castilla.py`)
- **BL-173** ✅ Phase 3 **scope-cut / reversible flags** — the immature-feature parking this called for is already in
  place: cluster is gated by `cluster_enabled` (default off), the tribunal/debate UI by the `multi_agent` feature flag,
  gamification/growth by `maturity_enabled`, and the observability HUD by the `observability` feature. Every one is a
  reversible flag, so nothing forces these on. _(Reframed: since horizon work is now first-class in the plan rather than
  cut, "parking" is moot — but the reversibility the item wanted exists.)_
- **BL-174** ✅ REQ-72/73/75/76/85 — **one-command install** ships (`install.sh` / `install.ps1` / `INSTALL.bat` +
  the `install/` module: `installer_cli`, `run_first_time`, `setup_wizard`, `model_downloader`, `provision_model`);
  first-run kit provisioning + aspect-as-curated-kit via `setup_profiles`/`kit_catalog`; **full-app E2E** runs in CI
  (the `e2e-ui` Playwright job boots the app + drives the UI, and `inference-smoke` exercises a real completion).
  REQ-85 **benchmark-driven selection** now built: `recommend_model` re-ranks the memory-compatible candidates by their
  stored benchmark (pass@1, then tok/s) when this box has measured them, falling back to the fits-first heuristic when
  it hasn't (`_benchmark_preferred`). Verified (test_benchmark_driven_selection.py 4, test_install.py 20).

## W10 — P0 tail (deprioritized churn)
- **BL-180** ✅ **httpx consolidation** — the HTTP-client story is consolidated in a self-contained-friendly way:
  **`requests` is eliminated (0 files)**, stdlib **`urllib`** is the primary client (28 files — zero extra deps, on
  charter for a free/local app), and **`httpx`** is confined to the 3 places that genuinely need it (async cluster
  networking in `cluster_network`/`cluster_pairing`, and a redirect/verify-controlled download in `geometry`). No
  mixed `requests`/`urllib`/`httpx` sprawl.
- **BL-181** ✅ **tenacity/diskcache/apscheduler** — all three are dependencies AND adopted: **diskcache** backs the
  retrieval cache (`retrieval_cache.py`), **apscheduler** runs the scheduler (`layla/scheduler/registry.py` +
  automation), and **tenacity** — previously declared-but-unused — now backs a shared `retry_util.retry_call` /
  `@resilient` helper (exponential backoff + jitter, stdlib fallback) adopted in the HF-Hub download. Verified
  (test_retry_util.py, 6).

## W11 — Companion depth (ADR-006, deliberately "later")
- **BL-190** ✅ **experience unification** — the three strands are now all present: **continuity** (welcome-back +
  `timeline`/`relationship_codex` recall), **passive initiative** (`initiative_engine` + BL-240 proactive goal hints),
  and the missing piece **emotional presence** — BUILT: `services/personality/emotional_presence.py` keeps a light,
  decaying affect state (valence + energy) nudged by interaction signals (praise/correction/success/…), surfaced as a
  subtle tone-tinting prompt hint (flag `emotional_presence_enabled`), and wired to answer-feedback (👍/👎 nudge mood).
  `/mood` get/signal/reset. Verified (test_emotional_presence.py, 8).
- **BL-191** ✅ **growth-system polish** — the maturity/evolution stack (`maturity_engine`, `evolution`,
  `operator_quiz`, `character_creator`, `aspect_behavior`) is complete + tested with no stubs/TODOs, and this cycle's
  companion-depth additions layer onto it: the **operating manual** (BL-236), **decision memory** (BL-235), **skill
  acquisition** (BL-238) and **emotional presence** (BL-190) all feed how Layla grows and shows up over time.
  · **BL-192** ✅ **memory/learning verification pipeline** — BUILT —
  `services/memory/learning_verification.py`: `find_contradictions()` catches learnings that make opposite-polarity
  claims about the same subject (model-free heuristic: shared subject terms + a negation/affirmation flip), and
  `run_verification_pass()` unifies decay-awareness + low-confidence pruning + due-for-review + contradiction-flagging
  into one report. `/memory/verification/run` + `/contradictions`. Verified (test_learning_verification.py, 5).

## W12 — Post-feature polish + generalization (operator, 2026-07-05)
- **BL-220** ✅ **Generalized multi-language tutor** — BUILT — extend the German tutor (BL-040) into a **language-agnostic**
  learning system that works for **any** language, shipping **German + Italian + Spanish** now. Design: a `LANGUAGES`
  registry (code · name · native · CEFR-applicable · has-rule-patterns); **LLM-based correction** as the generalized
  engine (prompt the model as a `{language}` tutor at CEFR `{level}` → errors + corrected text), keeping German's fast
  regex `_ERROR_PATTERNS` as an optional supplement; per-`(user, language)` profile/level; flashcard SRS tagged by
  language; per-language calibration sentences (curated starters for de/it/es, LLM-generated for the long tail). New
  `/language/*` API (language-parametrized) with `/german/*` kept as a compat alias; UI gets a **language picker** so
  the same panel teaches any language. Adding a language = one registry entry (+ optional starter sentences);
  correction/flashcards/level work for free via the LLM path.
- **BL-221** ✅ **WebUI review (scaling + design)** — responsive audit done against the live UI at desktop (1280) and
  mobile (390) via the preview harness. **Measurable scaling is clean at both:** zero horizontal overflow
  (`body.scrollWidth == innerWidth`), no element wider than the viewport, the right panel + overlays cap to viewport
  width, columns align (sidebar+main, no gap), and **0 sub-32px touch targets** across 40 visible buttons. Hardened the
  one anomaly — the mobile **sidebar is now an authoritative off-canvas drawer**: added a `@media (max-width:768px)`
  block to `layla-rebuild.css` (the last-loaded sheet, so it wins the cascade) that defaults the sidebar off-screen,
  slides it in on `.mobile-open` (the existing `#mobile-hamburger` toggle), and gives the chat area full width.
  _(Subjective per-screen visual polish is an ongoing operator-pointed collaboration — the structural/responsive
  foundation is verified sound; the animated renderer blocks static screenshots, so live-app spot checks are the venue
  for taste-level tweaks.)_

## W13 — Capability audit (operator's 26-feature review, 2026-07-05) — OSS-first
*Audited the operator's 26 requested capabilities against the codebase. **12 already built** (fs-watcher=`watchdog`,
adaptive-tool-learning=`strategy_stats`/`experience_replay`, context-compression=`prompt_compressor`, model-routing=
`model_router`, what-if-sandbox=`cognitive_workspace`, curiosity=`curiosity_engine`, autonomous-maintenance=
`self_improvement`+`system_doctor`, multi-agent=`coordinator`, checkpoint/rollback=`file_checkpoints`, confidence=
`answer_assessment`, resource-scheduling=`resource_governor`, marketplace=`kit_catalog`). The rest, prefer prebuilt OSS:*
- **BL-230** ✅ **Visual understanding (VLM)** — BUILT — `services/vision/vlm_backend.py`: optional local **GGUF
  multimodal** backend (LLaVA/moondream2/Qwen2-VL via **llama-cpp-python**'s `Llava15ChatHandler`, gated by
  `vision_model_path`+`vision_mmproj_path`), degrading gracefully when absent. `services/vision/image_analysis.py`
  unifies it with the pre-existing BLIP captioner + Tesseract/EasyOCR OCR into one `analyze_image`. New **`analyze_image`
  tool** (198 total) + **image input on `/v1`** (data-URI content parts → decoded in-sandbox → analyzed → injected,
  SSRF-safe, gated). Gated feature **`vision`** in the setup manifest. `/vision/analyze` + `/vision/status`. Verified
  (test_vision.py, 10). _(GGUF inference itself is model/compute-blocked; the plumbing + fallbacks are tested via mocks.)_
- **BL-231** ✅ **Workflow recorder & macro engine** — BUILT — `services/skills/macros.py`: SQLite macro store;
  `record_from_run()` extracts a run's successful `{tool,args}` steps (tool steps now carry a compact args snapshot);
  `replay_macro()` re-dispatches through the live `TOOLS` registry with `{{param}}` substitution, confirm-gated +
  stop-on-error. `/macros/*` router + `components/macros.js` (⌘K "Macros / workflows"). Verified (test_macros.py, 9).
- **BL-232** ✅ **Cross-project reasoning** — BUILT — OSS: **`networkx`** graph over the entity codex + per-project memories to
  surface shared entities / transferable knowledge across repos. `/intelligence/cross-project` + a codex view.
- **BL-233** ✅ **Event-driven automation engine** — BUILT — `services/automation/rules_engine.py`: SQLite rule store
  (event→action) + `dispatch_event()` matching (event type + fnmatch glob) that runs actions reusing existing
  capabilities (run_macro/record_timeline/reindex/log). `knowledge_watcher` emits `file_created`/`file_modified`
  events into it; `POST /automation/emit` lets git hooks/schedulers fire `git_commit`/`schedule`. Each action is
  isolated so one bad rule never blocks others or the watcher. `/automation/rules` CRUD. Verified (test_automation.py, 7).
- **BL-234** ✅ **Temporal memory timeline** — BUILT (API) — `services/memory/timeline.py` over the existing
  `timeline_events`/`episodes`/`episode_events` tables: `query_timeline` (range/type/project/importance + paginate),
  `timeline_days` (per-day buckets for a calendar/heatmap), `list_episodes` + `reconstruct_episode` (episode + its
  events, chronological). `/timeline`, `/timeline/days`, `/timeline/episodes[/{id}]`. Verified (test_timeline.py, 4).
  _(UI surface folds into the deferred BL-221 WebUI pass.)_
- **BL-235** ✅ **Decision memory** — BUILT — `services/memory/decision_memory.py` (SQLite `decisions.db`): stores
  chosen option + rationale + rejected alternatives + assumptions + goal/context. `run_deliberation()` persists every
  real decision (best-effort). `/decisions` list/search/get + record. Verified (test_decision_memory.py, 5).
- **BL-236** ✅ **Personal operating manual** — BUILT — `services/personality/operating_manual.py`: `build_manual()`
  consolidates derived identity (verbosity/humour/formality/response-length, always current) + operator-quiz work
  domains/traits + a growing store of user-appended notes (habits, workflows, comm-style) into one living doc.
  `manual_markdown()` + `manual_for_prompt()` (compact digest for prompt personalization). `/manual` + `/manual/notes`
  CRUD + `/manual/summary`. Verified (test_operating_manual.py, 5).
- **BL-237** ✅ **Explainable reasoning mode** — BUILT — `services/agent/explain.py`: `build_explanation()` distils a
  run's trace (think-thoughts + tool sequence with ✓/✗ outcomes + conclusion) into a structured + markdown "why",
  deterministic (no extra model call). `run_finalizer` attaches `state["explanation"]` when
  `explainable_reasoning_enabled` is on (inert by default). `POST /explain` for any trace. Verified (test_explain.py, 5).
- **BL-238** ✅ **Skill acquisition from tasks** — BUILT — `services/skills/skill_acquisition.py`: `acquire_from_run()`
  turns a successful run's tool sequence into a named **learned skill** — steps stored as a macro (BL-231, reused for
  validation + `{{param}}` replay), identity in a `learned_skill` store (name auto-derived from the goal). Learned
  skills are discoverable/invocable beyond installed packs: `invoke_skill` replays, `forget_skill` removes both.
  `/skills/learned` list/acquire/get/invoke/forget. Verified (test_skill_acquisition.py, 6).
- **BL-239** ✅ **Plugin SDK polish** — BUILT — `services/skills/plugin_sdk.py`: `scaffold_plugin()` generates a plugin
  skeleton (via **`cookiecutter`** against the shipped `plugins/_template/` when available, else a built-in render of
  the same layout) + `validate_manifest()` enforcing the contract incl. **version pinning** (semver `version` +
  `requires.layla_api` range checked against `LAYLA_PLUGIN_API`). Top-level **PLUGINS.md** dev guide. `/plugins`
  scaffold/validate/api-version. Verified (test_plugin_sdk.py, 9).
- **BL-240** ✅ **Goals: proactive progress + suggestions** — BUILT — `services/planning/goal_tracker.py`: reads the
  goals/goal_progress store as a dashboard (latest %, days-idle, momentum) and derives proactive nudges — stalled
  goals to resume, near-done to finish, fresh to break down. `collect_initiative_hints` now folds in
  `initiative_goal_hints()`, so long-term goals surface over weeks, not just within a turn. Added `get_goal_progress`
  + `set_goal_status` readers to user_profile. `/goals` dashboard + `/goals/suggestions` + create/progress/status.
  Verified (test_goal_tracker.py, 4).
- **BL-241** ✅ **World state model** — BUILT — `services/workspace/world_state.py`: `snapshot()` assembles one live
  view from existing sources — current `project_context`, known/open projects, `repo_indexer` stats, hardware probe,
  resource-governor mode — each read best-effort so a missing subsystem degrades that field, not the snapshot.
  `summarize()` gives a compact prompt-injectable digest. `/world` + `/world/summary`. Verified (test_world_state.py, 3).
- **BL-242** ✅ **Learning from feedback wiring** — BUILT — `services/infrastructure/answer_feedback.py`: records
  👍/👎 on answers; a 👎 with a written correction is routed into the learning store (`save_learning kind=correction`,
  the existing channel into planning/prompts) AND surfaced as a prompt hint. `system_head_builder` now injects
  `feedback_hint_for_prompt()` right after the RL hint, so the next turn honours recent corrections — closing the loop
  `rl_feedback` started. `/feedback` (record) + `/feedback/stats` + `/feedback/hint`. Verified (test_answer_feedback.py, 6).

---

## Definition-of-Done gates (the "truly-ready" bar)
1. Zero 🟡/⬜ in the UPG backlog (or each explicitly ✂️ cut).
2. Scope cut to the wedge (W9/Phase 3).
3. Security tier (W1) complete — safe to expose through a tunnel.
4. Full-app E2E green + one-command install (BL-174).
5. Truly-ready gate = Phase 7 polish complete.

**Honest sizing:** this is **weeks-to-months**. W0 is hours; W1 + W2 (German UI especially) are the
highest-leverage; W8/W11 are V2/V3 horizon.

---

> **EXECUTION:** W14/W15/W16 are sequenced for execution in [`phases/13-castilla-repair/CONTEXT.md`](phases/13-castilla-repair/CONTEXT.md) (slices S0-S10, S0 done).
> Evidence + honest caveats: [`phases/13-castilla-repair/VERIFICATION.md`](phases/13-castilla-repair/VERIFICATION.md).

## W14 — Castilla release repair (operator UI/UX audit, 2026-07-16) — the friend-ready gate

*Trigger: the operator drove the actual UI and found it broken in ways the 2,700-test suite could not see. Five
parallel adversarial audits followed (conversation persistence · UI bug repro · per-feature discoverability ·
setup/TTS/accessibility · content-policy & model tiers). **41 defects confirmed, 1 disproven.** Every item cites
file:line and is marked CONFIRMED (traced to code / reproduced live) or REPORTED (operator-observed, not yet
root-caused).*

**Why the suite missed all of this:** every prior test asserted *which fields a render function reads*, never that
anything *calls* it. Green suite, dead feature. The class guard landed in `test_ui_js_contract.py` (every spinner
pane must register its loader + route) — read it before writing any W14 test.

### W14a — Conversation history (the operator's #1; "fixed" 3x and still broken)

- ⬜ **BL-243** Rail never re-renders after the async title lands. CONFIRMED: `routers/agent.py:356` synthesizes
  the title on a **background thread**; the rail has **no polling and no re-render**. Live proof:
  `System Capabilities Table` created `10:13:35`, **updated `10:17:30`** — the good title arrived ~4 min later and
  the UI never showed it. This is the operator's "it never reloads the UI once it's actually done loading".
  Fix: push (SSE/bus event) or a bounded poll after turn completion. NOT a rail-load bug — the rail renders.
- ⬜ **BL-244** Title wraps badly; timestamp stranded mid-title. CONFIRMED `conversations.js:325-336` +
  `layla.css:2563-2567`: the title is a **bare text node** sharing one inline `-webkit-box` with `.conv-meta`
  (`display:inline-flex`), so the dot/pin/project/tag chips consume line 1 and push the title to wrap;
  `.sess-date` is a flex sibling pinned by `align-items:flex-start`, so "2h" sits level with line 1 of a
  multi-line title. Fix: give the title its own element, stack meta/title vertically, `overflow-wrap:anywhere`
  (not `word-break:break-word`), clamp 2. (CSS comment says 2 lines; the rule clamps 3 — stale.)
- ⬜ **BL-245** 7 error/abort paths never persist the turn — the user's message vanishes. CONFIRMED
  `routers/agent.py:1172` (error), `:1178` (under load), `:1183` (timeout), `:1189` (client abort), `:1195`
  (pipeline_needs_input), `:1403`, `:995` all yield `done:true` with no persist block. Realistic on a CPU-only
  box where timeouts are common. Likely contributor to "history is broken".

### W14b — Discoverability (the headline: shipped features that cannot be reached)

- ⬜ **BL-246** `header { display: none }` — **one CSS line kills 4 features.** CONFIRMED `layla.css:242`,
  unconditional, no JS override; runtime-confirmed every child computes HIDDEN. `.topbar` re-implements only 5 of
  the buttons. Dead with **no other entry point anywhere**: **Global search** (`index.html:208-215`) and **Aspect
  lock** (`:178`) — both advertised in the wizard's "What's new" card. Orphaned to Ctrl+K-only: `Commands`
  (`:184`), `Intel` (`:185`), and the `/settings/schema` modal gear (`:188`). **Cheapest high-value fix in the
  backlog** — partially resolves BL-247 and BL-252 too.
- ⬜ **BL-247** **21 features are Ctrl+K-only** and the button that opens Ctrl+K is invisible (BL-246). CONFIRMED,
  each grepped for another entry point (zero): german, missions, journal, improvements, tools-history, sync,
  debate, codex, verify, agent-tasks, kb, plans, intake-quiz, custom-aspect, welcome, marketplace, tutor, macros,
  self-test, setup-wizard, system-diagnostics, plus intelligence. The palette is mentioned in exactly ONE place a
  user might read (the input hint, `:433`). No browsable list exists. Two vanish silently when feature-gated
  (sync, debate).
- ⬜ **BL-248** **The entire Growth panel is unreachable.** CONFIRMED `index.html:1052` `style="display:none"` +
  `bootstrap.js:183` `_rcpAliases = { growth: 'status' }`. Lost: XP bar, **Unlocked Abilities**, velocity
  sparkline, verification breakdown, "Review pending facts". The maturity card says *"Growth is real. Click to
  open Growth panel"* (`:266`) and routes to Dashboard instead. **Plus 7 duplicate IDs** (growth-total-facts,
  growth-verified-pct, growth-week-count, growth-pending-verify, growth-capabilities-list, growth-types-list,
  growth-watcher-status) — `getElementById` silently binds the Dashboard copy.
- ⬜ **BL-249** First-run **introduces zero features**, and the only tour that would is **dead code**. CONFIRMED
  `setup.js:315-337` is the sole place explaining workspace scoping / aspect selection / aspect lock; it targets
  `#onboarding-overlay`, `#onboarding-text`, `#onboarding-next`, `#onboarding-done` — **none exist in
  index.html**. `maybeStartOnboarding()` (`setup.js:339`) early-returns forever.
- ⬜ **BL-250** **The wizard is SKIPPED when the install goes well.** CONFIRMED `wizard.js:236` early-returns on
  `wizard_complete || ready`; an installer/CLI that provisions a model sets `ready=true`. **The better the
  install, the less the friend is told** — they lose the workspace picker, character quiz, voice picker, and the
  entire "What's new" feature list. Worst single item for the actual handoff.
- ⬜ **BL-251** The 95-key schema modal is flat AND Ctrl+K-only. CONFIRMED `config_schema.py` has 95 keys across 9
  categories; `get_schema_for_api()` returns `categories` and **`settings-full.js` never reads it** (grep
  `category` -> 0 hits) — rendered as one ungrouped stream (`settings-full.js:74-89`). It is the ONLY home for:
  potato preset, admin mode + git undo, the **optional-feature installer** (the thing that would fix TTS),
  WhatsApp import, appearance/lite mode.
- ⬜ **BL-252** **Two gear buttons, same icon, same tooltip, different destinations** — one invisible. Topbar gear
  (`:367`) -> friendly prefs (~25 toggles); header gear (`:188`) -> 95 raw keys, unreachable. They overlap on
  uncensored, nsfw_allowed, tool_approval_bypass, deliberation_mode, tts_*, admin_mode; both POST `/settings`;
  neither cross-links. Also "Speak replies" appears **twice in the same prefs panel** (`#tts-toggle` `:616`,
  `#tts-toggle2` `:716`).
- ⬜ **BL-253** Raw paths/IDs/JSON with **not one browse button in the app**: `#km-source` "URL or folder path
  (inside sandbox)" (`:840`), `#workspace-path` (`:698`), `#obsidian-vault-path` (`:758`), `#cluster-queen-addr`
  "192.168.1.10:8000" + token (`:537`), `#models-hf-repo`/`-file` (`:1266`), `#relationship-codex-json` raw
  `{"entities":{}}` (`:967`), `#admin-undo-workspace` (`:1215`).
- ⬜ **BL-254** Research tab **leads with an API console**: `POST /autonomous/run`, `confirm_autonomous`,
  `research_mode`, `max_steps`, `timeout_s` (`:1009-1017`). The friendly "Start mission" buttons live in a
  *different* surface (prefs -> Research Mission `:743`), cross-linked one way only.
- ⬜ **BL-255** `#cluster-enable-toggle` is a bare `<div>` (`:532`) — runtime-confirmed `role=null, tabindex=null`.
  Invisible to keyboard + screen readers, in a section that otherwise uses real buttons.
- ⬜ **BL-256** Undefined jargon in primary labels: "Governor" (`:309`), "sandbox" (`:840`), "Compact" (`:365`),
  "Tribunal (6)" (`:640`), "Ctx:" (`:430`), and `GET /memory/elasticsearch/search` shown as an empty state
  (`:946`).
- ⬜ **BL-257** No user tutorials. `docs/` is ~40 internal/architecture files; exactly ONE user guide exists
  (`RESEARCH_MISSION_UI_GUIDE.md`). Nothing explains ingestion, memory, growth, study, or aspects.

### W14c — Dead/broken UI (all CONFIRMED with exact root cause)

- ⬜ **BL-258** **Study quick presets are 100% dead, silently.** CONFIRMED `workspace.js:191` (+`:197`):
  `JSON.stringify` emits **double** quotes into a **double**-quoted `onclick` attribute, so the parser ends the
  attribute at the inner quote -> SyntaxError, handler never runs. The label is a separate text node, so the
  button **looks perfect and does nothing**. CSP and the `window.addStudyPlan` export were both ruled out. Fix:
  use the delegated `data-action`/`data-arg` system already used at `:168`.
- ⬜ **BL-259** Model manager renders `Available: [object Object], ...`. CONFIRMED `workspace.js:33` joins model
  **objects**; `/platform/models` returns `{filename, path, size_mb}`. (`active` is a plain string — which is why
  only that line renders correctly.) Fix: map `.filename`.
- ⬜ **BL-260** Recent learnings render as word salad. CONFIRMED `workspace.js:46` (+`:48`) flattens 5 records
  into **one text node** joined by `' · '`; the API already returns `id` and `type` and both are discarded.
  Because the stored fragments are themselves sentence fragments, joining reads as one run-on sentence. Fix: one
  row per learning + type chip (mirror `refreshSkillsList` at `:262`).
- ⬜ **BL-261** i18n: panel buttons never translate. CONFIRMED the applier is **fine** (`i18n.js:72-84` re-runs on
  `layla:languagechange`). Coverage is the bug: **127 of 162 static buttons (78%) have no `data-i18n`**, and
  ~**168 buttons built dynamically across 40 JS files** are injected as hardcoded English via `innerHTML` (11
  `data-i18n` occurrences in ALL JS combined). Even translated ones revert when a `refreshX()` re-injects. Fix:
  (a) markup pass; (b) `applyTranslations(box)` after every dynamic render. **Own pass — not a quick fix.**
- ⬜ **BL-262** DOMPurify strips table column alignment. CONFIRMED `services/utils.js:133`
  `ALLOWED_ATTR:['href','class']` drops the `align` attr marked emits for `|:---:|`. Fix: add `'align'`.
- 🟡 **BL-263** REPORTED: a markdown table broke into raw text when the MR2 rank-up popup fired.
  **NOT REPRODUCIBLE — do not guess.** Disproved: `#rankup-overlay` only writes `#rankup-detail`
  (`aspect.js:193-208`); `bus.emit('growth:rank-up')` has **zero subscribers**; both renderers are identical
  `sanitize(marked.parse())`; marked has no config so GFM tables are on; backend cleaners executed against a real
  table leave it unchanged; `enhanceCodeBlocks` touches only `<pre>`. Two promising theories (fence-mask digit
  collision, missing `.md-content` wrapper) were executed and disproven. Leading hypothesis: the **model** emitted
  a malformed table (inconsistent column counts / no blank line before it) and the popup is a correlated symptom —
  it fires in the same millisecond as the done-frame render. **BLOCKED: needs raw `obj.content` from a recurrence.**

### W14d — Learnings quality (the "still facts loaded in" complaint)

- ⬜ **BL-264** 28 junk rows remain in the operator DB: test residue (Paris/Tokyo/8x7), **docstring parameter
  lines** ("n (int): The number to check for primality."), citations ('[1] "Python Sets". Real Python.'), aspect
  name leaks ("Nyx: For best practices..."). NOTE: 4 system-prompt-bleed rows were purged 2026-07-16 and the
  feedback loop cut (source fix in `run_finalizer.py` + floor in `distill.is_memory_junk`); these 28 are the
  remainder. **Deleting a memory store is the operator's call — ASK, do not wipe.**
- ⬜ **BL-265** No real quality gate. CONFIRMED `outcome_writer.py:277-293` accepts **any 25-200 char line
  containing always|never|should|must|note:** — system-prompt and docstring text is *dense* with these, so the
  heuristic is structurally biased toward capturing instructions over user knowledge. `learning_filter.py` only
  enforces MIN_LENGTH=40 + opening-clause hedges; `score_learning_content` returns 0.45 against a 0.35 floor, so
  junk sails through. Needs a real gate (is this a durable fact ABOUT THE USER or their work?), not a length check.
- ⬜ **BL-266** `distill._summarize_group` (`:132-149`) splits on "." — on
  `raise ValueError("n must be a non-negative integer.")` it cuts **mid string-literal**, yielding unbalanced
  quotes, then joins them -> the "[merged from 2 similar]" garbage. Jaccard matching is fine (>=0.55 genuinely
  matched near-identical fragments); naive sentence-splitting on code is the defect. Starved at the input by
  BL-265 but still wrong.

### W14e — Capabilities (displays a frozen constant)

- ⬜ **BL-267** **Capability scores can never move from normal use.** CONFIRMED: `record_practice()` has exactly
  two callers — `layla/scheduler/jobs.py:342` and `routers/study.py:419`, **both the study subsystem**. It is
  never called from `routers/agent.py` or any chat/agent turn path. DB proof: all 23 domains `level 0.49`,
  `practice_count 0`, `last_practiced_at NULL`; `capability_events` holds **23 rows, all decay_tick, all stamped
  2026-07-05T20:04:24** — nothing since, despite 228 prompts including coding questions. Decide: wire practice
  into the turn path (classify domain -> record on success), or **stop displaying a fake number**.
- ⬜ **BL-268** "+ 11 more" — hardcoded cap of 12 at `growth.js:250`. Operator wants all shown. Trivial.
- ⬜ **BL-269** **Operator domain picks do not exist.** CONFIRMED all 23 domains are hardcoded seeds
  (`data_migrations.py:185,219`) — including a full fabrication set (cad_modeling, cnc_machining, feeds_and_speeds,
  furniture_design, woodworking, wood_assembly, structural_building). There is no interests/focus_domains setting
  anywhere. Every user gets CNC Machining. NEW FEATURE: pick domains at first-run (-> BL-276), then filter.
  Compounds BL-267: 23 frozen 0.5s, most irrelevant to whoever is using it.

### W14f — Voice / TTS / accessibility

- ⬜ **BL-270** **Server TTS is 100% dead.** CONFIRMED missing from `.venv`: kokoro_onnx, pyttsx3, soundfile,
  onnxruntime — and faster_whisper, so **STT is dead too**. Live: `POST /voice/speak` -> **503 "TTS not
  available"**. What the operator hears is an undocumented browser `speechSynthesis` fallback (`voice.js:206`) —
  generic OS voice, **truncated to 500 chars** (`:208`), and the speed/volume sliders (`:180,197`) apply **only to
  the dead server path**. Root cause: the default `companion` profile excludes the `voice` feature
  (`setup_profiles.py:17-20` installs kokoro+whisper; only language/power include it) and
  `auto_pip_install_optional=false`.
- ⬜ **BL-271** **The Speak-replies toggle silently no-ops until a page reload.** CONFIRMED `voice.js:174` gates on
  a **module-local** `_ttsEnabled` written once at load (`:63,67`); the toggle only sets the window mirror
  (`main.js:519`). No exported setter exists (grep setTtsEnabled -> 0), and `initVoiceControls` sets `.checked`
  with **no change listener** (the adjacent stream toggle has one, `:79`). **This is the bug behind the operator's
  distrust.**
- ⬜ **BL-272** The checkbox **lies about its own state**. CONFIRMED `voice.js:67` treats unset as OFF;
  `obsidian.js:121` treats unset as **ON**. On a fresh profile the box renders **CHECKED while the engine is OFF**.
  (Operator asked for "speak replies off by default" — it already IS off authoritatively; the fix is deleting the
  contradiction, not changing the default.)
- ⬜ **BL-273** **No TTS availability flag** on `/health` or `/settings` (only `tts_voice:null`, `tts_speed:1.0`).
  The UI cannot know TTS is dead, so it offers a toggle for a feature that cannot work. `/doctor` omits it too.
  Root of the trust problem. **BL-270 + BL-271 + BL-273 must ship together** — fixing the toggle alone just makes
  a robot voice appear and reads as another failure.
- ⬜ **BL-274** **No Accessibility section exists anywhere.** The invisible baseline is genuinely good (96
  aria-label, focus traps WCAG 2.4.3, contrast tuned to AA with the failures documented in comments,
  prefers-reduced-motion honored, 11 locales + RTL) — but every a11y affordance is either a CSS media query or
  filed under an unrelated heading.
  - **Text size: ZERO implementation** (grep font-scale|text-size|textScale -> no hits). Biggest a11y gap.
  - **Reduced motion: OS-only.** `toggleLowFx` (`main.js:537`, sets `--fx-strength`) is a de-facto control
    **mislabelled as a graphics/perf option**. A user on a non-signalling OS has no path.
  - **High contrast:** OS-only, one CSS block, no toggle.
  - `index.html:202-204` `tabindex="-1"` **removes Character Lab / Compact / Terminal from keyboard reach**.
  - `index.html:169` — Escape will not dismiss the wizard (WCAG 2.1.2 concern).

### W14g — First-run setup (4 chained flows, ~17 steps)

*Today: Wizard (6 steps) -> Setup overlay -> Profile wizard -> Onboarding interview (6 stages). Workspace asked
**twice** (wizard 1 & 2); personality asked **three times** (wizard 3, wizard 4, interview personality).*

- ⬜ **BL-275** **No accessibility step.** TTS + text size + reduced motion + high contrast. Must trigger the
  `voice` feature install (BL-270).
- ⬜ **BL-276** **No content-policy disclosure.** `uncensored:true` and `nsfw_allowed:true` are ON by default and
  **never mentioned in any of the four flows**. UX and liability gap. Fold in the domain picks (BL-269).
- ⬜ **BL-277** **No language picker.** 11 locales + RTL ship; first-run never offers them — **RTL users start in
  LTR English**.
- ⬜ **BL-278** No data-dir disclosure. `/doctor` reports `database.exists:false`, `config.exists:false`; the user
  is never told where state lives.
- ⬜ **BL-279** Dedupe workspace (x2) and personality (x3); ~17 steps is heavy abandonment surface.
- ⬜ **BL-280** Rename wizard step 4 — **"Choose a voice" is the ASPECT picker, not TTS.** Actively cruel while TTS
  is silently dead.

### W14h — Content policy & model tiers

*KEY CORRECTION: **uncensored/NSFW is ALREADY the fresh-install default** — verified by executing the config chain
against an empty data dir (uncensored=True, nsfw_allowed=True; all five default sites agree). And `safe_mode:true`
alongside them is **NOT a contradiction**: safe_mode is not a content flag — its only reader is a destructive-tool
approval floor (`tool_dispatch_base.py:113`). The operator's ask is therefore NOT a settings change — it is a
**model-selection and guard-precision problem**.*

- ⬜ **BL-281** **The shipped model is the dominant gap.** `Qwen2.5-3B-Instruct` is Alibaba **safety-tuned**;
  `uncensored:true` adds one prompt paragraph its RLHF overrides. Config says yes, the model says no.
- ⬜ **BL-282** `recommend_kit` — **the path that actually ships** (`provision_model.py:65`, Castilla default,
  `prefer="lite"`) — has **no uncensored term at all** (`model_selector.py:403-413`) -> picks qwen2.5-3b-instruct.
  `recommend_model` (`:250`) has a jinx term but it is a **tiebreak behind mem_req**, so smallest-fits-first always
  wins -> qwen2.5-coder-0.5b. Only `models_for_picker` (`:36-79`, the picker UI) ranks uncensored-first — and it
  correctly picks dolphin-2.9.4-llama3.1-8b.
- ⬜ **BL-283** **Catalog data bug — must ship WITH BL-282, not after.** `model_catalog.json` labels stock
  bartowski Qwen2.5-Instruct `uncensored:true` at 7B/14B/32B/72B while the *same family* is false at 0.5B/1.5B/3B.
  All are safety-tuned; none abliterated. Fixing the ranking first would make the recommender confidently rank a
  **censored** model top.
- ⬜ **BL-284** **content_guard Tier 1 blocks ordinary adult content, non-overridably.** CONFIRMED
  `content_guard.py:49-53`: order-independent lookaheads pairing
  (child|minor|underage|preteen|toddler|infant|kid|boy|girl) with (naked|nude|sexual|porn|erotic|molest|abuse)
  over a **20,000-char window** (`:131`). Any adult scene using girl/boy within 20k chars of erotic hits a
  hardcoded refusal. The guard reads only content_guard_* — `uncensored` does **not** disable it. **The CSAM
  intent is legitimate and MUST stay**; the *pattern* is over-broad. Fix: restrict age terms to
  child|minor|underage|preteen|toddler|infant (drop kid|boy|girl — not age indicators in adult prose) and scope
  the compound match to a sentence/paragraph window instead of 20k chars. Precision fix, not a weakening.
- ⬜ **BL-285** **The prompt fights itself.** `prompt_builder.py:134` (honesty_and_boundaries_enabled, default
  True) injects "Refuse or redirect requests that would cause harm" into the **same prompt** as the uncensored
  paragraph at `:173`. A 3B resolves the conflict toward refusal. Also `:184` — the strongest anti-refusal
  paragraph only fires when the **goal text literally contains** nsfw|intimate|explicit|adult|18+|uncensored;
  ordinary phrasing misses it. Fix: drop the keyword gate; soften/skip the refuse clause when uncensored is on.
- ⬜ **BL-286** Dead flags with disagreeing writers: `knowledge_unrestricted` + `anonymous_access` are written by
  `first_run.py:84`, `setup_engine.py:118`, `runtime_config.example.json:12-13` and **immediately deleted** by
  `config_migrator.py:31-32` ("was dead config flag"). Zero readers.
- ⬜ **BL-287** Consider renaming `safe_mode` -> `destructive_tool_approval_floor`, or document it in the UI. It
  reads as a content flag and is not one — that misreading is what prompted this audit.

### W14i — Operator feature requests (new work, not defects)

- ⬜ **BL-288** Runtime & options: **sliders** for max_cpu_percent / max_ram_percent / max_active_runs (currently a
  read-only text dump). Must respect the auto-tune tier + governor clamps.
- ⬜ **BL-289** **Run diagnostics: human-readable FIRST**, JSON dump behind a disclosure for technical users.
  Applies to the same raw-JSON dumps at `index.html:478`, `:486`, `:829`.
- ⬜ **BL-290** Light theme is a **flashbang** — retune to lilac (light purple), not white. `layla.css:84`
  `body.theme-light`; accent already tuned for AA at `:99` — keep the contrast ratios when changing.
- ⬜ **BL-291** Ingestion shortcut. **Blocked on a design decision:** there is **no ingestion folder** —
  `#km-source` takes a URL or a hand-typed sandbox path; `ingest_directory()` takes an arbitrary path; there is no
  watched drop-folder. And **a browser cannot open Explorer** — it needs a backend endpoint shelling out to
  explorer.exe, a local-only action with real security weight on an app that also accepts remote connections.
  Options: (a) invent a real watched `LAYLA_DATA_DIR/ingest/` with auto-ingest + a reveal endpoint, (b) a plain
  "reveal sandbox folder" button, (c) neither — instead fix **`#km-ingest-list`** (`index.html:844`), which is
  **declared and written by nothing**, so you cannot see what you already ingested.
- ⬜ **BL-292** **Build the GSD operating method into Layla's normal behaviour** (plan -> execute -> verify, phase
  artifacts, explicit gates). **MILESTONE-SIZED, NOT A TASK.** Interacts with study/capabilities (W14e), the
  reasoning trace, and the run loop. Needs its own discovery + spec before any estimate. Do not start it inside W14.

### W14j — Release / operator actions

- 🟡 **BL-293** **ROTATE `agent/.layla/memory_encryption.key`** if any installer was built and shared before
  2026-07-16. The pre-fix `build_installer.ps1` recursively copied the working tree into the payload, shipping the
  Fernet key, 2,070 operator embedding vectors, .governance/ logs, and local paths. Export is now
  `git archive HEAD` + a build-time leak gate (landed; `test_release_hygiene.py`). **OPERATOR ACTION — Claude
  cannot know whether a build was shared.**

### The rule for W14 (non-negotiable)

**Nothing here is marked done on Claude's say-so.** Claude cannot see the rendered UI (preview tooling is banned by
the operator), so "tests pass" is NOT verification. Every W14 item is marked done only after the OPERATOR confirms
it in the browser. Claude's report must state: what changed · what was PROVED · what was ASSUMED · what is still
unverified. No check-marks, no confidence scores. This rule exists because the same class of bug was declared fixed
three times while the operator was looking at it still broken.

### W14k — Capability-table verification (2026-07-16) — **every mark was too generous**

*The operator supplied a 40-feature capability table with confidence marks and asked for it to be verified and
seeded into Layla's knowledge. Three parallel adversarial audits re-checked every row. **Result: not one row
survived unchanged in the categories audited — 11/11 in coding/companion downgraded or contradicted, plus 14
interface/safety rows.** Root cause, in the auditor's words: **tests validate storage and API shape, never
end-to-end effect.** Every dead feature below has passing tests.*

**DO NOT seed the operator's table into Layla's knowledge.** Seeding it would convert hallucination into
confident lying — she would tell the friend her Python sandbox has no network access (it has), that she has
tree-sitter symbol search (never installed), and that she can speak (every TTS engine missing). The manifest
(BL-306) must be built from verified data only.

#### The structural finding — read this before fixing anything in W14k

- ⬜ **BL-294** **The fast-path bypasses `finalize_run_state`.** CONFIRMED: `grep finalize_run_state
  routers/agent.py` → **zero hits**; the finalizer lives in `services/agent/run_finalizer.py` and only the
  orchestrated path calls it. Every subsystem hanging off that finalizer — **personality recording, maturity XP,
  entity extraction, routing telemetry, learning extraction** — is *live in the pipeline and dead on the common
  turn*. The fast-path handles trivial/self-contained turns, i.e. most real ones. This is the single highest-
  leverage defect in W14: it explains BL-267 (frozen capabilities) and the "live loop that never runs" pattern
  across the companion tier. **Audit every subsystem marked "live" for whether it is live on the FAST path.**

#### Security — three HIGH, all "defence-in-depth failing quietly while advertising success"

- ⬜ **BL-295** **HIGH — the Python network jail is decorative.** CONTRADICTS the table's "jail confirmed; a test
  asserts getaddrinfo is blocked". `python_runner.py:51-65` patches the `socket` **wrapper module**, not the
  `_socket` C extension. **6 live bypasses proven, including a real HTTP 200**: `import _socket`,
  `importlib.reload(socket)`, `python -S`, `python -E`, `os.system('curl')`. The cited test only asserts the one
  shadowed name is shadowed — it never tries to undo the patch. **On by default.** Remove "network-jailed" from
  every user-facing description until fixed. Realistic threat: a prompt-injected model (URL ingestion is a real
  injection path) emitting exfiltration code.
- ⬜ **BL-296** **HIGH — `.exe` defeats the shell blocklist on Windows, the shipping OS.** Reproduced directly:
  `powershell` blocked / `powershell.exe` **ALLOWED**; same for `cmd.exe`, `reg.exe`, `curl.exe`, `rm.exe`,
  `pwsh`, `bash`. `shell_runner.py:56-70` does basename equality and the comment shows the reasoning is POSIX
  ("/usr/bin/rm is blocked, but 'charm' is not") — correct on Linux, defeated by four characters on Windows.
  Compounding: **`shell_restrict_to_allowlist` defaults to False** (`runtime_safety.py:504`), so the allowlist is
  **dead code** and a 16-item blocklist is the only control → **allow-by-default**, not the advertised
  "deny-by-default". The approval gate IS real and is the actual mitigation. Fix: normalize `.exe`/`.cmd`/`.bat`
  before matching; consider defaulting the allowlist on.
- ⬜ **BL-297** **HIGH — the post-model safety floor does not protect streaming, which is the default.**
  `check_output` runs *after* the token loop (`openai_compat.py:373-379`); tokens are already emitted. The code's
  own comment concedes it. Every guard site is `except: pass` **fail-open**. Same done-frame-vs-stream shape as
  the known glossary flash — but here the "flash" is the entire unguarded output. Corrects a prior claim: the
  guard is **not** unwired (8 sites, 50 passing tests); it is wired and ineffective on the common path.
- ⬜ **BL-298** MEDIUM-HIGH — browser tool SSRF via redirect (`browser.py:126,149,167`): Playwright follows 302s
  to internal hosts unrevalidated.
- ⬜ **BL-299** MEDIUM — **the SSRF docstring claims a TOCTOU/DNS-rebinding guard that the code does not
  implement** (`url_guard.py:119-124`). The false assurance is worse than the gap. Either implement or delete the
  claim. (Good news, prior mark corrected: there is **no** second weaker SSRF implementation — all four download
  paths delegate to the single hardened `url_guard`.)
- ⬜ **BL-300** MEDIUM — Windows Job Object "isolation" is **default-off, fail-open, silent, untested**, and is a
  resource cap, not isolation. `has_keyring()` tests importability, not viability.
- ✅ **GOOD NEWS (no action)** — the **filesystem jail is genuine**. It survived every escape attempt tried:
  NTFS junctions, `\\?\` prefixes, `\\localhost\C$`, `..` traversal, case tricks
  (`layla/tools/sandbox_core.py:161-172`). Only gap: tests are 4 trivial cases and the symlink test skips on
  Windows.

#### Features that are dead, inert, or lying (all CONFIRMED)

- ⬜ **BL-301** **Custom aspects are INERT and the API lies about it.** `select_aspect`
  (`orchestrator.py:216-229`) iterates the JSON built-ins only, so a custom aspect id **can never match**.
  `set_main_aspect` returns `ok:True` and every subsequent turn **silently falls back to Morrigan**. Creatable and
  deletable from the UI; **never selectable**. The merge logic itself is real and tested — it is simply never
  reachable.
- ⬜ **BL-302** **Symbol search returns `ok:True` with 0 matches.** Proved live: `search_codebase('select_aspect')`
  → **0**, while `grep_code` → 218 and `code_symbols` → 9. `impl/code.py:85` is wired to the **tree-sitter**
  `code_intelligence.search_symbols`; tree-sitter is **commented out of `requirements.txt:127`**, absent from both
  venvs, and `/health/deps` reports it missing. The working, well-tested `ast`-based `repo_indexer.search_symbols`
  (24 passing tests) is **wired to nothing**. Worse than an error: Layla concludes the symbol does not exist.
  Two tests hide it — `test_code_intelligence.py` auto-skips via `importorskip`; `test_workspace_index.py:17`
  **passes while codifying the breakage** (asserts only that the dict has keys, so all-empty satisfies it).
  Fix needs a small adapter — the signatures differ.
- ⬜ **BL-303** `grep_code` **branches on environment**: `rg` is on PATH in Git Bash but NOT for the app's
  interpreter (`shutil.which('rg')` → None under `.venv`), so production silently runs a Python `re` fallback with
  different match semantics and a different result cap. Neither branch has a behavioral test. CI cannot see the
  difference between "works on my machine" and "works in the app".
- ⬜ **BL-304** **Self-improvement is 3 hardcoded strings and effectively unreachable.** `self_improvement.py:145,
  154,164`. The UI posts `{}` (`improvements.js:90`) so only the unconditional one ever fires; the
  `capability_levels` param is **never read**. The real LLM path (`initiative_engine.py:161`) is hard-forced off
  below **rank 10** (`runtime_safety.py:925` → `initiative_project_proposals_enabled = False`) ≈ **111,500 XP ≈
  37,000 turns**; live rank is **2**. Decide: lower the gate, or stop shipping it as a feature.
- ⬜ **BL-305** Discord autostart is **dead code** — `main.py:378` uses absolute imports while `bot.py:63` uses
  relative → ImportError, swallowed at `:403`. The 801-line bot is real; its 103 tests are not in CI's collection.
  One-line fix, nothing would catch the regression.

#### Marks downgraded to PARTIAL (real code, absent or non-behavioral tests)

- ⬜ **BL-307** "6 aspects, JSON single-source" → **13 duplicate rosters**, already diverged (cassandra's title
  differs between JSON and `ASPECT_DEFAULTS`). The test diffs **ids only**, so drift is unpinned.
- ⬜ **BL-308** Character Lab: the dead surface is **~4x larger** than the prior mark said — voice (4 sliders),
  colour, titles and lore are all **write-only**. Only the 6 personality sliders are live
  (`prompt_builder.py:229-233`) — and that is **the one path with no test**. Voice sliders are dead *by design*:
  `voice.py:151` has its own hardcoded table.
- ⬜ **BL-309** Personality evolution: liveness **CONFIRMED by live probe** (morrigan: 119 real interactions,
  drift `humor 0.169`, injected at `system_head_builder.py:880`) — but **zero tests**, and the fast-paths
  (`routers/agent.py:726,872`) **skip the recorder while still reading the drift** (→ BL-294).
- ⬜ **BL-310** Missions "restart-recoverable" → APScheduler has **no jobstore configured** → MemoryJobStore.
  Recovery is a DB poll, not APScheduler. Crashed missions become `paused` and are excluded from
  `get_active_missions` → **manual resume required**. `schedule_task` jobs are lost silently.
  `execute_next_step` has **zero** coverage.
- ⬜ **BL-311** `/v1` is **not a drop-in model**: `temperature`, `max_tokens`, `top_p`, `seed` are parsed and
  **deliberately discarded** (`openai_compat.py:36-55`, comment at `:39`). Only `stop` is honoured.
- ⬜ **BL-312** Ollama `/api/*`: `stream:False` is **hardcoded** (`ollama_compat.py:81,111`) while Ollama clients
  default to `stream:true`; all `options` except `stop` are dropped.
- ⬜ **BL-313** MCP: protocol is genuinely real (18 tests against a real subprocess) but **no UI path** —
  `mcp_stdio_servers` is not a schema field, so the schema-driven settings UI cannot render it. Only route:
  hand-edit `runtime_config.json`. Schema default `False`, live config `True` (disagreement).
- ⬜ **BL-314** Obsidian "bidirectional + conflict resolution" → vault→Layla is real+tested; Layla→vault is
  **learnings-export only** (edited notes can never return); "conflict resolution" = skip-or-clobber; the export
  happy path is **untested with no UI caller**.
- ⬜ **BL-315** Syncthing: REST code is real and correct but **0% executes in any test** — `_request`
  short-circuits before `urlopen` (`syncthing_sync.py:67`). Not bundled. **No UI to set the API key.**
- ⬜ **BL-316** Intent-driven setup: **16 features, not 15** (the test asserts `>= 13`, so drift is unpinned), and
  **`/setup/apply` writes config keys only**. Reproducible live: `/setup/state` lists `voice` while
  `/health/deps` reports `voice_stt: missing`. **The wizard prints "✓ configured" for things it never installed**
  — this is the direct cause of the dead TTS in BL-270.
- ⬜ **BL-317** German tutor: SM-2 is genuinely implemented and well-tested; the placement quiz is **self-rated**
  ("how much did you understand?"), not graded; A1 users auto-promote regardless of accuracy.
  *(NOTE: the auditor also claimed a "dead gate" hardcoding German off at `system_head_builder.py:886`. **That
  claim is FALSE — verified.** Line 886 is the initializer; :889 reads `german_mode_enabled` from config
  immediately after. Normal default-then-override; German mode is simply off by default, which is correct. Left
  here as a reminder that subagent findings get verified, not repeated.)*
- ⬜ **BL-318** Ctrl+K palette: an e2e test **does** exist (`tests/e2e_ui/test_ui_smoke.py:66`, CI job
  `ci.yml:147`) but is **deselected from the main job**, and it only asserts open+focus — **no test executes a
  command**. 38 commands, 0 stubs.

#### Backend-real-but-no-UI-path (found while verifying)

- ⬜ **BL-319** `repo_indexer.search_symbols` (working, 24 tests) — wired to no tool; `/missions/board` Kanban
  endpoint — no UI caller; `learn_communication_preference` — zero production callers, 3 of 4 hint branches
  unreachable; custom aspects — creatable, never selectable (BL-301); `/health/deps` — **zero UI consumers**, its
  only reader is a test (and it is exactly what would have exposed the dead TTS).

#### The seed (the operator's actual ask)

- ⬜ **BL-306** **Seed Layla with verified self-knowledge.** She currently **cannot know what she can do** — three
  self-knowledge surfaces exist and not one carries a capability list:
  (1) `.identity/self_model.md` — 51 lines of pure philosophy, **Lilith-only** (`prompt_builder.py:88`), and
  explicitly *not* RAG-indexed; (2) `docs/CAPABILITIES.md` — about the implementation *registry*
  (chromadb/faiss/qdrant), **docs-only, no runtime reader**; (3) `operating_manual.manual_for_prompt()` — literally
  named "for_prompt" and **called only by an API endpoint, never wired into a prompt**.
  That is why the "report your capabilities in a table" turn produced invented entries ("User management",
  "Encryption support", "Security auditing") — from the **lilith** aspect, i.e. the file *was* injected and told
  her who she is, not what she can do.
  **Design constraints (all load-bearing):**
  - **NOT via `ingest_text()`** — it chunks → embeds → **saves as `learnings`**, which would dump ~50 capability
    chunks into the learnings table, surface them in "Recent learnings"/"Things I remember", and make BL-264
    dramatically worse.
  - Git-tracked repo file → genuinely preloaded on clone, no ingestion step.
  - Read at prompt-build time, **gated to capability questions** (a 3B cannot afford it every turn; and
    `system_instructions` truncates from the TAIL on low tiers).
  - Available to **all six aspects**, not Lilith-only.
  - **Honest per-feature status** — including "not available on this machine" for TTS/STT/tree-sitter. A manifest
    that overstates is worse than no manifest: it turns hallucination into authoritative lying.
  - A **drift test** pinning the manifest to reality (tool count, endpoint existence, dep availability) so it
    cannot rot into the next generation of lies.
  - Should also serve BL-257 (no user tutorials) — one honest source, two consumers.

#### W14l — Reasoning/memory verification (2026-07-16): 9 of 15 downgraded

*Dominant failure mode of the prior table, in the auditor's words: **crediting stages and backends from their
docstrings and config keys rather than their call sites.** Four subsystems are real, tested, and unreachable.*

- ⬜ **BL-320** **The Knowledge-manager Ingest button is DEAD — reproduced directly.** `runKnowledgeIngest`
  (`settings-full.js:366`) reads `#ingest-path` and `#ingest-msg`; **neither element exists in index.html** —
  the panel has `#km-source` / `#km-label` (`:840-842`). So it reads null, bails at the empty-path guard, and
  writes its own error message to a null element: **nothing happens at all, not even the error.** It also POSTs
  to `/intelligence/kb/build/directory` (directory-only, live 400) — so the `"URL or folder path"` placeholder
  is wrong regardless: a URL could never work. **Knowledge cannot be added through the UI at all.** Supersedes
  the "no UI for ingest" note: the UI exists and is disconnected. (Related: BL-291's `#km-ingest-list` is also
  written by nothing.)
- ⬜ **BL-321** **`math_eval` is dead on arrival — every input raises.** Reproduced:
  `AttributeError: module 'ast' has no attribute 'Mul'` (it is `ast.Mult`). `layla/tools/impl/analysis.py:62,90`.
  Line 62 builds the tuple *before* parsing, so no input can succeed. **Real tool count: 197 working + 1 dead.**
  Root cause of it surviving: the 198-tool tests are purely structural and **never execute a tool**.
- ⬜ **BL-322** **The mission reaper moves crashed missions into exactly the state the worker ignores.** The
  reaper sets them to `'paused'`; `get_active_missions` (`missions_db.py:154`) selects
  `status IN ('running','pending')`. Its docstring promises "RESUMABLE from current_step" — half-delivered.
  **Auto-resume-on-boot does not exist for `layla_plans` at all** — no worker, a durable graveyard.
- ⬜ **BL-323** **`core/` pipeline is partly a facade.** *Validate* runs but `core/validator.py`'s `passed`
  verdict is **discarded** (`verification_engine.py:53-63`) — it can never fail a step, and no test imports it.
  *Observe* (`core/observer.py:20`) runs FTS + vector search **on every turn** into `state["_snapshot"]`, **which
  nothing ever reads** — pure waste on a CPU-bound box. *Plan* is not a stage (strings interpolated into a
  prompt). *Reflect* appends one canned sentence (`reasoning_handler.py:280-282`).
- ⬜ **BL-324** **Deliberation auto-detection is dead on the chat path.** Default is `"auto"`, not solo
  (`config_schema.py:145`), but `reasoning_handler.py:166` / `stream_handler.py:196` gate on
  `not in ("solo","auto")` — so `select_deliberation_mode()` never runs on chat. Also `/debate/modes` tells
  users council is a **"weighted vote"**; grep for `weight` finds only the comment. **No weighting exists** —
  user-facing false claim. (The 3-phase debate itself IS real: tribunal = 13 LLM calls.)
- ⬜ **BL-325** **Self-consistency is unreachable, not merely off.** `self_consistency_samples` is **absent from
  `config_schema.py`**, so `POST /settings` silently drops it (`runtime_safety.py:212`). Hand-edit + restart
  only, and triple-gated behind two other non-schema keys.
- ⬜ **BL-326** **Encryption-at-rest is real crypto on an unreachable path.** Fernet + keyring is sound, but it
  fires only when `privacy_level == "sensitive"`; the column defaults to `'public'` and **nothing in production
  ever passes "sensitive"** — it is in no router or request schema. Absent from `config_schema.py` yet
  `runtime_config.json:459` sets it **true** (on, and moot). **`ui/components/welcome.js:25` markets it to the
  user with no control anywhere.** No migration. Either wire it or stop advertising it.
- ⬜ **BL-327** **SM-2 is canonical math nobody calls.** `services/memory/spaced_repetition.py` has **zero
  production importers**; no scheduler drives it despite `background_intelligence.py:7` claiming otherwise. The
  `spaced_repetition_review` tool uses a **flat 24h interval**, bypassing `sm2()`. The only live SM-2 is a
  private duplicate inside German mode. (Journal is genuinely real, tested, UI-reachable.)
- ⬜ **BL-328** **LAN peer offload is dead code.** `run_completion_with_fallback`
  (`services/llm/inference_router.py:659`) is the only consumer of `cluster_offload_enabled` — **zero callers**
  repo-wide. Setting the flag changes nothing. **`litellm_enabled` is a decoy**: `inference_router.py:526`
  branches only on `inference_backend`, which is **absent from `EDITABLE_SCHEMA`**; this box runs
  `litellm_enabled: true` with litellm fully bypassed, and `docs/design/03-llm-and-reasoning.md:59` documents a
  gate that does not exist. Honest count: **3 live backends, 2 unwired**, plus an undeclared 6th (`onnx`).
- ⬜ **BL-329** **HyDE's checkbox is a lie on every CPU tier.** `hyde_enabled` IS a schema field and renders a
  control, but it is in `auto_tune.PROFILE_KEYS` and `apply_auto_tune` is authoritative — **ticking it is
  silently reverted on every CPU tier**. The only escape (`auto_tune_locked_keys`) has no UI control. (Corrects
  the prior mark twice over: `test_hyde_retrieval.py` DOES exist and passes.)
- ⬜ **BL-330** **NetworkX is not used at all** in the codex. `get_entity_graph` (`codex_db.py:166`) is
  hand-rolled BFS; the only `networkx` string in `layla/codex/` is a **stopword in a list**
  (`enricher.py:121`). Worse: `routers/codex.py` + `ui/components/codex.js` serve a **different, JSON-file
  codex** — the SQLite entity DB has **no router**. (The auto-linker genuinely is automatic.)
- ⬜ **BL-331** **GBNF bypasses the llama.cpp concurrency/KV hardening** — no lock, no `kv_cache_clear()`, on the
  **default-on** decision path. `inference_router.py:346` explicitly warns this is a native heap-corruption
  race. Highest-risk item in this section: a crash, not a wrong answer.
- ⬜ **BL-332** `vector_store.py:1019` — `light_k = min(cross_encoder_limit, 10)` then `results[:light_k]`;
  `limit=0` is meant to mean "skip rerank" but **slices all candidates to zero**. Latent only because
  `system_optimizer` is not wired into `load_config` — but `test_capability_routing.py:169` asserts `== 0` and
  `/health` advertises it.
- ⬜ **BL-333** **Two vacuous tests that would pass if the feature were deleted** (a whole class worth hunting):
  `test_completion.py:131` **copy-pastes the production `if` into the test body** — it tests Python's `if`
  statement. `test_workspace_index.py:17` asserts only that a dict has keys, so all-empty output passes (this is
  what hid BL-302). Also `test_agent_loop.py::test_tool_preflight_redirects_missing_args_to_reason` **fails**
  under `CI=true` — the fast path shadows preflight (→ BL-294).
- ⬜ **BL-334** **Silent degradation the UI reports as healthy.** chroma→sqlite fallback works but `/health`
  mislabels it **`"disabled"`**; flashrank→torch CrossEncoder; trafilatura/bs4→regex tag-strip;
  tree-sitter→nothing; HyDE force-off. `knowledge_index_ready` is decoration — written once at `main.py:85-86`,
  never again, and `test_health_endpoint.py:26` locks in the vacuum with `is None or isinstance(...)`.

#### W14m — Class sweeps (2026-07-16): generalizing each confirmed defect

*Every prior finding was a single INSTANCE. These sweeps ask "where else?" for each class. Method: mechanical
(script every JS `getElementById` / `fetch` against the real DOM + the live OpenAPI route table), then verify
each hit by hand — a pattern match is not proof.*

**SWEEP RESULT — dead element references: 10 hits / 5 distinct broken features.**
**SWEEP RESULT — UI→endpoint: CLEAN.** All 340 live routes; the 3 apparent misses were my own regex capturing
the literal prefix before a string concat (`/operator/quiz/stage/0` -> 200, `/learn/` -> 422,
`/pairing/{instance_id}/permissions` -> PATCH exists). The UI→API layer is sound — recorded so nobody re-audits it.

- ⬜ **BL-335** **`saveAppearanceLite` is dead at FOUR independent layers and lies to the user.** The most
  complete specimen of this codebase's disease:
  1. the button is REAL and correctly registered — "Save appearance & lite" (`index.html:1237`,
     `main.js:389`);
  2. it reads `#app-font-size` / `#app-anim-level` (`settings-full.js:352-353`) — **neither element exists
     anywhere**;
  3. it POSTs `ui_font_size` / `ui_animation_level` — **neither key is in `config_schema.py`**, so
     `POST /settings` **silently drops them** (`runtime_safety.py:212`);
  4. **nothing reads either key** — zero consumers in any .py/.js/.css.
  It then toasts **"Appearance saved"** regardless. **This is the TEXT SIZE accessibility feature.** Corrects
  BL-274: the a11y audit called text size "ZERO implementation" because it grepped
  `font-scale|text-size|textScale` and missed `ui_font_size`. It is not zero — it is a save path with no
  control, no schema, and no consumer.
- ⬜ **BL-336** **The "server unreachable" banner has never once appeared.** `app.js:837` appends the health
  banner to `#chat-messages`; the real container is **`#chat`** (`index.html:379`). `if (chatEl)` swallows it.
  Worse: the 5-second `/health` poll (`app.js:842-864`) still runs for 2 minutes and writes its result to
  `getElementById('layla-health-banner')` — a banner that was never inserted — so it is **pure wasted work on a
  CPU-bound box** AND the user gets no warning when the server dies.
- ⬜ **BL-337** **Phone access is entirely dead.** `loadPhoneAccess` (`settings-full.js:441`) has **zero
  callers**, and `#phone-access-url` / `#phone-access-status` exist nowhere. A whole feature, unreachable.
- *(Already tracked: `#ingest-path`/`#ingest-msg` -> BL-320; `#onboarding-text`/`-next`/`-done` -> BL-249, the
  dead 3-step tour.)*

**The pattern across all five:** every one is guarded by `if (el)` or `(getElementById(x) || {})`, so a missing
element produces **silence, not an error**. Defensive null-guarding is exactly what let five features die
invisibly. Any fix here should consider failing loudly in dev instead.

#### W14n — THE HEADLINE (2026-07-16): the learning pipeline does not run for normal use

- 🔴 **BL-338** **With default settings, the full finalizer runs on approximately ZERO UI turns.** This
  supersedes and enlarges BL-294. Independently verified:
  - `finalize_run_state` gates ALL of its work on `if state.get("status") == "finished"` (`run_finalizer.py:34`).
  - `reasoning_handler.py:58-65` sets `status = "stream_pending"` and **returns before the answer exists**
    whenever `stream_final=True`.
  - The UI ships **streaming ON by default** (`index.html:610` `<input id="stream-toggle" checked>`).
  So the split is NOT "orchestrated vs fast-path" — it is **`stream=false` vs everything else**. The finalizer
  is called at `agent_loop.py:921` with a state that has no answer in it, so L34-157 is skipped on the
  orchestrated STREAMING path too. **Unchecking "Stream responses" is currently the only way the UI runs the
  learning pipeline at all.**

  **Blast radius (measured, 24 realistic messages through the live gate):** 17/24 take the stream fast-path
  (path A, zero side effects) — including `write a python script...`, `fix the bug in the auth module`,
  `what is a monad`, `make a plan for the release`. The remaining 7 hit ORCH-ST, which runs 5 of 20 effects.
  `is_self_contained_question` ends in a bare `return True` (`response_builder.py:181`) — it is a **denylist,
  not an allowlist**, so anything without a path/filename or a hard tool signal is "self-contained".

  **Effectively dead for normal use** (no live write path from conversation):
  1. **Learning extraction** — the learnings table can only grow from non-stream callers and the scheduler.
     *This explains the operator's 32 junk learnings: they are ALL residue from non-stream benchmark runs.
     Real chat has never written one.*
  2. **Learning reinforcement / decay** (+ chroma `success_score`) — recall ranking never gets feedback, so
     retrieval quality is frozen.
  3. **Outcome evaluation -> `record_strategy_stat`** — the "mandatory outcome recording for feedback loop" is
     chat-blind.
  4. **Fact distillation** (`run_distill_after_outcome`) — never triggers from conversation.
  5. **Emotional presence / mood** — **BL-190 claimed to fix "mood stayed permanently neutral"; the fix landed
     INSIDE the block that does not run. Mood is still permanently neutral.**
  6. **Conversation entity extraction** — the codex/wiki graph gets nothing from chat.
  7. **Skill acquisition** — **BL-238's `learned_skills` still cannot fill**; a >=3-tool streamed run mints
     nothing.
  8. **Routing telemetry** — blind to exactly the turns whose routing is in question.
  9. **Model-outcome telemetry** — `log_model_outcome` always receives `score=None` on any streamed turn, so
     model-quality routing trains on the non-stream minority only.
  10. **Explainability (BL-237)** and **answer quality (BL-100/102)** — never populate on streamed turns.
  11. **Golden examples / reflection engine** — chat-unreachable.
  12. **Maturity XP / relationship "active days"** — undercount by the path-A fraction (~70% of turns).

  **Irony worth keeping:** `/api/chat` + `/api/generate` force `"stream": False` (`ollama_compat.py:81,110`) and
  `/v1` non-stream reaches `autonomous_run(stream_final=False)` -> **full finalizer**. Ollama clients get more
  learning than Layla's own UI. `/v1` STREAMING (`openai_compat.py:293-382`) never calls `autonomous_run` at
  all, so everything above is dead for OpenAI-SDK streaming clients too.

  **Root cause is one line + a missing callback:** `reasoning_handler.py:58` returns `stream_pending` before the
  answer exists, and nothing ever calls back into the finalizer once the router has finished streaming tokens.
  A fix must either (a) finalize AFTER the stream completes, router-side, with the assembled text and a
  synthetic `reason` step, or (b) move the `finished`-gated block behind an "the answer now exists" callback
  instead of a status check. **Do not "fix" this by disabling streaming.**

  **What the fast paths DO run inline** (they are not no-ops — do not double-implement): path A does output
  polish + junk strip + conversation persist + title synth + **`_mem_receipt`/`capture_identity_from_turn`**
  (`agent.py:984`) + artifact extraction. Path B does conv history + persist + title synth (no `_mem_receipt`).
  Path C re-runs `check_output` + persist + title synth. Multi-agent subtasks DO finalize, but attributed to the
  subtask goal, not the user's turn.

  **Corrections to the earlier brief (BL-294), both verified:** `record_practice` is NOT finalizer collateral —
  `finalize_run_state` never calls it; its only callers are `scheduler/jobs.py:342` and `routers/study.py:419`.
  It was never wired to conversation turns at all — a separate, wider gap (BL-267). And personality
  `record_interaction` sits OUTSIDE the `finished` block, so drift DOES record on ORCH-ST; it is dead only on
  paths A/B/C.

- ⬜ **BL-339** Path B (trivial quick reply) is checked **before** the `if stream:` branch, so an
  SSE-expecting client gets a JSON body. Verified live: `POST /agent {"message":"ok","stream":true}` returns
  `content-type: application/json`, `"status":"fast_path"`. Content-type contract violation.

#### W14o — Why 2,900 green tests caught none of this

*The diagnosis, in the auditor's words: **"strong behavioral coverage of pure functions, text-matching at every
wiring seam."** Every shipped dead feature — TTS, symbol search, ingest button, study preset, capability scores
— died at a SEAM, which is precisely where the assertions turn into grep. **The 2,900 green tests are measuring
the parts that were never at risk.***

*Empirical, not inferred: the tests guarding the known-dead features were RUN — **30 passed, 2 skipped** —
while the same venv proved `search_symbols` returns `{'ok':True,'matches':[],'count':0}`, `math_eval` raises
`AttributeError`, and `check_dignity('hello')` returns `''`. A second cluster: **89 passed** for features whose
deps are not installed at all.*

- 🔴 **BL-340** **119 AST-confirmed fully-vacuous test functions** (conservative lower bound: every assertion in
  the function is incapable of failing, after excluding `pytest.raises`/`assert_called*`/Playwright `expect()`
  as genuine). ~114 further key-presence-only candidates need manual triage. Scanner kept at
  `scratchpad/vac.py`.
- 🔴 **BL-341** **THE TEST VENV IS NOT THE APP VENV — tests certify features that cannot run in production.**
  Verified directly: `cryptography` and `nbformat` are **present in `.venv-test` and MISSING from `.venv`**
  (the venv that runs the app). The encryption tests are `skipif(not enc.available())` — which is TRUE in the
  test venv — so they **run and pass, certifying encryption-at-rest**, while production silently never
  encrypts. **The skip is keyed to the wrong environment. No test can ever catch this.** Independently
  corroborates BL-326 from a second direction: encryption is dead for two unrelated reasons.
  Fix: gate optional-dep skips on the RUNTIME venv, or make CI assert the two environments agree on every
  optional dep.
- 🔴 **BL-342** **The UI contract layer is not vacuous — it is ABSENT.** `tests/e2e_ui` is *well written* (real
  Playwright `expect()` assertions) but **collects 0 tests** — playwright is not installed — and CI deselects
  the marker anyway (46 deselected). **This is why the dead ingest button and dead study preset shipped.**
  Same shape for voice: `voice_smoke` is deselected in PR CI and line 32 `pytest.skip`s when TTS is
  unavailable — **the dead TTS skipped itself into production.** A skip that fires because the feature is
  broken is not a skip, it is a silent pass.
- ⬜ **BL-343** **My own guards are in the top 10 worst — verified by executing the reverted bug against them:**
  - `test_learning_bleed_guard.py:86-89` (written 2026-07-16 to prevent the bleed regression): a reverted
    `learn_text = final_text` — sanitizer removed, exact bug reintroduced — **PASSES all four asserts**. It
    checks the variable NAME, not that sanitization happens. **A grep wearing a guard's clothing.**
  - `test_data_integrity_writes.py:12,19,27`: source-match, so moving `os.fsync` to AFTER `os.replace` passes
    — **and that inversion IS the bug fsync-before-replace exists to prevent** (config/chat truncation on
    power loss).
  - `test_round1_loop_fixes.py:50`: claims "each now has a production caller"; the bare `import` line satisfies
    all four security loggers. **Delete every call site → still green → audit trail silently empty.**
  - `test_ui_backend_contract.py:44`: self-titled "WATERTIGHT"; greps the whole module, so it passes if
    `reasoning_tree_summary` appears **in a comment**. Field computed-but-never-sent → green.
  Same disease at the meta level: I verified the artifact, not the behavior, then named the file "watertight".
- ⬜ **BL-344** The worst pre-existing offenders:
  - `test_shell_approval_gate.py` (whole file) — **deleting the shell approval block entirely would still
    pass.** `"not ctx.allow_run" in SRC` is satisfied by 3 OTHER gates (lines 339/379/637); shell's is 582.
    Line 46 re-implements the predicate in the test body. Its own docstring admits: *"They never invoke
    `_handle_shell`."* This guards the control that BL-296 identified as the ONLY real protection on the
    sandbox.
  - `test_smoke_comprehensive.py:344` — **permanently skips on a stale path**
    (`services/inference_router.py` moved to `services/llm/`). Zero coverage, reads as green.
  - `test_smoke_comprehensive.py:359` — FTS5 escape guard passes on an unrelated `errors="replace"` elsewhere
    in the file. Delete the real escape → green → FTS5 injection.
  - `test_capability_evolution.py:19-33` — **the frozen-scores root cause**: sets `cfg={"vector_search":
    "chromadb"}` then asserts the registry echoes `"chromadb"` back. Asserts a value the test just set.
  - `test_graph_reasoning.py` — NEW, same shape as the symbol-search hider: `spacy` missing →
    `extract_entities` returns `[]` → test asserts `isinstance(list)` → green.
  - `test_edge_cases.py:64-84` — 14 parametrized tests of Python's own `str()` and `html.escape`; line 61
    `except Exception: pass` swallows any `save_learning` crash.
  - `test_llm_lock_safety.py` — guards NATIVE HEAP CORRUPTION (BL-331) via a string match on a lock-ordering
    property.
- ⬜ **BL-345** **A live bug the tests are hiding right now:** `get_expanded_context("nonexistent query")`
  returns polluted graph nodes straight into prompt context — `Knowledge graph associations: NOT; s the
  problem?\nLayla: You; CASSANDRA; ERIS; CORRECTED; ONLY; EARNED; TITLE; REFUSED; ...` — including leaked test
  data (`"REPAIR TEST: prefer tea over coffee"`) in the operator's real graph DB. The guarding test asserts
  only `isinstance(result, str)`. Related to the BL-338 bleed cluster; the graph purge of 2026-07-16 removed 6
  bleed nodes but this shows more junk remains.

**The rule this implies for every W14 fix:** a source-grep is NOT a regression guard. If a test cannot fail when
the wiring is removed, it is documentation. Guards must EXECUTE the seam — call the function and assert the
observable effect (as `test_capability_manifest.py` does: it asserts manifest CONTENT and real prompt-injection
behaviour including index position, which is why the auditor explicitly excluded it). Simple is not vacuous;
un-failable is.

#### W14p — The tool registry proves nothing (2026-07-16)

- 🔴 **BL-346** **153 of 198 tools (77%) are invoked by NO test; 110 are never even mentioned.** Only ~45 are
  genuinely exercised, and that is generous (name-collision false positives — `shell` looked covered until the
  auditor checked by hand and found every hit was a string literal passed to a *gate/parser*, not the tool).
  **Routes have the same hole: 223/367 (61%) are never called**, including all of `/goals`, `/decisions`,
  `/feedback`, `/automation/rules`, and 14 `/intelligence/*`.
  Worst-covered domains: search 6/7 uninvoked (`search_codebase`, `grep_code`, `ddg_search`), math/data 6/7
  (**`math_eval`**, `sympy_solve`, `sql_query`), memory 7/9, file ops 11/18, shell/exec 5/7 (**`shell`**), git
  5/8.

  **The mechanism — why invocation is the ONLY possible detection.** Two structural facts, both verified:
  1. every tool is wrapped by `_wrap_tool_with_metrics` into `(*args, **kwargs)` (`registry.py:103`), so
     `inspect.signature` is useless on all 198;
  2. the registry meta carries **no parameter schema** — keys are only
     `fn, dangerous, require_approval, risk_level, category, description`.
  There is no static contract to check. **Registration proves only that a name maps to a callable.**
  `test_registered_tools_count.py:23` asserts `len(TOOLS)==198` and passes while `math_eval` raises
  `AttributeError` on every input (BL-321). `search_codebase` (BL-302, returns `ok:true` with 0 matches) is the
  same pattern — also never invoked.

  **Honest calibration (the auditor's, kept):** the safe read-only subset of never-invoked tools was
  smoke-invoked and **`math_eval` was the only hard crash** — the "Outside sandbox"/`TypeError` results were
  sandbox guards working correctly plus arg-guessing. So **153 is EXPOSURE, not 153 broken tools.** But nothing
  distinguishes working from broken except running them.

  **Highest-leverage fix in the whole backlog:** add a parameter schema to the tool meta, then one parametrized
  smoke test over `registry.TOOLS` invoking each tool with a schema-valid minimal input and asserting it does
  not raise. **That single test would have caught `math_eval` on day one and closes all 153 at once.**

- ⬜ **BL-347** More structural-only guards (registered != working): `test_phase6_autonomy_engine.py:376-396`
  (5x `'/mission/{id}/cancel' in paths` — cancel registered but the worker keeps running; a handler that
  `return None`s still passes); `test_observability.py:168` (`/metrics` registered but **500s** when
  `PROMETHEUS_AVAILABLE=False`; nothing HTTP-calls it); `test_vision.py:69` (asserts the registered fn is
  callable — but it is a *different wrapper* than the one other tests exercise, so its `inside_sandbox()`
  guard could invert into an arbitrary-path image read and this still passes); `test_tool_dispatch.py:228-250`
  (fake registry means **zero signature conformance**: rename the real param `repo` to `path` and it stays
  green while production raises TypeError).

- ✅ **GOOD NEWS, recorded so it is not re-audited:** the **mocked-to-death cluster came back CLEAN.**
  `test_ws_manager`, `test_cancellation`, `test_shared_state_safety`, `test_architecture_boundaries`,
  `test_phase7_knowledge_loading` — every mock sits on a WebSocket/DB/LLM/clock boundary while real logic runs.
  `test_shared_state_safety.py:427` was called the strongest test in the suite. **Mocking discipline is
  genuinely good; the hole is structural, not mock abuse.** `test_startup_imports.py` and
  `test_smoke_comprehensive.py:47-88` are legitimate import smokes — catching `ModuleNotFoundError` at startup
  IS the point.

- ✅ **BL-348 (FIXED 2026-07-16)** — my own manifest guard asserted `"197" in core`, i.e. **fixing `math_eval`
  would have FAILED the test**: the bug was encoded as expected behaviour by the guard meant to protect
  against it. Now derived: `expected = len(TOOLS) - len(KNOWN_BROKEN_TOOLS)`, computed at test time, plus
  `test_known_broken_tools_are_still_actually_broken` which **executes** `math_eval` and fails loudly if it
  ever starts working (telling you to update the manifest). Fix a tool, drop it from the set, the count rises,
  and the manifest must follow. The guard now rewards repair instead of punishing it.

#### W14q — Unwired-function sweep (2026-07-16): the class, mapped

*Method: inverted identifier index — 1,706 public defs in `services/`+`layla/`+`core/` cross-referenced against
every .py/.js/.json/.md/.html, categorized test/init/doc/ui/prod → 168 zero-prod-reference candidates, each
verified by hand for dynamic dispatch. The index reproduced the known instances unprompted, which validated it.*

**THREE CORRECTIONS TO MY OWN BRIEF (verified — record so they are not repeated):**
1. `layla/memory/repo_indexer.py` **does not exist**; it is `services/workspace/repo_indexer.py`. The shape was
   right, the path wrong — and it is worse than I described (BL-355).
2. **Only 2 of the 5 "dead config keys" I listed are bugs.** `self_consistency_samples`, `mcp_stdio_servers` and
   `inference_backend` are read by prod, shipped in `runtime_config.json`, and never POSTed by the UI — they are
   deliberate file-only advanced keys and the schema docstring says so. **No UI lies about them.** Only
   `ui_font_size`/`ui_animation_level` (BL-335) are real.
3. **Three suspects CLEARED:** `prompt_builder.build_static`/`tool_injection` (self-declared test façade; tool
   descriptions DO reach the model), `filter_batch_tools` (a *stricter* inline filter is live at
   `decision_loop.py:399-410`), `get_tool_preferences` (accessor orphaned but `build_behavior_block` reads the
   dict directly — aspect tool bias works; `docs/audit/subsystem_audit.md:61` is stale).

##### TIER 1 — dead subsystems the UI advertises

- 🔴 **BL-349** **LAN clustering: a user can enable it, pair two machines, see both peers online, and never move
  one unit of work.** `ClusterNetwork.submit_task` (`cluster_network.py:420`), `get_task_status:435`,
  `cancel_remote_task:445` — **zero callers**. `TaskQueue.submit` (`work_unit.py:166`) is the only enqueue path
  and its sole prod caller is the *receiving* endpoint (`routers/cluster.py:207`) — **the loop is closed with no
  entry point**. `DroneWorker._work_loop` (started for real, `main.py:536`) polls a permanently empty queue every
  5s **forever**. Shipped UI: Enable-Clustering toggle, pairing flow, peer list, live queue-stats — **translated
  into all 11 locales**. Also makes the `inference_offload` pairing permission grantable but inert. Supersedes
  BL-328's narrower finding.
- 🔴 **BL-350** **Spaced repetition is advertised IN CHAT and is entirely dead.**
  `ui/components/chat-render.js:385` lists **"Spaced repetition study sessions"** in Layla's own capability
  list. Zero prod importers for ANY public symbol in `services/memory/spaced_repetition.py` (`sm2`,
  `run_study_session:224`, `review_item`, `get_due_items`) — ~60 green assertions across two files, fully
  unreachable. Three rivals are wired instead: the flat-24h tool, a research "study" scheduler that never
  touches SRS, and **a copy-pasted SM-2 clone at `german_mode.py:379`** that is live and serves the only real
  flashcard UI. Supersedes BL-327.
- ⬜ **BL-351** **Skill packs install successfully and can never run.** `run_entry_point`
  (`skill_sandbox.py:82`) — venv resolution, path-escape guard, env allowlist, timeout, 10 tests incl. a real
  subprocess — **zero non-test callers**. The whole install lifecycle IS live, and `validate_manifest`
  *requires* a non-empty `entry_point`. `docs/SKILL_PACKS.md:29,125` promises "a Python entry point that Layla
  executes in a sandboxed venv". Author per the docs → installs → silently never runs.
- ⬜ **BL-352** **`GET`/`POST /settings/appearance` exists, purpose-built for BL-335 (`editable_only=False`,
  accepts non-schema UI keys) — and has ZERO callers.** The right door exists; nobody knocks. Fold into BL-335.

##### TIER 2 — safety/correctness verdicts computed then discarded

- 🔴 **BL-353** **Fabrication verify-before-mutate is structurally unreachable — the highest-impact discard
  found.** `decision_policy.py:220` gates on `if th.forbidden_tools:`, but `policy_hint_from_toolchain`
  (`toolchain_awareness.py:37-45`) has three return paths and **none ever sets `forbidden_tools`** — the only
  verdict it carries is `require_verify_before_mutate=True`. The guard is never true; `merge_policy_caps` at
  :221 is dead code. "generate gcode from this dxf" is *meant* to force verify-before-mutate on
  `gcode_post`/`machine_run` (the module's own DAG marks them `risk=high`). **It never does.** Compounding: the
  block converting that flag into a real ban sits at :206-214, ABOVE the merge — so even fixing the condition
  arrives a tick late. **Zero tests.** Callee sets one field, caller inspects another.
- ⬜ **BL-354** More discarded verdicts: **research promotion gate** — `get_promotable_research_learnings`
  (`research_intelligence.py:400`) zero callers; `study_service.py:70,76` saves research output at
  **confidence=0.9 with no filter**, its docstring's "do NOT store speculative output" unenforced ·
  **grounding/abstention** — `should_abstain` (`grounding.py:148`) zero prod callers,
  `answer_assessment.py:41` re-derives it inline, result lands in the unread `answer_quality`; off at THREE
  layers (`grounding_enabled:false`, `mode:"flag"`, and flag mode can never set abstain) ·
  **validation matrix** — `evaluate_validation_matrix` (125 lines, 5 dimensions, **on by default, runs every
  turn**); `critical_pass` appears only at its definition, its packing, and one test assertion — policy caps
  still run on the fuzzy heuristic it was built to complement · **`pkg_policy_strict_enabled`** — inert;
  nothing writes the `pkg_policy` key it reads · **dignity level-3 aspect override** — `dignity_engine.py:280`
  sets `suggest_aspect_override="lilith"`, caller returns only `boundary_prompt` (:311); the prompt *says* "You
  are Lilith now" so intent ships as an instruction, not a switch.

##### TIER 3 — write-only state / wasted compute (this box is CPU-bound)

- 🔴 **BL-355** **`repo_indexer` is a write-only index.** A full SQLite structural index of the user's repo is
  built **at every startup** (`main.py:339`) **and on a schedule** (`jobs.py:291`) — and **all 6 query APIs**
  (`search_symbols:399`, `get_symbol_context:457`, `get_callers_of:425`…) have **zero readers**. `search_codebase`
  routes to a different module (`code_intelligence.py`, ChromaDB) — the broken one (BL-302). This is the
  duplicate triangle, corrected: the working index is built at cost and never queried; the queried one is dead.
  **`scripts/check_wiring.py:17` passes** because the three *writers* satisfy it.
- ⬜ **BL-356** Per-turn waste: **`routing_telemetry`** — `migrate()` + a 12-column INSERT (goal string up to
  2000 chars) + `commit()` **every turn**, retained 90 days; `get_recent_route_telemetry:55` has zero callers,
  **not even a test** · **`person_dossier`** — `update_person_mention` writes on **every exchange**; the entire
  read chain (`get_dossier_for_prompt:183` → `build_dossier` → `summary_for_prompt`) is a closed dead loop ·
  **`impact_estimate`/`effort_estimate`** — the prompt *instructs the model to emit them* and GBNF parses them;
  **nothing reads them** (wasted prompt AND generation tokens per decision iteration) · **`tool_calls`** —
  SHA-256 (`args_hash`) computed per tool call for dedup nobody performs; 4 write-only columns ·
  **`steps_taken`** — a full list copy of `steps` every turn, doubling the serialized payload.
- ⬜ **BL-357** **Silent work loss under load.** `decision_loop.py:526,533` builds a full resume `checkpoint` and
  sets `paused_high_load`; **nothing reads either**, and `routers/agent.py:1489` has no branch for that status —
  it falls through to the generic **"Ready. What do you need?"**. The user gets a nonsense reply while the data
  that would have saved the turn is discarded. Realistic on this box.
- ⬜ **BL-358** Diagnostics that cannot work: **`token_throughput` is READ** (`system_optimizer.py:51,210` →
  `routers/system.py:299` + system_doctor) **and NEVER WRITTEN** — guarded by `if count > 0`, so it is silently
  always absent. **Layla can never report her token throughput — the one number that matters most on this box.**
  · **`MetricsCollector`** (`services/observability/metrics.py`) — `record_timing`/`increment_counter`/
  `record_gauge` have **zero callers repo-wide including tests**, yet `routers/metrics.py:52` reads it:
  `GET /metrics/observability` returns empty counters **permanently, by construction**. Contained by luck — the
  UI polls `/metrics/summary`, backed by the genuinely-fed `prom_metrics`.

##### TIER 4 — duplicates where the worse implementation is wired

- ⬜ **BL-359** **`services/retrieval/reranker.py` has NO production importers at all** — the entire
  FlashRank→CrossEncoder→BM25 ladder (BL-103's "potato-path default") is dead; the live path is
  `layla/memory/vector_store_rerank.py`. **`capabilities/registry.py:72-84` still advertises `reranker`
  capabilities pointing at the dead module.**
- ⬜ **BL-360** **`clear_blocker` (`working_memory.py:139`) has no caller** while its pair `add_blocker` is live
  from chat extraction and `format_for_prompt` is live at `system_head_builder.py:1005`. Blockers can only be
  cleared wholesale → **stale blockers keep entering the prompt forever.**
- ⬜ **BL-361** Wired-worse rivals: **`build_retrieved_context_with_ids`** orphaned while the live
  `build_retrieved_context` **throws the learning IDs away** — then `reasoning_handler.py:331` passes a single
  opaque blob to `attribute_response`, which **lexically re-matches sentences to guess provenance it already
  had exactly** (and the docstring's "used for learning reinforcement" is false — nothing reinforces) ·
  **`crawl_urls`** — the wired `crawl_site` is a hand-rolled **serial** trafilatura BFS that never touches
  `web_crawler`, silently forgoing Firecrawl/crawl4ai (users who install Firecrawl get it for single URLs and
  not for site crawls) · **`get_aspect_routing_params`** zero callers → **`temperature_boost` and
  `reasoning_mode` in `aspect_model_overrides` are dead config keys** (`preferred_model` works, but via
  `llm_gateway.py:369` reaching past the accessor into private `_resolve_aspect_model()`) ·
  **`retrieve_high_confidence_memory`** — docstring says the planner seeds plan-steps with it; **the 0.75
  confidence filter does not exist in production** · **`model_manager.select_best_model`** bypassed —
  `main.py:162` calls `recommend_from_hardware` directly · **`coordinator.py`** — `run_parallel_subtasks`,
  `spawn_subtasks`, `merge_outputs`, `resume_from_task` are **REAL implementations** (correcting the old
  "fake placeholders" note), shadowed by `multi_agent` + `GraphExecutor`.
- ⬜ **BL-362** Inert knobs/features: `long_horizon_planner` (well-tested, **no producer** — nothing calls
  `save_checkpoint`, so `GET /missions/horizon` returns `{"plans": []}` forever) · `kb_use_graphrag` (sole
  reader orphaned → flag has no effect) · `suggest_optimization` (the one fn that would switch models on
  latency; never consulted) · `get_reliable_tools` + `tool_health_snapshot` (docstrings claim "used by
  planner/routing" — not) · `run_experience_replay` **is scheduled** but its result is discarded into a log
  line (the source admits it) · `auto_session_recap` (no trigger) · `mission_chains` table (entirely dead) ·
  **`verification_queue.user_answer` discards the user's actual correction text — the most valuable signal in
  that loop.**

##### Why this class survives here — three mechanisms (the real lesson)

1. **`scripts/check_wiring.py` checks module IMPORTS, not data-flow reachability.** It passes on `repo_indexer`
   (satisfied by the writers), on `metrics.py` (satisfied by the reader), and on every duplicate pair. **The
   guard built to catch exactly this class is structurally blind to it.**
2. **The test became the production caller.** `tests/test_cluster_e2e.py` POSTs to `/cluster/task/submit` over
   HTTP — exercising the receive path perfectly while masking that **no shipping code ever makes that request**.
   Any heuristic trusting "has e2e coverage" as a liveness signal misses the whole class.
3. **Tests are frequently the ONLY reader** (`answer_quality`, `update_health`, `user_answer`, `critical_pass`).
   **A green suite actively masks these.** Inversely, the single highest-cost item — `routing_telemetry`, one
   INSERT+commit per turn — has **no test at all**; nothing would notice if it were deleted.

**Verified NOT bugs (do not action):** `_legacy_observability` (18/27 live) · `provider_health` (real circuit
breaker) · `session_context` (pruner is scheduled) · `request_tracer` · watchdog `on_created`/`on_modified` and
zeroconf `add_service`/`update_service`/`remove_service` (**genuine framework callbacks — index false
positives**) · `retrieve_learnings`/`retrieve_graph_context` (reached via intra-file `ThreadPoolExecutor.submit`)
· `cached_retrieve` · all `reset_*`/`clear_*` test fixtures.

---

## W15 — Architecture review: build-vs-adopt (2026-07-16)

*Four parallel reviews (infra · UI+testing · memory/learning · agent/tools), each required to design the correct
thing, price a REAL named OSS option (license, weight, CPU cost, offline viability on Py3.12 Windows), and
compare fairly. Constraints given: local-first/offline, CPU-only ~16.9GB no GPU, license matters (kokoro-GPL
already broke CI), and "adding a library is NOT free — 10 optional deps are already installed-nowhere and
silently dead."*

**THE THROUGH-LINE (the infra reviewer's synthesis, and the best sentence written about this codebase):**
> *"This codebase's defect isn't under-building, it's **callee sets one field, caller inspects another** —
> repeated at every scale, from `submit_task`/`queue.submit` (a 4,600-LOC courier with no depot) down to
> `record_token_throughput`/`get_token_usage` (5 lines apart, never introduced). The fix is rarely a library."*

**Headline: of 9 verdicts so far, ZERO are "adopt a framework."** Three are CUT, five are FIX-IN-PLACE, one is
a ~15-line wire. The two genuine wires in the infra tier total **about fifteen lines**.

### Corrections to MY OWN backlog (verified — 4 in Layla's favour)

- ❌ **BL-342 is WRONG.** I claimed CI deselects `e2e_ui`. **It does not.** `.github/workflows/ci.yml:147`
  defines a separate **ungated** `e2e-ui` job that installs playwright + chromium and runs 9 tests on every
  push/PR. The `-m "not e2e_ui"` deselect applies only to the *unit* job — which is correct, it has no browser.
  "Collects zero tests" is a **local** artifact of `.venv-test` lacking playwright. The Playwright layer is
  present, ungated, and good. **It is under-covered, not absent.**
- ❌ **BL-347 is WRONG.** Verified by execution: with `PROMETHEUS_AVAILABLE=False`, `/metrics` returns JSON and
  does not 500. `prom_metrics.py` ships a complete `_FallbackCounter`/`_FallbackHistogram`/`_FallbackGauge`.
  **The fallback IS the production path and always has been** — `prometheus_client` is in neither venv.
- ⚠️ **BL-310 misdiagnosed.** Interval jobs are re-registered from config on every boot, so **MemoryJobStore is
  CORRECT**; a persistent jobstore would resurrect stale jobs and drag in SQLAlchemy (~8MB, uninstalled). And
  the reaper→`paused` is a **deliberate, defensible choice** (auto-resuming a mission that crashed the app is
  how you build a crash loop) — the real defect is that the docs say "restart-recoverable" and the UI never
  tells the operator that N missions sit paused awaiting a click.
- ⚠️ **BL-341 UNDERSTATED, and worse than reported.** `cryptography` is declared in **NO extra in
  pyproject.toml** — not core, not dev, not `[all]` — with zero reverse-deps in `.venv-test`. **It was
  hand-installed to turn `skipif(not enc.available())` green.** So `pip install layla[all]` does not give you
  encryption: **encryption-at-rest is unshippable by construction, in every supported install path.** Verified.
  Also `prometheus_client` is declared in `[core]` and **missing from BOTH venvs** — so neither venv was built
  from `[core]`, and nobody knows which extra any environment came from.

### The deepest artifact found this session

- ⬜ **BL-363** **The test suite saw `header{display:none}`, documented it, and routed around it.**
  `tests/e2e_ui/test_ui_smoke.py:33-36`: *"the live UI is the `.topbar` inside `.main-area`; the legacy
  `<header>` is display:none ("Preserved IDs for JS compatibility"), so tests must target the visible shell."*
  Playwright's `to_be_visible` **would have caught BL-246** — the one line that kills Global search and Aspect
  lock and orphans the palette button. Instead the test author looked directly at it, described it accurately,
  called it "legacy", and adapted. **RULE: when a test comment explains why it avoids the live UI, that comment
  is a defect report.** Grep the suite for the rest of them.

### Verdicts — infra tier

- ⬜ **BL-364 CUT LAN clustering** (−4,600 LOC: `services/cluster/` 3,822 + `routers/cluster.py` 487 +
  `cluster.js` 269 + `pairing.js`, the 11 locale key-sets, `test_cluster_*`, 2 scheduler jobs, the
  `inference_offload` permission). **The physics is decisive, not the wiring:** only the hidden state crosses
  the wire (~few kB), so distributed inference is never bandwidth-bound — it is **RTT × sync-count** bound, and
  your gigabit is irrelevant. **Distributed inference is how you run a 70B *at all*, accepting ~2× worse decode
  as the price of possibility. It has never been a speedup for a model that fits** — and your 3B-Q4 (~2GB) fits
  in 16.9GB with vast headroom. Evidence: llama.cpp RPC's own README says *"fragile and insecure, never run on
  an open network"*, carries a known unauth RCE, benchmarks **91.8 → 52.7 tok/s** on a fitting model, and its
  Windows `rpc-server.exe` has crashed on warmup since b8233. exo = **macOS/Metal-only, no Windows**. petals =
  last release Sept 2023, built for 176B internet swarms. ray = orchestration, not a decode kernel.
  distributed-llama is the honest counterexample (2× Pi 4B: 1.37 → 2.04 tok/s, +49%) — **but that works only
  because a Pi token takes 729ms against ~25ms network (3% overhead); on a desktop CPU (~50-100ms/token) the
  same sync is 25-50% overhead and the win inverts. The Pi speedup exists because the Pi is slow enough to hide
  the network.**
  **Fairness:** Layla's design was *smarter* than llama.cpp RPC — `task_dispatcher.py` dispatches whole
  `WorkUnit`s (job offload, latency-tolerant) rather than layer splits. That is the one architecture with real
  upside. It was **never merged** (lives only in a stale worktree + `build/lib/`). **Delete the UI, do not
  disable it — a "coming soon" toggle is the same lie with a longer fuse.** `node_sync.py` (701 LOC) is
  *knowledge sync*, genuinely different and coherent: keep it and rename the UI "Sync with another machine", or
  cut it too. If job offload is ever wanted back it is a NEW, smaller feature (batch embeddings, ingestion) —
  and **do not reach for Celery/RQ/Redis**; Redis on Windows is a WSL/Memurai mess and SQLite + the existing
  queue schema is better.
- ⬜ **BL-365 FIX optional deps (~1 day) — DO THIS FIRST.** Until the venvs agree, **every other test may be
  lying.** (a) declare `cryptography` in `[core]` (Apache-2.0/BSD, pure wheel on Win/py3.12); (b) a **~20-line
  CI gate asserting `.venv` and `.venv-test` agree on every optional dep** — the single highest-value test in
  the repo, because it is the one that makes every *other* test honest; (c) **invert the skips** — gate on what
  the SHIPPED config can do, not on what the test venv imported (a skip that fires because the feature is broken
  is a silent pass — this is BL-342's disease, and how the dead TTS shipped); (d) **wire `/health/deps` to the
  UI** — it exists, works, has zero consumers, and is exactly what would have exposed the dead TTS; (e) delete
  `auto_pip_install_optional` — it defaults False and is **not in EDITABLE_SCHEMA**, so the UI cannot turn it
  on: a dead flag guarding a dead installer. **No OSS needed** — pip-tools/uv/pip-audit solve resolution, not
  "assert my two venvs agree."
- ⬜ **BL-366 FIX config (~1 day). REJECT pydantic-settings.** Measured: **437 live keys, 89 editable, 363
  (83%) silently unsettable**, 15 schema keys with no live value (latent KeyErrors). **But `save_config_keys`
  ALREADY RETURNS `saved`** (`runtime_safety.py:225` — verified) — the information needed to stop lying is
  already computed and thrown away by the router. **This is a ~10-line honesty fix, not an architecture
  problem:** return `{saved, rejected}` and have the UI toast what was ACTUALLY saved. That kills BL-335's lie
  class permanently — every future non-schema key included. pydantic-settings is MIT/mature/offline-fine but
  **installed in neither venv**, models env→dotenv→secrets (not Layla's defaults→auto-tune→migrator→user-edit
  with a hardware governor that must *clamp*), and 437 keys → 437 typed fields is a multi-week port with a large
  regression surface to fix a `continue` statement. Layla already has the good parts: `coerce_and_clamp`,
  atomic-write-with-fsync, `_config_lock`.
- ⬜ **BL-367 CUT ~60% of observability (−800 LOC) + wire tok/s (+5 lines).** **Drop `prometheus_client` from
  `[core]`** — Layla already re-implemented the ~5% she needs in ~150 lines with no dep, which was the right
  call (nobody scrapes a desktop app; OpenTelemetry is absurd here; structlog solves logging, not metrics).
  **NEW BUG:** `_build_fallback_summary()` and `_build_prometheus_summary()` **return different shapes**
  (nested vs flat) — so a `[core]` install (which gets prometheus_client) **breaks
  `system-diagnostics.js:18`** while a `[cpu]` install works. Two supported install paths, two different UIs.
  Dropping the dep fixes it by construction. **CUT:** `services/observability/metrics.py` (129 LOC, zero
  writers, `/metrics/observability` empty **by construction**) · **`routing_telemetry`** — the perf argument is
  weak (~2ms on a 70s turn, be honest) but **the privacy argument is decisive: a 90-day plaintext log of every
  user prompt (2,000 chars), unencrypted because encryption is dead, that NOTHING reads, in a product whose
  entire pitch is local-and-private. That is not waste, it is a liability.** **FIX:**
  `record_token_throughput` has zero callers while `llm_gateway.py:829` **already computes
  `tokens_per_second`** — producer and consumer exist 800 lines apart and were never introduced. **~5 lines
  gives Layla the ability to report her own throughput** — the one number that matters most on this box.
  What should be measured on a single-user CPU box: **tok/s, first-token latency, turn duration, RAM headroom,
  governor mode.** That is the whole list; the rest is a distributed-systems reflex applied to a desktop app.
- ⬜ **BL-368 FIX scheduler (~2 hrs). REJECT SQLAlchemyJobStore.** **NEW BUG:** `automation.py:_get_scheduler()`
  creates a **SECOND independent BackgroundScheduler** with its own `_SCHEDULED_JOBS` dict, undiscoverable from
  `get_scheduler()` — two schedulers, two thread pools. *That* is the defect, not the jobstore. Fix: one
  scheduler; persist `schedule_task`'s user-created jobs to a SQLite table mirroring `missions` (~40 lines, no
  SQLAlchemy); surface paused missions in the UI ("3 missions paused by a restart — Resume") and fix the docs;
  **do not auto-resume**. Test `execute_next_step` (zero coverage — it is the crash-recovery path).

### Verdicts — UI tier

- ⬜ **BL-369 KEEP vanilla ES modules. REJECT every framework, including the no-build ones.** The adversarial
  test — *does the rewrite eliminate the seam class?* — is **failed by all of them**. Alpine (MIT, ~7-15KB gz),
  petite-vue (~6-7KB gz), htmx (0BSD), Lit (BSD-3) are all **architecturally free to ADD** (precedent:
  `vendor/js/` already ships 180KB of marked+highlight+purify, offline, inside PyInstaller) — but **not free to
  ADOPT**: a 67-file + 1,345-line-HTML rewrite, re-integrating hand-tuned Warframe CSS and the sigils, and
  re-verifying an a11y baseline that already works — **to fix ZERO of the six dead features.** Alpine would turn
  `#app-font-size` missing from "silent no-op" into "silent no-op **plus a console warning**" — which `$req`
  gives for **15 lines and no rewrite**. React/Vue/Svelte additionally means Node on the build machine,
  `setup-node`+`npm ci` in `release.yml`, vendored `node_modules` or a committed `dist/` for offline
  reproducibility, and it kills the `:8777` preview loop. **"Rewrite in React" is wrong.**
  **Why the case dies before it starts:** the declarative binding registry **already exists and is healthy** —
  `core/actions.js` resolves **141/141 distinct action names**, zero fall back to `window[name]`; index.html is
  **156 `data-action` vs 9 `onclick`**. **Not one of the dead features is a state-management or binding
  failure.**
- 🔴 **BL-370 THE MECHANISM (the answer to "make the seam impossible to break silently"): three cheap guards,
  ~2 days, 0 dependencies.** The rot is in **exactly one layer**: `getElementById` — **430 calls, 235 distinct
  ids, 10 unresolvable, 7 duplicated.** Everything else (data-action routing, bus, i18n runtime, a11y) is sound.
  1. **`test_ui_element_contract.py`** — a static sweep in the EXISTING pytest suite: **~80 lines, 0 deps, <1
     second, no Node, no browser, no marker.** Forward (hard fail): every `getElementById('x')` must resolve to
     a static id in index.html or a JS-constructed literal — **10 violations today = 6 dead features**. Reverse
     (allowlist, burn down): 54 ids declared and read by nothing — including `#km-source`, `#km-label`,
     `#km-ingest-list`, `#appearance-save-msg`, **the other half of the same rename drifts. BL-320 appears in
     BOTH directions — that pair is the signature of a rename that updated one side.** Duplicates (hard fail):
     7 today.
     **Why this over everything else: it already found a defect the 119-item audit missed, in one second, with
     no toolchain.** Honest limit: it cannot see computed ids (`'cfg_' + key` for the 95 schema fields) — which
     is why you also need (2).
  2. **`$req(id)` / `$opt(id)`** in `services/utils.js` (~15 lines + a mechanical sed across 66 files): `$req`
     **throws in dev**, `console.error`s in prod (so the friend's install degrades rather than white-screens);
     every remaining `$opt` must carry a `// optional: <why>` comment, and the sweep asserts it — **which turns
     "I null-guarded it defensively" into a decision someone had to write down.** This inverts the default:
     absent element → **loud**, not silence. Catches the computed-id class the sweep is blind to.
  3. **Ban `onclick=` inside JS `innerHTML`** (one grep test, allowlist the 41 sites, burn down). Kills the
     study-preset SyntaxError class **permanently** — and the `data-action`/`data-arg` system that makes it
     impossible is **already used 10 lines above the bug** (`workspace.js:168`).
  **Rejected:** a second binding registry (you have one, it's healthy — building another is motion, not
  progress) · typed data-action registration (141/141 already resolve — solving a problem you don't have) ·
  component co-location (correct in principle, requires the 67-file rewrite to obtain; mechanisms 1-3 get ~95%
  of the benefit this week).
- ⬜ **BL-371 KEEP Playwright — grow 9 → ~25 tests. REJECT jsdom/happy-dom/web-test-runner.** The expensive part
  (server boot ~90s + chromium install) is **already paid in CI and ungated**; marginal cost per test is
  seconds. Add **one "click it and assert an outcome" test per top feature** (~8 lines each): Ingest posts to
  the KB endpoint, a Study preset click adds a plan, Appearance save posts a **non-empty** body, the health
  banner appears when /health fails. **jsdom is rejected on evidence, not taste: it has no layout, so
  `header{display:none}` — the single line that killed 4 features — is INVISIBLE to it**, and it would add a
  Node toolchain to a Python repo to cover a layer the static sweep covers faster. **The asymmetry that settles
  it: a jsdom/Playwright test only finds `#ingest-path` if someone wrote a test that clicks Ingest — nobody did,
  for years. The sweep finds it whether or not anyone thought of it.** Also: install `requirements-e2e.txt` into
  `.venv-test` so it stops silently collecting zero locally.
- ⬜ **BL-372 KEEP `i18n.js` — the runtime is not the bug.** ~120 lines, correct: flattened catalogs,
  `dict→_fallback→key` chain, `{param}` interpolation, plurals, RTL, `<html lang/dir>`, Intl, re-applies on
  `layla:languagechange`. i18next (~40KB+) would fix **nothing** — you'd port 11 catalogs to solve a coverage
  problem it also doesn't solve. **Measured: 35/162 static buttons have `data-i18n` (78% bare); `data-i18n`
  appears in exactly ONE JS file — `i18n.js` itself — so ZERO of the ~168 dynamic buttons emit it; `en.json`
  has 126 leaf keys for ~330 button labels (the catalog is a third the size of the surface).** Fix: (a) a static
  sweep asserting every button/label/placeholder carries `data-i18n*` or is allowlisted, and every key exists in
  `en.json`; (b) a **`qps` pseudolocale** (`⟦{en value}⟧`) — switch to it and every untranslated string is
  instantly visible, catching the dynamic renders the sweep can't reach, for one generated file and one array
  entry; (c) emit `data-i18n` during the BL-370 mechanism-3 migration and call `applyTranslations(box)` after
  every dynamic render (~40 sites need it), then sweep-assert it.
- ⬜ **BL-373 Settings: ONE surface, three depths. REBUILD the modal renderer (~1 file).** `config_schema.py`
  carries `"category"` on **every** key (9 categories); `settings-full.js:74-89` iterates flat and **never reads
  `f.category`** — **the backend already ships the IA and the frontend throws it away.** Two gears with the same
  icon and tooltip is not a discoverability bug to patch with a cross-link; **it is one surface that got built
  twice.** Depth 1 "Common" (the ~25 curated toggles, promoted to `category:"common"` so the backend stays the
  single source; the 6 overlapping keys exist ONCE; delete `#tts-toggle2`) · Depth 2 grouped by the 9 backend
  categories (one `.reduce()`) · Depth 3 "Advanced" + a filter box (an engineer wants Ctrl+F, not curation —
  which is what the flat list accidentally already is). One gear, one route, **not Ctrl+K-only** — which is
  BL-246, whose fix is **deleting one CSS line** and which partially resolves BL-247/251/252 at once.

### Order (UI tier): 1) element-contract sweep · 2) `$req`/`$opt` · 3) **delete `layla.css:242`** (1 line, 4
### features back) · 4) ban `onclick=` in JS · 5) grow e2e 9→25 · 6) i18n sweep + pseudolocale · 7) settings IA.
### Items 1-4 are ~2 days and close the class that produced most of W14.

### Verdicts — memory/learning tier (the most valuable review; it corrected TWO of my own constraints)

- 🔴 **BL-374 LOCAL-FIRST BREACH — the worst constraint violation found all session.** VERIFIED: **no
  `local_files_only`, no `HF_HUB_OFFLINE`, no pre-fetch anywhere in the repo.** `install/model_downloader.py`
  provisions **only GGUFs** — the embedder (nomic/all-MiniLM), the cross-encoder and potion-base-8M are fetched
  **lazily from HuggingFace on first use**. A genuinely offline first-run **silently degrades**:
  `_cross_encoder_failed=True` -> `return docs[:k]`, unranked, no error. **For a product whose entire reason to
  exist is offline privacy, the memory tier phones home on first use and fails quietly.** Fix: bundle the models
  in the installer, or set `local_files_only` and **fail loudly**.
- 🔴 **BL-375 The operator's venv is a THIRD configuration nobody ships.** The installer ships `[cpu,llm]`
  (model2vec + sqlite-vec + sentence-transformers + torch). The operator's `.venv` is a partial `[core]`: torch
  present, **model2vec, sqlite-vec AND chromadb all missing** — "the worst of both: torch's 2.5GB weight with the
  fallback store's performance." **Every conclusion drawn from driving this box about retrieval speed is
  suspect.** Measured: model2vec is **65x faster per embed** (0.004s vs 0.259s per 100) and ~11s less startup.
  **TWO OF MY OWN CONSTRAINTS WERE WRONG:** (a) "a dep needing 4GB is a non-starter" — **torch already ships to
  every user** via sentence-transformers in `[cpu]`, so the CrossEncoder is already paid for; (b) "adding deps
  isn't free — 10 are already missing" — the deps that matter are **already declared in the shipped extra** and
  missing only from MY venv. **That is config drift between the box we test and the box we ship. The fix is
  parity, not restraint.** (Also `vector_store.py:100`'s claim that model2vec "drops the torch weight" is false
  as shipped — keep model2vec for SPEED, the honest reason.)
- 🔴 **BL-376 BL-338 UNDERSTATED, and BL-264/265 MISDIAGNOSED (mine).**
  - **Two holes, one symptom:** fixing the `finished` gate fixes only ORCH-ST (7/24 turns). The other **17/24
    take the fast path at `routers/agent.py:894`, which never calls `agent_loop` AT ALL** — no state, no
    finalizer, nothing to gate.
  - **The fix names itself:** all three done-frames (`:968` fast, `:1285` stream, `:1360` non-stream)
    independently repeat the **same six lines** of persist+title logic. **That triplication IS the missing
    abstraction.** Introduce `commit_turn(conversation_id, goal, text, *, aspect_id, state=None)` — the ONLY
    place a completed turn is durably recorded: persist, then dispatch post-turn learning. `state` is optional;
    the fast path has none, and post-turn learning legitimately needs only `(goal, text, aspect_id)`. The
    `status` gate then becomes what it always should have been: a **safety** filter
    (`refused/blocked/timeout/abort`), not a **liveness** one. Mature frameworks all fire on the *turn boundary*
    (LangGraph `on_chain_end`, Letta's post-step commit, Agents-SDK `RunResult`). **Layla independently arrived
    at the right structure — a finalizer — and attached it to the wrong signal.** CAUTION:
    `run_distill_after_outcome(n=50)` is O(n^2) Jaccard and runs synchronously per finished turn — **debounce it
    BEFORE wiring it to every turn.**
  - **LEARNING QUALITY IS NOT A THRESHOLD PROBLEM — I was wrong.** All 28 rows *would pass any gate you could
    write*: grammatical, confident, >40 chars, unhedged. The defect is `run_finalizer.py:126` — `learn_text` is
    **the ASSISTANT'S REPLY** — and `outcome_writer.py:271` iterates `resp_clean.split("\n")`. **The system
    faithfully extracts what Layla said about Python, not what is true about the operator.** Ask her to write a
    Fibonacci function and she dutifully memorises the docstring. **100% of the table is this. It is working
    exactly as written.** My BL-265 was also imprecise: the `always|never|should|must` regex is the **fallback**;
    the primary path is an LLM extraction call. **Fixing the regex fixes nothing.**
  - **Right fix:** source from the **user turn**; **closed-schema** extraction a 3B can actually do
    (`{"subject":"user"|"world"|"none","fact":...,"durable":bool}`, hard-reject `subject != "user"`) instead of
    open-ended "find insights"; type the memory (preference/correction/identity/episodic) and gate per type at
    the **existing choke point** (`learnings.py:80` already runs filter + dedup + content_hash + rate-limit for
    every writer — the right architecture). **`outcome_writer.py:302-335` ALREADY has correction and
    implicit-preference detection reading `user_msg` — right instinct, right source, wrong file. Make that island
    the mainland.** **#1 and #2 are ONE change: the seam without the fix floods the DB with docstrings 8x
    faster.** (5-6 days together, ship behind a flag, watch what lands for a day.)
- ⬜ **BL-377 No OSS memory library fits — build it (~60 lines).** All disqualified on the hard constraints:
  **mem0** — posthog is a **hard core dep** and `MEM0_TELEMETRY=false` **does not fully work** (issues #3729,
  #3762: blocking I/O + threads persist): *a telemetry client that hangs on an offline box, in a privacy
  product* · **zep** — Community Edition **discontinued, cloud-only**; graphiti needs Neo4j/FalkorDB/Kuzu **and
  an LLM call per write** (tens of seconds at a 14s first-token) · **letta** — a server, not a library;
  migrations are **Postgres-only**, so shipping it on SQLite signs users up for unmigratable data · **langmem** —
  pre-0.1, ~20mo stale, drags LangGraph + two cloud SDKs · **cognee** — ~50 core deps incl. a web server.
  **ECOSYSTEM FLAG: Kuzu is DEAD** (Apple acquihire Oct 2025; repo archived read-only) — **contaminates cognee
  and a graphiti backend. Do not adopt anything depending on it.** Only **txtai_minimal** (Apache-2.0, zero-dep
  escape hatch, runs against llama.cpp which we already ship) is worth a spike. **And mem0 would not even fix it:
  point it at the assistant's response and it stores the docstring too.**
- ⬜ **BL-378 The DEAD reranker is BETTER than the live one on the failure path that matters.** The live
  `vector_store_rerank.py` has **NO fallback**: if sentence-transformers is unavailable *or the model is not
  cached* (i.e. offline first-run — BL-374), `_get_cross_encoder()` returns None and `rerank()` **silently
  returns the first k docs unranked**. The dead `services/retrieval/reranker.py` has exactly the **zero-dep BM25
  backstop** that would save it. **Port `_bm25_rerank` INTO the live module, THEN delete the dead one** — do not
  just delete. Fix `capabilities/registry.py:72-84`, which advertises reranker capabilities pointing at the dead
  module (a self-knowledge lie — cf. BL-306). **flashrank: SKIP** — its whole pitch is "no torch" and torch
  already ships; adding onnxruntime (~50MB) to avoid a dep we already have is a net loss. **chromadb: DROP from
  `[core]`** — still drags onnxruntime, grpcio and **a Kubernetes client** onto a desktop. **`rank_bm25` is
  ABANDONED** (last release Feb 2022) — migrate to **bm25s** (MIT, torch-free) opportunistically. **sqlite-vec**
  (MIT, ~2MB, zero py deps; verified v0.1.9 KNN works) is already coded for in `fallback_store.py`, already in
  `[cpu]`, just missing here — brute-force is **correct at 28-10k rows**; do not pay for an ANN index.
  **BL-361 is nearly free:** `_retrieve_and_build` already threads `track_ids`; `context_builder.py:113` simply
  calls the wrong function — they diverged only because the `_with_ids` path skips the 60s cache. **Cache the
  tuple instead of the string. ~2 hours.**
- ⬜ **BL-379 THERE IS NO GRAPH — 71 entities, 0 relationships (verified directly).** *"A graph with no edges
  isn't a graph — it's a list."* Nodes come from the entity extractor (which sits OUTSIDE the `finished` gate,
  which is why any exist at all); **edges come from `auto_link_learning`, whose only production caller is the
  ingestion pipeline — reachable solely via the Ingest button, which BL-320 proves is DEAD.** Nodes from one
  writer; edges from a writer no user can reach. And the nodes are junk anyway (`'research what'`, `'the world'`,
  `'earned_title'` — leaked control text; **`'trusts nyx'` is a RELATIONSHIP mis-parsed as a node** — the
  extractor found the one real edge in the corpus and stored it as a vertex). **MY networkx framing was WRONG:**
  `get_entity_graph`'s SQL-scoped BFS touches only the k-hop neighbourhood; **networkx would load the ENTIRE
  graph into memory to answer the same query. The hand-rolled BFS is the better engineering — do not replace
  it.** networkx (BSD-3, already installed) earns its keep ONLY for pagerank/Louvain/centrality, *if edges ever
  materialise*. Do not add rustworkx (a compiled dep to optimise milliseconds) or kuzu (dead). Also: two codexes
  — `routers/codex.py` serves a **JSON file** while the SQLite entity DB (with the schema, encryption and
  confidence scoring) **has no router**. Pick the SQLite one. **BLOCKED: do not start here.** Fix BL-376 +
  BL-320 and re-measure — the graph may largely fix itself.
- ⬜ **BL-380 Spaced repetition: the LIVE clone is BUGGIER than the dead original.** DB: `next_review_at` **0
  rows**; `review_reps > 0` **0 rows** — the SM-2 schema has **never held a single item**. The live
  `german_mode.py:388` clone uses the **stale ease factor** (`interval * ease_factor` instead of `new_ef`) and
  **never clamps ease to the 1.3 floor on failure**, so a repeatedly-failed card's ease drifts unbounded. **The
  wired implementation is worse than the dead one it duplicates — and it drives the only real flashcard UI.**
  **`fsrs`** (MIT, 6.3.1 Mar 2026, **one dep: typing-extensions**, ~50KB, verified running CPU-only on py3.12 —
  PyPI name is `fsrs`, NOT `py-fsrs`; torch appears only in the `[optimizer]` extra) is what Anki uses and is
  strictly better than SM-2. **But the algorithm was never the bottleneck — nothing has ever ADDED an item to the
  queue.** So: **(a) CUT — delete the dead module, drop the "Spaced repetition study sessions" claim from
  `chat-render.js:385` (an untrue claim in Layla's own voice — that IS the bug), fix german_mode's ease bug (2
  lines). ~1 hour, honest immediately.** Or (b) adopt `fsrs` + build a queue producer + a review UI (~3 days).
  **Do not hand-roll SM-2 a third time.**

### What is genuinely good (recorded because the audit format selects for defects)

The hybrid **RRF + MMR + model2vec + sqlite-vec-fallback** design is **the right answer for a CPU box** — better
than most cloud-first OSS would give you. **sanitize-before-extract** and its comment are real forensic work.
**`is_memory_junk`'s** documented feedback-loop reasoning is something most codebases never write down. The
**SQL-scoped BFS** is better engineering than the networkx it was criticised for not using. The **write choke
point** with dedup + rate limiting is exactly where a subject-gate belongs. `core/actions.js` resolves
**141/141**. The **filesystem jail** survived every escape attempted. **Mocking discipline** is genuinely good.

> **The tier's problem isn't that it was built badly. It's that it was built well and then not plugged in — and a
> 2,700-test suite asserting *which fields a function reads* could never tell the difference.**

### Verdicts — agent/tools/sandbox tier (the highest-leverage finding in the whole review)

- 🔴 **BL-381 ONE LINE: `@functools.wraps(fn)` at `registry.py:106`. BL-346's central premise is FALSE — and
  that is GOOD news.** BL-346 said *"there is no static contract to check."* **There is.** Verified directly in
  the APP venv:

      registry wrapper sees : (*args, **kwargs) -> Any      <- the contract, DISCARDED
      underlying fn sees    : (expression: str) -> dict     <- the contract, right there
      registry __doc__      : None                          <- the description, NULLED
      pydantic 2.13.4       : already installed, MIT, FastAPI REQUIRES it (cannot become a dead dep)
      generated schema      : {'properties':{'expression':{'type':'string'}},'required':['expression']}

  **196/198 tools (98%) are fully type-annotated**, and pydantic built a JSON Schema for **198/198 in 247 ms**.
  This reframes BL-346 from "design a schema system" (weeks) to **"stop discarding the one you have" (a day)**.
  **It also explains BL-306:** `list_tools` returns **198 tools with 100% EMPTY descriptions**
  (`general.py:379` reads `fn.__doc__`, which the un-wraps'd wrapper nulls) — **that is the tool Layla uses to
  answer "what can you do?"**. The capability manifest was working around a one-line bug.

  **CORRECTS W15's cleared-suspect note:** the 198 hand-written `description` strings **reach the model
  NOWHERE** — `llm_decision.py:425` sends `tool_names_for_decision()`, a **bare comma-separated list of names**.
  All 20 `TOOLS` iteration sites were grepped; not one reads `description` into a prompt. **So a 3B is asked to
  invent argument names from nothing:** it sees `glob_files` and a GBNF where `args` is a free-form `object`; it
  cannot know `root` exists. Demonstrated: `glob_files` -> `TypeError: missing 1 required positional argument`.
  **Fair to Layla:** `core/executor.py:183` catches it, so the cost is **a burned 15-70s iteration and a raw
  TypeError fed back to a 3B**, not a crash — a weaker argument than BL-346 implied, and it should be made
  honestly.

  **The seam already exists:** `services/tools/tool_preflight.py` is a hand-written required-arg checker
  covering **6 of 198 tools** that ends in `return PreflightResult(ok=True)` — **allow-by-default for the other
  192**. It is a partial manual re-implementation of what the schema generates for free. The choke point is
  `core/executor.py:run_tool` between `clean_args` and `fn(**clean_args)` — **170/198 tools reach it** (the
  other 29 are `_HARDCODED_INTENTS` whose args are built in Python, type-correct by construction). One seam,
  ~15 lines, 170 tools. `llama_cpp.llama_grammar.json_schema_to_gbnf` **is present in the pinned 0.3.32
  (verified, emits valid GBNF)** — schema->grammar is free, replacing the free-form `object` rule.

  **VERDICT: FIX-IN-PLACE with pydantic (~250 lines):** `@wraps` (1) + `tool_schema.py` (~40) + validation at
  `run_tool` (~15) + grammar wiring (~30) + descriptions into the prompt (~20) + one parametrized test (~60),
  minus `tool_preflight`'s table (~100 removed). **Closes BL-346 + BL-321 + BL-348 + the list_tools bug + the
  MCP schema drift.**

  **HONEST CONSTRAINT BL-346 MISSED:** the proposed "invoke every tool with schema-valid minimal input" smoke
  test **HANGS** (timed out at 120s) — blind invocation reaches tools that call the LLM, the network, or block.
  It needs **per-tool declared `smoke_args` in the meta + a per-call timeout**, not blind synthesis. The bounded
  version caught `math_eval` on the first run. Plan for ~198 curated arg samples, not zero.

  **REJECTED:** langchain-core `convert_to_openai_tool` (works, but high-churn and only transitively present —
  buys ~30 lines for a framework coupling) · `mcp`/FastMCP as a dep (**but note: MCP `inputSchema` IS JSON
  Schema 2020-12 IS `model_json_schema()` — so `cursor-layla-mcp/tool_definitions.py`'s 507 hand-written lines
  for 22 tools generate for free once this lands**) · pydantic-ai (**no llama.cpp backend** — issue #1801 closed
  with "run an Ollama server and use the OpenAI interface": a network hop + a second process on a 16.9GB box, to
  get what pydantic already gives). **`outlines` is DEAD OPTIONAL DEP #11** — in `requirements.txt:43`, missing
  from BOTH venvs, while `gbnf_grammar.py`'s docstring advertises an "outlines -> instructor -> plain-parse
  chain" whose first link is absent.

  **FAIR TO LAYLA:** the registry's taxonomy (`dangerous`/`require_approval`/`risk_level`/`category`/
  `concurrency_safe`/`feature`) is **genuinely better than langchain's `StructuredTool` or MCP's `Tool`** — a
  real policy model neither has. The 198 descriptions are well written. **The only missing field is `args`** —
  and pydantic derives it from code that already exists.

- 🔴 **BL-382 SANDBOX: the honest answer is the one anticipated — "you cannot sandbox Python on Windows without
  a real OS boundary; the approval gate IS the boundary; stop advertising a jail."** Both HIGHs reproduced.
  The `.exe` bypass is **worse than four characters**: `pwsh` and `bash` **are not on the 16-item blocklist at
  all**; `PowerShell.EXE` (case) passes; `certutil.exe`, `wget.exe`, `curl.exe` all allowed. Network jail:
  **3/3 bypasses reproduced** (`import _socket`, `importlib.reload(socket)`, raw `_socket.socket`) — plus
  `subprocess` is not blocked, so `os.system('curl.exe')` is a fourth.

  **The state of the art AGREES:** RestrictedPython's own docs say *"not a sandbox system or a secured
  environment"* (+ CVE-2023-37271, stack-frame escape); **smolagents' own docs** say local execution *"must not
  be used as a security boundary"* and that the only robust isolation is E2B/Docker/Modal — **all cloud or
  Docker, i.e. all disallowed here**. Firejail/nsjail/bubblewrap are Linux-only. wasmtime-py **installs and
  runs (verified)** but gives neither pip deps nor subprocesses — wrong shape for `run_python`. The genuine
  answer (OpenAI Codex's Windows restricted tokens + synthetic SIDs + ACLs + an elevated setup helper) is **an
  installer-privilege redesign, not a sprint**, and not drop-in MIT code.

  **THE INSTRUCTIVE CONTRAST:** the **filesystem jail survived every escape** because it **normalizes THEN
  compares**; the shell blocklist fails because it **compares WITHOUT normalizing**. *Same team, same file
  family, one `os.path.splitext` apart.*

  **VERDICT: FIX the two mechanisms + REBUILD the claims (~1 day):** (1) normalize before matching — strip
  `.exe/.cmd/.bat/.com/.ps1`, casefold, resolve; add `pwsh`, `bash`, `wget`, `certutil`, `bitsadmin`, `mshta`,
  `rundll32`, `wmic`; (2) **default `shell_restrict_to_allowlist` to True** — the allowlist already exists with
  the right names, so this flips allow-by-default to deny-by-default via a config change; (3) **delete the
  network jail or rename it** — if kept as a speed bump, its docstring must say *"best-effort; trivially
  bypassable; not a boundary"*; (4) **remove "network-jailed"/"sandboxed" from every user-facing string**
  (feeds BL-306: a manifest claiming a jail is worse than no manifest); (5) **`test_shell_approval_gate.py`
  (BL-344) is now THE priority test fix in the repo** — the approval gate is the only real control, and its
  guard would pass if you deleted the gate entirely.

- ⬜ **BL-383 Agent loop: KEEP the loop, DELETE the facade (~1 day, mostly deletions).** `core/observer.py` ->
  `state["_snapshot"]` is write-only (zero readers, ungated at `run_setup.py:517`) — **but BL-323's magnitude
  claim is WRONG**: measured **14,448 ms on call 1, then 66 ms / 58 ms**. It is ~60ms/turn steady-state, NOT
  "pure waste". The honest indictment: it **forces the 14.4s Chroma cold-start onto the first orchestrated turn
  even when nothing needs vector recall.** Delete for correctness + first-turn latency, not throughput.
  `core/validator.py`'s `passed` is confirmed discarded (`verification_engine.py:53-63` reads
  `flagged_injection`/`warnings`, never `passed`) — **fix in 3 lines: consume it as an annotation, or delete it
  and stop claiming a verdict exists. Do NOT make it abort the loop** — the docstring is right that a hard fail
  on a 3B's noisy output would be worse. "Reflect" is confirmed as one canned string
  (`reasoning_handler.py:280`); `pipeline_stage="REFLECT"` is set inside the block BL-338 proves never runs.
  **Plan/Reflect -> RENAME**: they are prompt interpolation and a canned sentence; *calling them stages is what
  let BL-323 sit unnoticed — the same disease as BL-343: the artifact named after the intent, not the
  behaviour.* **REJECT LangGraph** (Layla already has `GraphExecutor` + `plan_steps_to_task_graph`, live via
  `planner.py:904`, default ON, plus task persistence — LangGraph's headline features are things already built
  and wired) · **REJECT smolagents** (code-as-action demands MORE instruction-following than JSON tool calls —
  backwards on a 3B; the research is blunt that sub-7B models *"do not reliably parse tool schemas"*) ·
  **REJECT pydantic-ai** (no llama.cpp backend). **Layla's real differentiators — GBNF pinning tool names so a
  3B physically CANNOT hallucinate a tool, the risk/approval taxonomy, auto-tune tiers — have no equivalent in
  any of them. Adopting one is a downgrade.**

- ⬜ **BL-384 Multi-agent: KEEP one, DELETE two. CORRECTS BL-361 — `coordinator.py` is NOT shadowed; it is the
  live front door** (`routers/agent.py:39` + `routers/agent_tasks.py:74` both import `coordinator.run`; it does
  classification, trace, task persistence, worktree isolation, bounded retry, strategy feedback). What is
  orphaned is **four helper functions inside it**, not the module: `run_parallel_subtasks`, `spawn_subtasks`,
  `merge_outputs`, `resume_from_task` (~110 lines). **There are not three overlapping systems** — there is one
  live dispatcher, one live graph executor reached through it, and one gated-off decomposer.
  **`multi_agent`'s CPU-tier gate is CORRECT ENGINEERING, not an oversight** — the only subsystem in this entire
  audit that is dead **on purpose and for a good reason**: each subtask runs the full agent loop **holding the
  LLM lock**, so 3 subtasks = ~3.5 min of serialized inference for one question. **Parallelism across subtasks
  is arithmetically impossible on single-model CPU inference — one llama.cpp model, one lock.** **Do not adopt
  CrewAI/AutoGen** — they exist to parallelize across API calls; there is no fan-out to buy here. Decide
  `multi_agent` explicitly (delete, or keep and never let it appear in a capability manifest).

- ⬜ **BL-385 BL-341 RUNS IN THE OTHER DIRECTION TOO, and nobody looked.** `instructor` 1.15.4 and
  `docstring_parser` 0.18.0 are **present in `.venv` and MISSING from `.venv-test`** — so **production runs an
  instructor-backed decision path that CI cannot exercise**. BL-365's fix ("assert the two venvs agree") **must
  be BIDIRECTIONAL**; the stated framing only catches one direction. **THREE schema sources, none agree:**
  `domains/*.py` (198 tools, no args) · `tool_preflight.py` (6 tools, hand-written) ·
  `cursor-layla-mcp/tool_definitions.py` (**507 lines, 22 hand-written `inputSchema` blocks**). One pydantic
  generator collapses all three.

---

## W16 — Instance enumeration (2026-07-16): the classes are mapped, here are the counts

*The class map (W14) and the architecture (W15) are done. This is the mechanical instance count for each
remaining class — cheap, finite, re-runnable. Scripts are one-off and in the session scratchpad; the durable
one is `agent/tests/test_ui_element_contract.py`.*

**Method note that matters: every count below is an UPPER BOUND with known noise, not a defect list.** Sweep C
proves why — see its false positives. Do not action a number from here without triaging the entries.

### C1 — `onclick=` in JS templates: **40 sites across 10 files**

    11  components/chat-render.js       6  components/memory.js
     6  components/workspace.js         5  components/pairing.js
     4  components/search.js            3  components/artifacts.js

This is the class that killed the study presets (BL-258): `JSON.stringify` emits DOUBLE quotes into a
DOUBLE-quoted `onclick`, the parser ends the attribute early, the handler never runs, and the button renders
perfectly. **The `data-action`/`data-arg` system that makes it impossible already resolves 141/141 actions** and
is used feet away from the bug. Fix: migrate the 40, then a grep test banning `onclick=` in `ui/**/*.js`.
Ratchet, burn down. (BL-370 mechanism 3.)

### C2 — i18n coverage: measured, and worse than BL-261 stated

    static <button> without data-i18n : 127 / 162  (78%)
    buttons built dynamically in JS   : 155
    data-i18n emitted anywhere in JS  : 11
    applyTranslations call sites      : 7

So **both halves fail**: 127 static buttons never translate, and ~155 dynamically-rendered buttons are injected
as hardcoded English (11 `data-i18n` occurrences in ALL JS combined). Even a translated button reverts the
moment a `refreshX()` re-injects it — only 7 render paths call `applyTranslations`. **The applier itself is
fine** (BL-372); this is pure markup coverage. 11 locales + RTL ship and RTL users start in LTR English.
Fix: static sweep + `qps` pseudolocale (`⟦{en}⟧` makes every untranslated string visible instantly) + emit
`data-i18n` during the C1 migration.

### C3 — ids declared but referenced by nothing: **99 candidates — AND THE SWEEP'S NOISE IS THE LESSON**

    declared ids            : 343
      read by JS            : 208
      styled in CSS         :  49
      legit non-JS (for/aria/href) : 14
      data-action driven    :  32
      TRULY unreferenced    :  99  <- upper bound, NOT a defect count

**Verified false positives inside that 99:** `#btn-cassandra`, `#btn-echo`, `#aspect-opt-*` and friends are
built at `aspect.js:74` as `getElementById('btn-' + id)` and `aspect.js:215` as `el.id === ('aspect-opt-' + id)`
— **computed ids, the exact blind spot documented in `test_ui_element_contract.py`, firing exactly where it was
predicted to.** The forward sweep is precise because a lookup either resolves or does not; the reverse sweep is
inherently noisy because an id can be reached by construction, by CSS, by ARIA, or by an anchor.
**This is why the reverse sweep is a burn-down allowlist and NOT a hard gate** — and why C3 must be triaged by
hand, never bulk-deleted. Real hits confirmed in the list: `#appearance-save-msg` (BL-335's other half — the
element `saveAppearanceLite` should be writing to), `#km-ingest-list` (BL-291), `#batch-diff-*`.

### C4 — carried from W14, already counted, still open

- **153/198 tools invoked by no test** (110 never mentioned); **223/367 routes never called** (BL-346).
  *Calibrated: EXPOSURE, not 153 broken tools — `math_eval` was the only hard crash found, and it is now fixed.*
  **BL-381 unblocks the real fix:** `@functools.wraps` landed, so pydantic now schemas 198/198 — a parametrized
  registry smoke test is finally possible. It needs **per-tool `smoke_args` + a per-call timeout**; blind
  invocation HANGS (verified, 120s timeout) because some tools call the LLM or the network.
- **119 AST-confirmed vacuous tests** + ~114 key-presence candidates needing manual triage (BL-340).
- **7 dead lookups** on the `_KNOWN_DEAD` ratchet in `test_ui_element_contract.py` (BL-335/249/337).
- **7 duplicate `growth-*` ids** (BL-248) — pinned by `test_no_duplicate_static_ids`, can only shrink.

### The loop's terminal condition, stated honestly

**New CLASSES stopped appearing** — that is what convergence looks like, and it is why the investigation is
complete. **New INSTANCES have not stopped**, and on a ~400-module codebase they will not: every sweep above is
an upper bound that needs human triage, and C3 demonstrates why an automated count is not a defect list.

The durable answer is not "find every instance once." It is the guard that makes the class unrepeatable:
`test_ui_element_contract.py` is hard-fail for the forward direction, so **new drift dies immediately**, and the
known-dead ratchet can only shrink. Instances found *later* by that guard cost seconds. Instances found by
hand-auditing 343 ids cost a session and go stale the next commit.

---

## W17 — Operator-observed during P13 execution (2026-07-17)

- 🔴 **BL-386 — the setup-profiles popup is an UNWINNABLE, INESCAPABLE modal.** Operator screenshot: "set up
  layla / what do you want to do? / pick at least one / continue" with **zero options rendered**. Two defects,
  both in committed (pre-S5) code (`ui/components/setup-profiles.js`), both this codebase's signature classes:
  1. **Empty render → dead-end.** Step 0 does `((_data && _data.profiles) || []).forEach(...)` (`:72`). The
     data comes from `GET /setup/profiles` (`:151`), and `:155` falls back to `{profiles: [], features: []}`
     on any non-array/failed response. Empty profiles -> no cards -> "what do you want to do?" with nothing to
     choose -> `_onNext` (`:114`) blocks on `if (!_selProfiles.size) ... 'pick at least one'; return;` FOREVER.
     Root-cause the endpoint: does `/setup/profiles` actually return PROFILES on a fresh/this install, or is
     the frontend swallowing an error into the empty fallback? (install/setup_profiles.py::PROFILES.)
  2. **Escape is wired to the wrong element.** `_root.addEventListener('keydown', ...Escape... closeSetupProfiles())`
     (`:54`) — a listener on `_root` only receives keydowns that target it or a descendant. If focus is on
     body (the default), Escape never reaches it. The decorative `<kbd>esc</kbd>` chip (`:44`) ADVERTISES an
     exit the wiring does not deliver. Fix: listen on `document` (as other overlays do), and make the modal
     dismissable (the esc chip should be clickable too).
  **RELEVANCE TO S5:** this is the first-run/setup surface S5 is actively touching. S5's verification MUST
  confirm the profile picker renders options AND Escape closes it — if S5 makes the wizard reachable without
  fixing this, it makes a dead-end modal MORE reachable, not less. Fold into S5's follow-up or a first-run
  polish slice; guard with a test that boots the flow and asserts (a) options render for a normal profile set,
  (b) Escape dismisses. A source-grep does not count — attempt 1 shipped a dead UI past 17 text-greps.

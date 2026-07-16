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

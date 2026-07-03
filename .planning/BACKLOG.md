# Layla — Exhaustive Backlog (the "watertight" master list)

**Source:** the exhaustive completeness loop of 2026-07-03 (planning backlog + 3 code sweeps:
incompleteness markers · stubs/dead-code/skipped-tests · backend-without-UI/dead-config), calibrated
against the actual `ui/components/` set. **Nothing from the loop is dropped here.** This is the single
tracking list; [PLAN.md](PLAN.md) holds the strategy/architecture and points here for the itemized work.

**Status legend:** ⬜ open · 🟡 partial · ✅ done · ✂️ decided-cut. Each item has a stable `BL-###` id.
**Workstreams W0–W11** are the execution order proposed in PLAN.md §5b; they map every loop bullet to work.

---

## W0 — Stabilize & clean (quick, low-risk, do first)
- **BL-001** ⬜ Restart the running app — stale `llm_gateway` in the 18.5h process makes chat 500 until reload.
- **BL-002** ⬜ Dead flag `dynamic_tool_generation_enabled` (`runtime_safety.py:324`) — read nowhere → delete or wire.
- **BL-003** ⬜ Dead flag `codex_semantic_enabled` (`runtime_safety.py:470`) — read nowhere → delete or wire.
- **BL-004** ⬜ Dead flag `slack_webhook_url` (`config_schema.py`) — read nowhere → delete or wire.
- **BL-005** ⬜ Delete tracked-dead files: `services/protocols.py`, `services/tool_generator.py`, `ui/js/layla-app.js.bak`.
- **BL-006** ⬜ `vector_store.py:160-174` int8 quantization falls back to **deprecated `torch.quantization`** when torchao absent — replace/guard (breaks on newer torch).
- **BL-007** ⬜ `execution_state.py:80` coordinator + task-graph are **placeholders** — implement or remove.
- **BL-008** ⬜ `projects_db.py:223` fallback for "not-yet-migrated" columns — add the migration.
- **BL-009** ⬜ Back-compat shims audit — `research_lab/intelligence/stages/utils.py`, `background_job_worker.py`, `lens_refresh.py`, `probe_hardware.py`: keep-as-shim or remove callers then delete.
- **BL-010** ⬜ `services/observability/_legacy_observability.py` — remove if superseded.
- **BL-011** ⬜ Uncalled standalone scripts (`seed_self_training_plans.py`, `export_finetune_data.py`, `download_docs.py`, `probe_hardware.py`) — move into a `scripts/` package or document as manual tools.

## W1 — Security & sandbox hardening (SHIP-BLOCKER — §7)
- **BL-020** ⬜ **Sensitive-data encryption at rest** (`schemas/entity.py:57`, marked "ideally", not implemented).
- **BL-021** ⬜ Shell **deny-by-default + allowlist** when remote.
- **BL-022** ⬜ Subprocess **rlimits / cgroups / Windows job-object** for code exec.
- **BL-023** ⬜ Ephemeral-container (E2B) exec tier.
- **BL-024** ⬜ Per-invocation approvals.
- **BL-025** ⬜ Egress control / network jail.
- **BL-026** ⬜ Audit-by-default when remote.
- **BL-027** ⬜ R9: split `vector_store.py` (~1410).
- **BL-028** ⬜ R9: split `migrations.py` (~1362, hand-rolled ladder).
- **BL-029** ⬜ R9: split `tool_dispatch.py`.
- **BL-030** ⬜ R9: split `cursor-layla-mcp/server.py` (~1296).

## W2 — Surface the headless backend (BIGGEST UI GAP — 14 families, ~80 routes)
Genuinely headless (no `ui/components/*` exists — verified). Corrects PLAN's "~18" underestimate.
- **BL-040** ⬜ **🇩🇪 German language-learning UI** (11 routes: profile/level/correct/corrections/calibrate/flashcards+SRS/stats) — the **headline wedge feature**, fully built backend, zero UI.
- **BL-041** ⬜ Missions board UI (8: create/get/list/pause/resume/cancel/board/horizon).
- **BL-042** ⬜ Journal UI (3: journal/daily/create).
- **BL-043** ⬜ Sync / Syncthing UI (5: status/rescan/device-id/add-device/setup-guide) — UPG-33.
- **BL-044** ⬜ Codex / relationship UI (6: get/put relationship, proposals gen/approve/dismiss).
- **BL-045** ⬜ Intelligence / AirLLM / KB UI (13: info, airllm gen/chat/unload, compress/rag, optimize, kb build/articles).
- **BL-046** ⬜ Debate UI (2: debate, modes).
- **BL-047** ⬜ Improvements UI (4: list/generate/approve_batch/reject).
- **BL-048** ⬜ Plans UI (5: get/patch/approve/execute/viz) + Projects UI (3: get/patch/delete).
- **BL-049** ⬜ Approvals + session-grants UI (6: pending/approve/deny, grants list/clear, refresh_lens).
- **BL-050** ⬜ Agent-tasks UI (9: background/steer/execute_plan/resume/tasks/cancel + decision_trace).
- **BL-051** ⬜ tools-history UI (2: history/analysis).
- **BL-052** ⬜ learn UI (2: schedule, verify/stats) + wakeup.
- **BL-053** ⬜ (calibration note) Families WITH components but some routes reached only via dynamic paths (conversations, memory, character, research, workspace, obsidian) — audit for genuinely-missing controls (e.g., `/character/*` 15 routes: creator is partial per REQ-79).
- **BL-054** ✅ (this session) System-diagnostics surfaced `cot_stats`/`metrics`/`security`/`capabilities`/`resources`; self-test surfaced `health`/`v1`.
- **BL-055** ⬜ Correct PLAN.md P4 "~18" → 14 headless families (~80 routes).

## W2b — Decide wire-or-cut on gated-OFF features (~18, default OFF, no toggle)
Each: build a Settings toggle + minimal surface, OR ✂️ cut and delete the code/flag.
- **BL-060** ⬜ `inline_initiative` · **BL-061** ⬜ `initiative_engine` · **BL-062** ⬜ `initiative_project_proposals`
- **BL-063** ⬜ `engineering_pipeline` · **BL-064** ⬜ `mcp_client` (+ un-skip 8 MCP tests, BL-140) · **BL-065** ⬜ `multi_agent_orchestration`
- **BL-066** ⬜ `litellm` · **BL-067** ⬜ `hyde` retrieval · **BL-068** ⬜ `elasticsearch` · **BL-069** ⬜ `meilisearch`
- **BL-070** ⬜ `remote` (part of W2 remote-access) · **BL-071** ⬜ `discord_bot_autostart`
- **BL-072** ⬜ `ui_decision_trace` (part of BL-050) · **BL-073** ⬜ `trace_id` / `tunnel_audit` / `telemetry_log_trivial`
- **BL-074** ⬜ `tool_replay_policy` / `pkg_policy_strict` · **BL-075** ⬜ embedder/STT/TTS prewarm (expose in Settings)
- **BL-076** ⬜ `geometry_frameworks_enabled` (cadquery/mesh/openscad backends all disabled) — wire or ✂️ cut
- **BL-077** ⬜ FabricationAssist **stub runner** (`automation.py:324`, `engine_plans.py:335`) — implement or ✂️ cut
- **BL-078** ⬜ mem0 integration (`mem0_integration.py:181`, disabled) — wire or ✂️ cut

## W3 — GUI finish (G2–G6)
- **BL-090** 🟡 G3 full form/card tokenization (some legacy input bgs kept).
- **BL-091** 🟡 G5 full 5-step onboarding **flow** (welcome · honesty-card · get-model · workspace · ready); self-test ✅.
- **BL-092** 🟡 REQ-79 aspect creator (name/sigil/sliders/voice/prompt + kit).
- **BL-093** 🟡 REQ-80 S.P.E.C.I.A.L.-style intake quiz.
- **BL-094** ⬜ REQ-81 / G6 per-aspect motion & polish (focus/reduced-motion ✅; motion choreography open).
- **BL-095** ⬜ Reconcile PLAN §6 palette spec (#0a0710/#c0395e) vs shipped tokens (#0a0008/#b11655) — pick one, remove the other from the doc. (Aspect hues already reconciled ✅.)

## W4 — Answer quality & eval
- **BL-100** ⬜ REQ-30 inline RAG grounding (MiniCheck/NLI, CPU, cite-or-abstain, `grounding` block) — **the #1 correctness lever**.
- **BL-101** ⬜ REQ-31 20–50 promptfoo golden set on PR + nightly.
- **BL-102** ⬜ UPG-01 hybrid escalation (small→big on low confidence; needs a bigger box to exercise 2 models).
- **BL-103** ⬜ UPG-04 FlashRank reranker.
- **BL-104** ⬜ Measure GBNF accuracy gain (HumanEval-164 — the discriminating step past the 10-problem set).
- **BL-105** ⬜ Measure self-consistency gain at K>1 (mechanism ✅; benchmark pending).
- **BL-106** 🟡 REQ-20 tiny-model inference-smoke **CI job** (seam ready, job unwired — `stories260K`/SmolLM2).
- **BL-107** 🟡 REQ-22 release-gate: pin seed/top_k.
- **BL-108** ⬜ REQ-82 coding scaffolding: repo-map ✅(wired) · diff-edit · **codebase RAG** · KV-cache reuse.

## W5 — Config & maintainability
- **BL-120** ⬜ REQ-50 **one typed config schema** — kill the two-file `config.json` vs `runtime_config.json` drift.
- **BL-121** 🟡 REQ-51 decompose `_autonomous_run_impl_core`; services stop importing `agent_loop` privates.
- **BL-122** 🟡 REQ-52 define shared UI data (ASPECTS) once; reduce `window.*` globals.

## W6 — Reliability & data
- **BL-130** ⬜ REQ-40 remove dead `LLMRequestQueue`; document the single-lock concurrency model.
- **BL-131** 🟡 REQ-41 `save_learning` embed **outside** the write txn; `/health` reports model-load failure.
- **BL-132** 🟡 REQ-42 backup includes the vector dir + WAL checkpoint + VACUUM.
- **BL-133** 🟡 REQ-43 erasure removes vectors + scrubs PII/secrets from logs.
- **BL-134** ⬜ `learnings.py:490` FSRS-style spaced repetition (currently simple interval).

## W7 — Test coverage (un-skip the 30+)
- **BL-140** ⬜ Add `fake_mcp_stdio.py` fixture → un-skip **8 MCP stdio tests**.
- **BL-141** 🟡 Wire tiny real-LLM smoke in CI (`LAYLA_TEST_REAL_LLM` + a stub GGUF) → un-skip `test_inference_smoke.py` module + `test_benchmark_coding_model.py`.
- **BL-142** ⬜ Playwright + `requirements-e2e.txt` in CI → un-skip `e2e_ui/test_ui_smoke.py`.
- **BL-143** ⬜ `tree-sitter-python` → un-skip `test_workspace_index.py`.
- **BL-144** ⬜ personalities-dir fixture → un-skip `test_aspect_behavior.py`.
- **BL-145** ⬜ Document/gate the env-only smokes (GPU/voice/browser/cgroup) so they're intentional, not silent.

## W8 — Ecosystem (V2/V3)
- **BL-150** ⬜ UPG-06 Ollama backend · **BL-151** 🟡 UPG-40 first-class `/v1` (REQ-61 params, REQ-83 Cline/Continue/Aider) · **BL-152** ⬜ UPG-41 Ollama API surface
- **BL-153** 🟡 UPG-12 MCP-only plugins · **BL-154** ⬜ UPG-13 Tauri shell · **BL-155** ⬜ UPG-34 VS Code / CLI / mobile-PWA clients
- **BL-156** ⬜ UPG-37 kit marketplace · **BL-157** ⬜ UPG-08 DSPy · **BL-158** ⬜ UPG-09 Open WebUI call · **BL-159** ⬜ UPG-42 HF Hub + ONNX
- **BL-160** ⬜ UPG-23 Castilla multilingual flagship · **BL-161** ⬜ UPG-33 memory/knowledge sync across paired instances

## W9 — Foundation-swap tail + scope-cut + install
- **BL-170** ⬜ UPG-10 engine abstraction · **BL-171** ⬜ UPG-11 one-SQLite memory file · **BL-172** 🟡 UPG-14 governor auto-cap
- **BL-173** ⬜ Phase 3 **scope-cut**: park cluster/tribunal/gamification-headline/HUD-chips behind reversible flags
- **BL-174** 🟡 REQ-72 install slice · REQ-73 first-run kit provisioning · REQ-75 full-app E2E + **one-command install** · REQ-76 each aspect = curated kit · REQ-85 kit upgrades (embedding-per-tier ✅, IQ-quant catalog, benchmark-driven selection)

## W10 — P0 tail (deprioritized churn)
- **BL-180** ⬜ httpx consolidation · **BL-181** ⬜ tenacity/diskcache/apscheduler replace bespoke.

## W11 — Companion depth (ADR-006, deliberately "later")
- **BL-190** ⬜ experience unification (continuity memory · passive initiative · emotional presence)
- **BL-191** ⬜ growth-system polish · **BL-192** ⬜ memory/learning verification pipeline

---

## Definition-of-Done gates (the "truly-ready" bar)
1. Zero 🟡/⬜ in the UPG backlog (or each explicitly ✂️ cut).
2. Scope cut to the wedge (W9/Phase 3).
3. Security tier (W1) complete — safe to expose through a tunnel.
4. Full-app E2E green + one-command install (BL-174).
5. Truly-ready gate = Phase 7 polish complete.

**Honest sizing:** this is **weeks-to-months**. W0 is hours; W1 + W2 (German UI especially) are the
highest-leverage; W8/W11 are V2/V3 horizon.

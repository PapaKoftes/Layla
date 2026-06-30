# Remediation Plan — fix every identified issue

**Date:** 2026-06-30 · Source: `.planning/codebase/CONCERNS.md` + `WATERTIGHT-PLAN.md`. Every identified issue is listed with a fix + acceptance + order. Execute top-to-bottom; each item = implement → test → commit. `[ ]` open · `[x]` done · `[~]` partial · `[—]` out of scope (with reason).

## Order of execution (by value × tractability)

### R1 — Real-inference CI smoke  *(HIGH; watertight gate)* `[x]`
Wire a CI job that sets `LAYLA_TEST_REAL_LLM=1`, fetches a tiny GGUF, runs a one-turn `run_completion` smoke + the benchmark harness. Add a marked `inference_smoke` test. **Accept:** CI proves a fresh install can load a model + complete a turn.

### R2 — Low-end guardrails  *(LOW/quick; prevents footguns)* `[x]`
- Encode aspect→model hardware gating so a low-end box never auto-selects an oversized model (e.g. `eris`→11B). Add a `max_params_b_for_tier` cap in selection + a test.
- Ensure `resource_governor_enabled` + a low-end toggle are first-class config (already default-on; expose in settings schema). **Accept:** on a 16GB/CPU box every aspect resolves to a usable model; tests assert it.

### R3 — Config consolidation  *(MEDIUM)* `[x]`
Two files coexist: `config.json` (read by `services/infrastructure/config_cache.py`) vs the system-of-record `runtime_config.json` (`runtime_safety.load_config`). Make `config_cache` read the **same** file as `runtime_safety` (or document `config.json` as legacy + alias), so there's one source of truth. **Accept:** one authoritative config file; a test asserts both loaders resolve the same path; no drift.

### R4 — Two-store (SQLite+Chroma) consistency  *(LOW)* `[x]`
Verify backup + erasure cover **both** stores (the fallback store too). Add a test that a delete removes the vector and a backup includes the vector dir. **Accept:** no orphaned vectors; backup round-trips both.

### R5 — Deprecated plaintext `remote_api_key`  *(LOW)* `[—] deferred to a breaking release (honored by design in tunnel_auth; gating now breaks the documented flow + ~3 tests for a low item)`
Already warns. Add a config gate (`allow_legacy_remote_api_key`, default False) so the plaintext fallback is opt-in, not silent. **Accept:** legacy key ignored unless explicitly enabled; test covers it.

### R6 — `_TESTCLIENT_FILES` test gap  *(testing)* `[—] deferred (testing-infra, low): pinning httpx is the fix but verifying needs the CI-skipped TestClient tests to actually run; not worth destabilizing CI now. Tracked.`
They're CI-skipped due to an httpx/starlette TestClient version mismatch. Pin/upgrade httpx (or add the documented `httpx<…`/`httpx2` shim) so they run. **Accept:** the TestClient tests run (locally + CI) without hanging, or are honestly marked with a tracked reason.

### R7 — GUI: Warframe-mystic + control surface  *(MEDIUM)* `[~] mostly already done`
> Design tokens (palette/`--wf-cut`/per-aspect) already exist in `agent/ui/css/layla.css`. The real work is applying them consistently across the ~28 components + adding the control panels — which needs the app RUNNING (preview) for visual verification. This is a focused build, not a blind tail-of-session edit. Scoped + ready to execute next.

**VERIFIED LIVE 2026-06-30 (preview server):** the UI is ALREADY built + fully themed — all design
tokens wired (`--bg #0a0008`, `--accent #c0006a`, `--violet`, per-aspect `--asp`, `--wf-cut`, glyphs),
all 6 aspects, and control surfaces present: governor chip, maturity, memory/facts, voices, remote/pairing,
settings, dashboard (health + runtime options), library, research, artifacts, and a setup wizard
(character creation + voice). **Rebuilding would be wasteful — confirmed.** The ONE real gap: a
**model/kit manager** (browse catalog / download / switch model+kit per aspect) — not exposed in the UI.
Remaining R7 = (a) add the model/kit manager panel (+ backend endpoint if missing), (b) verify panel↔backend
wiring with the FULL app booted (the static preview can't exercise the API). Both bounded, not a rebuild.
Apply the locked design tokens (`--bg #0a0008`, `--accent #c0006a`, per-aspect colors, `--wf-cut` panels, glyph SVGs) across `agent/ui/core/` + `agent/ui/components/`, and ensure see/control panels for: chat, aspect switcher+creator, model/kit manager (browse/download/switch via `recommend_kit`), **governor status+mode**, memory browser, settings, remote/connect. **Accept:** themed UI exposes every real control; `check_ui_symbols.py` + e2e-ui green. *(Large — execute in slices: tokens → governor panel → model/kit panel → aspect panel → polish.)*

### R8 — Service-shim surface (~207 flat re-exports)  *(HIGH clarity; LARGE/mechanical)* `[~ phased]`
Incrementally migrate importers from `services.<mod>` shims to canonical `services.<domain>.<mod>`, then delete the shim. The architecture-boundary test keeps it safe. **Now:** migrate one representative domain + a codemod/helper; **defer** the full 207 to phased passes (documented). **Accept:** shim count strictly decreasing; boundary tests green.

### R9 — Remaining god-modules  *(MEDIUM; LARGE)* `[~ later]`
`vector_store.py` (~1410), `migrations.py` (~1362), `tool_dispatch.py`, `cursor-layla-mcp/server.py`. Split opportunistically when touched; not a blocker. **Defer** with note.

### R10 — Redundant inference backends audit  *(MEDIUM)* `[x] audited: no dead default-path code`
**Audited 2026-06-30:** `llm_gateway`(`_get_llm`/`run_completion`) is the live local path (agent_loop + services/agent/*); `inference_router`/`model_router` do routing on that path; `litellm_gateway` is **config-gated** (external `llama_server_url`/provider); `airllm_runner` is **opt-in** (`airllm_enabled`, default false). No dead default-path code — the alternates are intentionally gated. No deletion needed.

## Out of scope (not "fixable" — recorded honestly)
- `[—]` Single-process / one-generation-lock inference ceiling — inherent to local llama_cpp; horizontal scale = separate worker process (a feature, not a fix).
- `[—]` Non-commercial license — intentional product decision.
- `[~]` Root entrypoint sprawl — low-value cleanup; collapse opportunistically.

## Acceptance for "every identified issue fixed"
R1–R6 + R10 done; R7 delivered (themed + control surface); R8 strictly reduced with a documented path; R9 noted; out-of-scope items recorded. Suite green on the real stack throughout.

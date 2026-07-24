# LAYLA COMPREHENSIVE AUDIT REPORT

> Generated 2026-05-13 — Full codebase audit covering backend, frontend, tests, config, docs, and open-source integration opportunities.

---

## EXECUTIVE SUMMARY

| Domain | Health | Critical Issues | Medium Issues |
|--------|--------|-----------------|---------------|
| Core Backend | **Good** | 2 | 4 |
| Memory / Codex | **Fair** | 1 | 2 |
| Routers / API | **Fair** | 3 | 2 |
| UI / Frontend | **Needs Work** | 5 | 3 |
| Tests | **Weak** | 1 | 0 |
| Config | **Fair** | 1 | 1 |
| Documentation | **Fair** | 0 | 2 |
| **TOTAL** | | **13** | **14** |

---

## 1. BACKEND BUGS (Confirmed)

### HIGH

| # | File | Bug | Impact |
|---|------|-----|--------|
| B1 | `services/retrieval_cache.py` | Lock held during slow I/O: `fetcher(query, k)` executes inside `_cache_lock`. If the fetch is slow (vector DB, network), ALL concurrent cache reads/writes are blocked. | Concurrency bottleneck — blocks all memory retrieval |
| B2 | `services/browser.py` | SSRF filter missing `192.168.x.x` private range (only checks `10.x`, `172.16-31`, `127.x`, `169.254.x`). | Security: browser tool can access LAN devices |
| B3 | `routers/system.py` | `/system_export` endpoint leaks secrets — raw config dump without filtering sensitive keys. | Security: API key exposure |
| B4 | `routers/setup.py` | `/setup/download` — SSRF via user-supplied URLs with no domain whitelist. | Security: arbitrary server requests |
| B5 | `services/kb_builder.py` | Missing sandbox check on directory-based KB build — could read outside workspace. | Security: path traversal |

### MEDIUM

| # | File | Bug | Impact |
|---|------|-----|--------|
| B6 | `services/cognitive_workspace.py` | Non-greedy JSON regex `r"\{[\s\S]*?\}"` matches wrong brace in nested output. | Incorrect JSON extraction for cognitive workspace queries |
| B7 | `services/file_lock.py` | `defaultdict` access not guarded by `_guard` lock — race condition on new keys. | Theoretical race (low probability) |
| B8 | `services/plan_executor.py` | Hardcoded `aspect_id: "morrigan"` — should use the operator's current aspect. | Plans always run as Morrigan |
| B9 | `services/model_manager.py` | `urllib.request` download with no timeout — could hang indefinitely. | Installer hangs on stalled connections |
| B10 | `layla/codex/linker.py` | Entity ID mismatch — linker generates different ID format than codex_db. | Double vector storage, orphaned links |
| B11 | `layla/scheduler/jobs.py` | Idle check uses type mismatch — comparing string to int for idle threshold. | Idle cleanup may not trigger |

---

## 2. FRONTEND BUGS (Confirmed)

### HIGH (User-visible breakage)

| # | File | Bug | Impact |
|---|------|-----|--------|
| F1 | `index.html` L523 | `_discoveryRunning` is a local var inside IIFE in `layla-pairing.js` — `onclick` handler always evaluates to `undefined` (falsy), so clicking always calls `startDiscovery()`, never `stopDiscovery()`. | Discovery toggle button is broken |
| F2 | `layla-artifacts.js` L140 | `laylaArtifactSendEdit()` targets `#input` / `#user-input` — actual textarea is `#msg-input`. | "Send edits" button does nothing |
| F3 | `layla-settings-full.js` L306-307 | `runKnowledgeIngest()` references `#ingest-path` and `#ingest-msg` — HTML uses `#km-source` and `#km-label`. | Knowledge Ingest button does nothing |
| F4 | `layla-settings-full.js` L236,254 | `refreshRelationshipCodex()` / `saveRelationshipCodex()` target `#codex-user-data` — HTML uses `#relationship-codex-json`. | Codex Load/Save buttons do nothing |
| F5 | CSS | Right panel (`#layla-right-panel`, 304px) has no collapse breakpoint — on screens < 900px, three-column layout crushes chat to zero. | App unusable on mobile/tablets |

### MEDIUM

| # | File | Bug | Impact |
|---|------|-----|--------|
| F6 | `sw.js` | Precache list stale — only 12 files, app loads 27+. Cache name (`layla-ui-v1`) never bumps. | Stale cache entries persist, missing offline files |
| F7 | `layla-settings-full.js` L290-291 | `saveAppearanceLite()` references `#app-font-size` / `#app-anim-level` — IDs don't exist. | Appearance settings save nothing |
| F8 | `layla-bootstrap.js` | innerHTML escaping misses `&` and `"` (only escapes `<` and `>`). | Minor XSS risk in fallback renderer |

### DEAD CODE

- `layla-app.js.bak` (180 KB) — entire pre-split monolith, should be removed
- `chat.js` — 193-byte placeholder, sets only `window.laylaChatModuleLoaded = true`
- Onboarding system in `layla-setup.js` (L306-356) — references DOM elements that no longer exist
- `loadPhoneAccess()` / `copyPhoneUrl()` — reference non-existent DOM IDs
- ASPECTS array duplicated in `layla-aspect.js` and `layla-wizard.js`

---

## 3. TEST COVERAGE

### Summary
- **164 test files**, **1,367 test functions**
- **116 of 171 service modules (68%) have NO dedicated test file**
- No always-pass tests, no hardcoded paths

### Critical Untested Services
| Category | Untested Modules |
|----------|-----------------|
| Core Infrastructure | `llm_gateway`, `context_manager`, `context_builder`, `prompt_builder`, `planner`, `plan_executor`, `plan_service`, `coordinator` |
| Memory Layer | `memory_router`, `memory_consolidation`, `retrieval`, `retrieval_cache`, `embedding_service` |
| Background Systems | `background_intelligence`, `initiative_engine`, `autonomy_optimizer` |
| Full Subsystems | `browser`, `stt`, `tts`, `shell_sessions`, `tunnel_manager`, `worktree_manager` |

### Flaky Risk
- `test_background_task_cancel.py` and `test_request_tracer.py` use `time.sleep()` with small values (5-50ms)
- `test_runtime_validation_plan.py` uses `time.sleep(0.25)` and subprocess timing
- `e2e_ui/test_ui_smoke.py` makes real HTTP calls

---

## 4. CONFIGURATION ISSUES

### Critical
- **Python version mismatch**: Venv runs **Python 3.14.3**; `pyproject.toml` caps at `<3.13`. The `outlines` package can't install, and Chroma/torch/sentence-transformers are unvalidated.

### Medium
- **106 undocumented config keys** referenced via `cfg.get("key")` throughout the codebase but missing from the canonical defaults dict in `runtime_safety.py`
- **Duplicate dependency**: `httpx` listed twice in `requirements.txt`
- **Heavy optional deps in main requirements**: `easyocr`, `torchao`, `yfinance`, `duckdb`, `bandit` are uncommented as if required, bloating install

### Config keys controlling non-existent features
- `llmlingua_compression_enabled` — LLMLingua not in requirements.txt
- `airllm_enabled` — AirLLM not in requirements.txt
- `syncthing_api_key` — Syncthing sync is scaffold-only
- `speculative_decoding_enabled` — partial support only

---

## 5. DOCUMENTATION DRIFT

- **Scripts README** (`agent/scripts/README.md`) omits 5 of 14 scripts
- **ROADMAP** marks Phases 0-6 complete but `topic_graph.py` (Phase 7.2), ContextCite (Phase 8.2), Selective Context (Phase 8.1) don't exist or are scaffold-only
- **SYSTEM_PLAN.md** lists debate/council/tribunal as MISSING — `debate_engine.py` now exists in services

---

## 6. OPEN-SOURCE INTEGRATION OPPORTUNITIES

### Quick Wins (Drop-in / Near Drop-in)

| Project | Replaces | Effort | Impact |
|---------|----------|--------|--------|
| **Ollama** | Manual model management in `llm_gateway` | Drop-in | Handles model downloads, GPU routing automatically |
| **Docling** (IBM) | PDF parsing in `kb_builder` / `doc_ingestion` | Drop-in | 97.9% table accuracy, MIT licensed, local-first |
| **Langfuse** | Manual observability in `services/observability.py` | Drop-in | Full LLM tracing, self-hosted, MIT |
| **HTMX + Alpine.js** | Hand-written AJAX in vanilla JS | Drop-in | 29KB combined, no build step, eliminates boilerplate |
| **Mem0** | Hand-built SQLite memory layer | Drop-in | Auto-extraction, deduplication, scoping |

### Strategic Upgrades (Moderate Effort, High Impact)

| Project | Replaces | Effort | Impact |
|---------|----------|--------|--------|
| **LanceDB** | ChromaDB | Moderate | Solves Python 3.13+ compatibility, truly embedded, Apache 2.0 |
| **nano-graphrag** | Manual KB graph building | Moderate | 800-line GraphRAG, hackable, MIT |
| **Whisper.cpp + Piper** | Current STT/TTS | Moderate | Full local voice pipeline, MIT, CPU-capable |
| **Pydantic AI** | Untyped tool calls | Moderate | Type-safe agent tool calls, structured outputs |
| **tree-sitter** | Regex-based code parsing | Moderate | Proper AST for 30+ languages |

### Longer-term Candidates

| Project | Purpose |
|---------|---------|
| **vLLM** | High-throughput multi-device inference |
| **LightRAG** | Graph-enhanced RAG at scale |
| **Letta (MemGPT)** | OS-inspired tiered memory |
| **DSPy** (Stanford) | Programmatic prompt optimization |
| **Guidance** (Microsoft) | Constrained generation for structured output |

---

## 7. IMPROVEMENT ROADMAP (Priority Order)

### Tier 1: Fix Now (Security + Breakage)
1. **Filter `/system_export`** — strip API keys, secrets from config dump
2. **Whitelist `/setup/download` domains** — only HuggingFace, approved mirrors
3. **Add `192.168.x.x` to SSRF filter** in `browser.py`
4. **Fix `_discoveryRunning` scope** — expose to `window` or use proper event handler
5. **Fix `#msg-input` references** in `layla-artifacts.js`
6. **Fix DOM ID mismatches** in `layla-settings-full.js` (ingest, codex, appearance)
7. **Fix `retrieval_cache.py` lock contention** — move fetcher outside lock with double-check pattern

### Tier 2: Stabilize (Correctness)
8. Fix `plan_executor.py` hardcoded aspect
9. Fix entity ID format mismatch in `codex/linker.py`
10. Fix `cognitive_workspace.py` JSON regex
11. Add download timeout to `model_manager.py`
12. Add mobile responsive collapse for right panel (CSS `@media` < 900px)
13. Fix service worker precache list and add cache-busting version
14. Consolidate all 106 undocumented config keys into `runtime_safety.py` defaults

### Tier 3: Quality (Coverage + Polish)
15. Add tests for core untested services (llm_gateway, context_manager, coordinator)
16. Remove dead code (layla-app.js.bak, chat.js, onboarding ghost code)
17. Deduplicate ASPECTS array between layla-aspect.js and layla-wizard.js
18. Update scripts README with all 14 scripts
19. Separate optional heavy deps into `requirements-extras.txt`
20. Fix Python version cap in pyproject.toml or validate 3.14 compatibility

### Tier 4: Open-Source Upgrades
21. Integrate Ollama as optional inference backend
22. Replace ChromaDB with LanceDB for 3.13+ compatibility
23. Add Langfuse for structured LLM observability
24. Adopt Docling for document ingestion
25. Evaluate HTMX + Alpine.js for frontend simplification

---

## 8. SERVICES NEVER CALLED FROM PRODUCTION CODE

| Module | Status |
|--------|--------|
| `services/tool_generator.py` | Stub — only imported by test |
| `services/capability_discovery.py` | Only imported by test |

---

## 9. ARCHITECTURAL NOTES

### Cross-cutting strengths
- **Lazy imports**: Extensive use of inline `from X import Y` inside function bodies prevents circular imports. This is the correct pattern.
- **Graceful degradation**: All optional dependencies (spaCy, elasticsearch, langfuse, OpenTelemetry, prometheus) are guarded by try/except.
- **No hardcoded credentials**: Config uses env vars (`LAYLA_DATA_DIR`) consistently.
- **XSS protection**: Main chat renderer uses DOMPurify with strict allow-list. `showToast` defaults to `textContent`.

### Cross-cutting concerns
- **~220 innerHTML assignments** across frontend JS — most properly escaped, but surface area for future XSS.
- **Global mutable state** in `shared_state.py` — callback refs set at startup. Fragile if `set_refs()` is never called.
- **Dual locking** in `llm_gateway.py` — both `_llm_lock` (RLock) and `LLMRequestQueue` coexist for legacy sync + async paths.

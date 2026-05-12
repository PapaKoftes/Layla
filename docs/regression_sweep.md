# Git History Regression Sweep

**Date:** 2026-05-12  
**Scope:** Full `git log --diff-filter=D` across all history for `agent/**/*.py`  
**Deleted files found:** 6  
**Feature regressions:** 0

---

## Methodology

Searched the complete git history for any Python file under `agent/` that was ever deleted.
For each, examined the file content at the commit before deletion, checked whether the
functionality was consolidated elsewhere, and assessed whether any features were lost.

All 6 files were deleted in commit `75229a4` ("consolidation: outcome_writer, SQLite
barrel+migrations, engineering pipeline kwargs, codex/study/sandbox/UI fixes, docs archive").

---

## Findings

### 1. `agent/core/loop.py` — **Stub, no regression**

- **Content:** Empty module with docstring: "Status: extraction in progress; do not assume the 6-phase pipeline is implemented here"
- **LOC:** ~10 (imports + docstring only)
- **Functionality:** None — was a planned extraction target for the agent loop, never implemented
- **Current home:** `agent/agent_loop.py` contains the full execution loop
- **Verdict:** ✅ Safe deletion. Stub never held real logic.

### 2. `agent/services/context_builder.py` — **Stub, no regression**

- **Content:** Docstring + logger only: "Delegates to agent_loop._build_system_head for now; can be fully extracted later."
- **LOC:** ~8
- **Functionality:** None — was a planned extraction point
- **Current home:** Context building lives in `agent_loop.py` `_build_system_head()` and `services/context_manager.py`
- **Verdict:** ✅ Safe deletion. Empty placeholder.

### 3. `agent/services/decision_engine.py` — **Consolidated into agent_loop.py, no regression**

- **Content:** `classify_intent(goal)` function (~70 LOC) — keyword-based heuristic that maps user goals to tool names
- **LOC:** ~80
- **Functionality:** Intent classification for tool routing
- **Current home:** `agent/agent_loop.py` line 2972 contains an identical `classify_intent()` function, plus the more sophisticated `_ask_model_for_decision()` at line 2607
- **Verified:** All 4 call sites resolve to the consolidated version in `agent_loop.py`
- **Verdict:** ✅ Intentional consolidation. No feature loss.

### 4. `agent/services/integration_sandbox.py` — **Replaced by sandbox_validator.py, no regression**

- **Content:** Full sandbox evaluation pipeline (~160 LOC): create isolated venv → pip install → import test → benchmark
- **LOC:** ~160
- **Functionality:** Isolated venv creation, package installation, compatibility testing, benchmarking
- **Current home:** `agent/services/sandbox_validator.py` provides the same capabilities (validate imports in subprocess + run benchmarks) without the venv isolation overhead
- **Key difference:** Old version created a fresh virtualenv per evaluation; new version runs subprocess import checks against the existing environment. For a local-first system this is the right tradeoff — venv creation was ~60s overhead per evaluation.
- **Verdict:** ✅ Intentional simplification. Core capability (validate + benchmark) preserved.

### 5. `agent/services/self_improvement.py` (old version) — **Replaced with production version, no regression**

- **Content:** LLM-powered codebase analysis (~180 LOC): `analyze_codebase()`, `propose_improvements()`, `evaluate_capabilities()`, `detect_missing_capabilities()`, `propose_capability_integrations()`
- **LOC:** ~180
- **Functionality:** Codebase analysis, capability evaluation, LLM-generated improvement proposals
- **Current home:** `agent/services/self_improvement.py` (rewritten) provides deterministic proposal generation, config-based application with an allowlist, and DB persistence via `layla/memory/improvements.py`. Router at `routers/improvements.py` wires the full CRUD.
- **Key difference:** Old version used LLM to generate ad-hoc suggestions from codebase scans; new version is deterministic, safe-by-default, and operator-approved. The old `evaluate_capabilities()` / `detect_missing_capabilities()` scanning functions were removed as they depended on modules (`capabilities.registry`, `capability_discovery`) that don't exist in the current codebase.
- **Verdict:** ✅ Intentional rewrite. More robust, no phantom imports.

### 6. `agent/services/tool_orchestrator.py` — **Stub, no regression**

- **Content:** Docstring + logger only: "Tool dispatch, approval flow, verification."
- **LOC:** ~8
- **Functionality:** None — was a planned extraction point
- **Current home:** Tool dispatch lives in `agent/agent_loop.py` and `layla/tools/registry.py`
- **Verdict:** ✅ Safe deletion. Empty placeholder.

---

## Summary

| File | LOC | Status | Regression? |
|------|-----|--------|-------------|
| `core/loop.py` | ~10 | Stub (empty) | ❌ No |
| `services/context_builder.py` | ~8 | Stub (empty) | ❌ No |
| `services/decision_engine.py` | ~80 | Consolidated into `agent_loop.py` | ❌ No |
| `services/integration_sandbox.py` | ~160 | Replaced by `sandbox_validator.py` | ❌ No |
| `services/self_improvement.py` (old) | ~180 | Rewritten with production version | ❌ No |
| `services/tool_orchestrator.py` | ~8 | Stub (empty) | ❌ No |

**Conclusion:** Zero feature regressions found. All deletions were either empty stubs or intentional consolidations where the functionality was preserved or improved in the replacement code.

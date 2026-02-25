# Layla extension implementation summary

All eight phases implemented with **backward compatibility**, **optional** fields, and **no breaking changes**. Existing behavior preserved when new fields are absent.

---

## Files modified

| File | Changes |
|------|--------|
| **agent/orchestrator.py** | `get_decision_bias(aspect)`, `should_deliberate(message, aspect)` optional aspect param and bias-based depth; bias influences deliberation threshold. |
| **agent/agent_loop.py** | `_load_learnings(aspect_id)` for recall weighting; `_write_pending` adds `risk_level`; `_build_system_head` injects `.identity/self_model.md` for Lilith only; `_llm_decision` adds `bias_hint` from `get_decision_bias`; both `should_deliberate` call sites pass `active_aspect`. |
| **agent/jinx/memory/db.py** | Optional column `learning_type` (migration + backfill); `save_learning` writes `learning_type`; `get_recent_learnings(n, aspect_id=None)` with aspect-based ordering (Echo→preference, Morrigan→strategy, Nyx→fact). Optional column `momentum_score` on `study_plans` (migration). |
| **agent/jinx/memory/vector_store.py** | `_parse_knowledge_front_matter(text)`; `index_knowledge_docs` parses front matter (priority/domain), stores metadata, skips `.identity`; `get_knowledge_chunks` fetches 3*k and sorts by priority (core > support > flavor). |
| **agent/runtime_safety.py** | `_knowledge_priority_from_text`; `load_knowledge_docs` sorts by priority and skips `.identity`. |
| **agent/research_stages.py** | `STAGE_ORDER` includes `contradiction_check` between verification and distillation; `SUBDIRS` + `STAGE_TO_SUBDIR`; `load_research_context` loads contradiction output for distillation/synthesis; `run_contradiction_check_stage`; `STAGE_RUNNERS["contradiction_check"]`. |
| **agent/jinx/tools/registry.py** | Each tool entry has `risk_level`: low (read/git/fetch/file_info), medium (write_file, apply_patch), high (shell, run_python). |
| **personalities/morrigan.json** | `decision_bias`, `failure_mode`. |
| **personalities/nyx.json** | `decision_bias`. |
| **personalities/echo.json** | `decision_bias`. |
| **personalities/eris.json** | `decision_bias`. |
| **personalities/lilith.json** | `failure_mode`. |

---

## New schema fields

| Location | Field | Default / note |
|----------|--------|-----------------|
| **Personality JSON** | `decision_bias: string[]` | Optional. e.g. `["efficient","risk_averse"]`. |
| **Personality JSON** | `failure_mode: string` | Optional. Store only (e.g. `"over-correct"`, `"refuse"`). |
| **Knowledge doc front matter** | `priority: core \| support \| flavor` | Default `support` if missing. |
| **Knowledge doc front matter** | `domain: string` | Optional. |
| **learnings table** | `learning_type` | `fact` \| `preference` \| `strategy` \| `identity`. Existing rows backfilled from `type`; new saves set explicitly. |
| **study_plans table** | `momentum_score` | REAL DEFAULT 0. Store + expose only. |
| **Pending approval entry** | `risk_level` | From TOOLS registry when writing; exposed in GET /pending. |
| **TOOLS registry** | `risk_level` | `low` \| `medium` \| `high` per tool. |

---

## Research stage integration

- **New stage:** `contradiction_check`
- **Order:** `mapping` → `investigation` → `verification` → **`contradiction_check`** → `distillation` → `synthesis`
- **Output:** `.research_brain/contradictions/check.md`
- **Context:** Reads map, investigation, verification; compares key claims, detects conflicts, annotates uncertainty, surfaces confidence.
- **Depth logic:** `stages_for_depth("map"|"deep"|"full")` and `FULL_PIPELINE_ORDER` include `contradiction_check` in base pipeline.

---

## New file

| Path | Purpose |
|------|--------|
| **.identity/self_model.md** | System goals, limits, growth direction. Loaded only when aspect is Lilith; excluded from RAG and from `knowledge/` indexing. |

---

## Confirmation of zero-breaking changes

- **Aspects without `decision_bias`:** `get_decision_bias` returns `[]`; prompt and deliberation unchanged.
- **Aspects without `failure_mode`:** Loaded as-is; no logic uses it.
- **Knowledge docs without front matter:** `priority = "support"`; same retrieval behavior as before when all are support.
- **Learnings:** Table may lack `learning_type` on first run; migration adds it and backfills. `save_learning` falls back to 4-column INSERT if 5-column fails. `get_recent_learnings(n)` (no aspect) unchanged; with aspect, ordering prefers type when column exists.
- **Study plans:** `momentum_score` added by migration; `get_active_study_plans()` returns it when present; no writes to it yet.
- **Approvals:** Existing pending entries without `risk_level` still valid; new entries include `risk_level`. Approval logic unchanged.
- **Research:** All existing depth presets (map, deep, full) run the new order including `contradiction_check`; runners keyed by name.

**Tests:** 16/16 passed (test_agent_loop, test_e2e_agent, test_completion).

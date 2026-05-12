# AI Handoff Report — Total State After Recent Changes

**Purpose:** Full state report for another AI to continue work. Read this first, then AGENTS.md, ARCHITECTURE.md, docs/IMPLEMENTATION_STATUS.md.

**Date:** 2025-03-14

**Also see:** `AGENTS.md` (operations manual), `ARCHITECTURE.md` (request flow)

---

## 1. Project Summary

**Layla** is a self-hosted AI companion and engineering agent:
- Local GGUF via llama-cpp-python (no cloud, no API keys)
- 6 personality aspects (Morrigan, Nyx, Echo, Eris, Lilith, Cassandra)
- 195 registered tools (`EXPECTED_TOOL_COUNT` in `agent/tests/test_registered_tools_count.py`), SQLite + ChromaDB memory, voice I/O, browser automation
- FastAPI at `localhost:8000`, Web UI at `/ui`
- Approval gate for writes/execution; non-autonomous by design

**Source of truth:** `LAYLA_NORTH_STAR.md` (do not modify unless operator asks)

---

## 2. Recent Changes (This Session)

### 2.1 Test Flakiness Fix

**Problem:** `test_pre_read_probe_runs_only_once_per_path` failed when run in full suite (71 tests) but passed alone.

**Root cause:** `system_overloaded()` in `agent_loop.py` returns True when CPU/RAM exceeds thresholds. Earlier tests load sentence-transformers, ChromaDB, torch → CPU/RAM spike → third test sees "overloaded" → `autonomous_run` returns early with `status: "system_busy"`, `steps: []`.

**Fix applied:**
- Mock `system_overloaded` to return `False` in all three pre_read_probe tests:
  - `test_pre_read_probe_inserts_file_info_before_read`
  - `test_pre_read_probe_avoids_binary_reads`
  - `test_pre_read_probe_runs_only_once_per_path`

### 2.2 Test Hardening

- **`_minimal_cfg`** (in `agent/tests/test_agent_loop.py`): Added `planning_enabled: False`, `max_tool_calls: 10` for deterministic tests.
- **Sandbox reset:** Added `set_effective_sandbox(None)` in `test_pre_read_probe_avoids_binary_reads` and `test_pre_read_probe_runs_only_once_per_path` to clear thread-local state.

### 2.3 New Documentation

- **`docs/DEBUG_AND_UPGRADE_ANALYSIS.md`** — Debug findings, OSS upgrade opportunities, deprecation notes.
- **`docs/IMPLEMENTATION_STATUS.md`** — Added "Debug & upgrade analysis" section linking to DEBUG_AND_UPGRADE_ANALYSIS.md.

---

## 3. Files Modified

| File | Changes |
|------|---------|
| `agent/tests/test_agent_loop.py` | `system_overloaded` mock in 3 tests; `_minimal_cfg` + `planning_enabled`/`max_tool_calls`; `set_effective_sandbox(None)` in 2 tests; removed duplicate `max_tool_calls` |
| `docs/DEBUG_AND_UPGRADE_ANALYSIS.md` | **New** — Debug report, OSS upgrades, deprecations |
| `docs/IMPLEMENTATION_STATUS.md` | Link to DEBUG_AND_UPGRADE_ANALYSIS.md |
| `docs/AI_HANDOFF_REPORT.md` | **New** — This handoff report |
| `AGENTS.md` | Quick orientation: added pointer to `docs/AI_HANDOFF_REPORT.md` for resuming AI sessions |

---

## 4. Test Suite State

- **71 tests pass** (run with `-m "not slow"` to exclude live-LLM test)
- **1 test deselected:** `test_completion_report` (marked `@pytest.mark.slow`, needs real LLM)
- **Command:** `cd agent && python -m pytest tests/ -m "not slow" -q`
- Pre_read_probe tests are stable across full suite.

---

## 5. Known Warnings (Non-blocking)

- **torchao prototype imports** — Deprecation warnings from torchao.dtypes; track upstream.
- **ChromaDB Pydantic V1** — Compatibility warning on Python 3.14+; track upstream.

---

## 6. Phase B — Intelligence Systems (Implemented)

- **Conversation summary embeddings** — `embedding_id` column; summaries participate in retrieval via ChromaDB.
- **Graph reasoning** — `services/graph_reasoning.py`: spaCy entity extraction, networkx graph expansion; integrated into retrieval.
- **Code intelligence** — `workspace_index.py`: tree-sitter extracts functions, classes, imports, call graph.
- **Parallel agent roles** — `task_graph.py`: `run_parallel_ready()`, `run_until_complete_parallel()`; TaskNode.role.

## 7. Phase A — Runtime Stability (Implemented)

- **Torch quantization** — Removed deprecated torch.quantization fallback; torchao only, skip when unavailable.
- **pytest asyncio_mode** — Moved to pyproject.toml; PytestConfigWarning suppressed.
- **Conversation summary memory** — `conversation_summaries` table; persist on compress, recall in system head.

## 7. OSS Upgrade Opportunities (Phase 1 — Implemented)

| Priority | Component | Status | Notes |
|----------|-----------|--------|-------|
| High | Tool-call JSON | **Done** | instructor with JSON_SCHEMA mode for local Llama |
| High | Token counting | **Done** | tiktoken in `services/token_count.py` |
| High | LLM backends | **Done** | inference_router: llama_cpp, openai_compatible (vLLM), ollama |
| Medium | Vector search | ChromaDB | faiss-cpu | Already in capability registry |
| Medium | Summarization | LLM-based | **sumy** | Extractive, lightweight |

---

## 9. Hard Rules (Never Violate)

1. Never commit `agent/runtime_config.json`, `layla.db`, or `knowledge/` (except explicit .gitignore exceptions).
2. Never hardcode paths; use `Path(__file__).resolve().parent` and `.expanduser().resolve()`.
3. Never break approval gate for `write_file`, `apply_patch`, `shell`, `run_python`.
4. Never hardcode aspect list; use `_load_aspects()` from `orchestrator.py`.
5. DB schema: migrate forward only; add columns in `migrate()` in `agent/layla/memory/db.py`.
6. Update `ARCHITECTURE.md` and `docs/IMPLEMENTATION_STATUS.md` when changing flow or implementing North Star sections.

---

## 10. Key Paths for Next AI

| Need | Path |
|------|------|
| Operations manual | `AGENTS.md` |
| Request flow | `ARCHITECTURE.md` |
| North Star mapping | `docs/IMPLEMENTATION_STATUS.md` |
| Capability domains | `docs/LAYLA_PREBUILT_PLATFORM.md` |
| Debug & upgrades | `docs/DEBUG_AND_UPGRADE_ANALYSIS.md` |
| Agent loop | `agent/agent_loop.py` (~2207 lines) |
| Tools registry | `agent/layla/tools/registry.py` |
| Config | `agent/runtime_config.json` (gitignored), `agent/runtime_config.example.json` |

---

## 11. Git Status (At Report Time)

From conversation start:
- Modified: `.gitignore`, `agent/services/study_service.py`, `conversation_history.json`
- Untracked: `_audit.py`, `_ci_commit_msg.txt`, `_commit_msg.txt`, `_fix_lint.py`, `_msg2.txt`, `_sprint2_endpoints.py`, `agent/runtime_config.json.bak`, `agent/services/context_manager.py`, `agent/services/graph_learning.py`, `agent/services/intent_detection.py`, `agent/services/learning_filter.py`

**New/Modified this session:** `agent/tests/test_agent_loop.py`, `docs/DEBUG_AND_UPGRADE_ANALYSIS.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/AI_HANDOFF_REPORT.md` (this file).

---

## 12. Quick Start for Next AI

1. Read `AGENTS.md` (repo map, hard rules).
2. Read `ARCHITECTURE.md` (request flow).
3. Run tests: `cd agent && python -m pytest tests/ -m "not slow" -q`.
4. Check `docs/DEBUG_AND_UPGRADE_ANALYSIS.md` for open work (instructor, torch migration, etc.).
5. Do not modify `LAYLA_NORTH_STAR.md` unless explicitly asked.

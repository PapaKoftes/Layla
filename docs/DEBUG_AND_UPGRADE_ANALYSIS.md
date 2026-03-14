# Debug & Upgrade Analysis

Analysis from thorough debug, research, and OSS upgrade review. See [LAYLA_PREBUILT_PLATFORM.md](LAYLA_PREBUILT_PLATFORM.md) for capability domains and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for North Star mapping.

---

## 1. Debug: Test Flakiness Fixed

### Issue

`test_pre_read_probe_runs_only_once_per_path` failed intermittently when run in the full suite (71 tests) but passed when run alone or with only the other pre_read_probe tests.

### Root Cause

**`system_overloaded()`** in `agent_loop.py` returns `True` when CPU or RAM usage exceeds config thresholds. The first two pre_read_probe tests load heavy dependencies (sentence-transformers, ChromaDB, torch) which spike CPU/RAM. By the third test, the system is still considered "overloaded", so `autonomous_run` returns early with `status: "system_busy"` and `steps: []` before any tool loop runs.

### Fix

Mock `system_overloaded` to return `False` in all three pre_read_probe tests so the agent loop always runs:

```python
monkeypatch.setattr(agent_loop, "system_overloaded", lambda: False)
```

### Additional Test Hardening

- Added `planning_enabled: False` and `max_tool_calls: 10` to `_minimal_cfg` for deterministic tests
- Added `set_effective_sandbox(None)` in tests that patch tools to reset thread-local state

---

## 2. OSS Upgrade Opportunities

### High Impact — Implemented (Phase 1)

| Component | Status | Implementation |
|-----------|--------|----------------|
| **Tool-call JSON** | Done | instructor with JSON_SCHEMA in `_llm_decision` (agent_loop.py) |
| **Token counting** | Done | tiktoken in `services/token_count.py`; context_manager uses it |
| **LLM backends** | Done | inference_router: llama_cpp, openai_compatible (vLLM), ollama |
| **torch quantization** | Done | torchao in vector_store.py with torch fallback |

### Medium Impact

| Component | Current | OSS Upgrade | Benefit |
|-----------|---------|-------------|---------|
| **Vector search** | ChromaDB | faiss-cpu (already in registry) | Faster ANN when ChromaDB is bottleneck |
| **Embeddings** | nomic-embed-text, all-MiniLM | BGE, E5 (sentence-transformers) | Quality/performance tradeoffs |
| **Summarization** | LLM-based | [sumy](https://github.com/miso-belica/sumy) | Lightweight extractive summarization for long convos |

### Lower Priority

- **tree-sitter** — Multi-language AST (Python, JS, TS, Go, Rust)
- **crawl4ai** — Async web crawler (alternative to trafilatura)
- **ruff** — Fast Python linter (promote for code_lint)

---

## 3. Deprecation Warnings to Address

### torch.ao.quantization — Addressed

`vector_store.py` now uses torchao with torch fallback. torch.quantization.quantize_dynamic deprecated path resolved.

### ChromaDB / Pydantic V1

ChromaDB uses Pydantic V1; Python 3.14+ shows compatibility warnings. Track ChromaDB upstream for Pydantic V2 migration.

---

## 4. Test Suite Notes

- **71 tests** pass (excluding `@pytest.mark.slow` which requires live LLM)
- `test_completion_report` is slow and hits real LLM; run with `-m "not slow"` for CI
- Pre_read_probe tests now stable across full suite

---

## 5. Recommended Next Steps

1. ~~**instructor**~~ — Done. Grammar-constrained tool JSON in `_llm_decision`.
2. **system_overloaded** — Consider raising thresholds or adding a "test mode" that skips the check when config indicates test environment
3. ~~**torch quantization**~~ — Done. Migrated to torchao in vector_store.py.

---

## Related Documents

- [LAYLA_PREBUILT_PLATFORM.md](LAYLA_PREBUILT_PLATFORM.md) — Capability domains, OSS foundations
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) — North Star mapping, missing components
- [AGENTS.md](../AGENTS.md) — Hard rules, repo map

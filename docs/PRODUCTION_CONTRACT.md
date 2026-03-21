# Production contract — Layla

This document defines what operators can rely on when running Layla in a **production-minded** configuration. It maps guarantees to code, config keys, and tests.

For release verification steps, see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).  
Repository rules for humans and AIs: [RULES.md](RULES.md).

---

## 1. Determinism (behavioral)

**Guaranteed (within local inference limits):**

- **Bounded tool loop**: Optional detection blocks repeated / ping-pong tool patterns when `tool_loop_detection_enabled` is true (`services/tool_loop_detection.py`, `agent_loop.autonomous_run`). Per-run duplicate tool invocations are suppressed.
- **Structured decision path**: JSON decision schema and tool gating (`decision_schema.py`, `agent_loop.py`) — no silent infinite agent loops beyond configured `max_tool_calls` and `max_runtime_seconds`.

**Best-effort (not strict determinism):**

- LLM sampling: `temperature`, `top_p`, `top_k` affect variance. Lower `temperature` (default in `runtime_safety.load_config()` defaults) improves repeatability; outputs are still not bitwise-identical across runs.
- Hardware and driver timing may change latency and occasional numerical differences.

**Config:** `temperature`, `tool_loop_detection_enabled`, `tool_loop_*` thresholds — see `agent/runtime_config.example.json` and [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md).

---

## 2. Bounded cost

**Guaranteed:**

- **Max tool calls per request**: `max_tool_calls` (research missions: `research_max_tool_calls`).
- **Max runtime per request**: `max_runtime_seconds` (research: `research_max_runtime_seconds`). Light chat may further cap via `chat_light_max_runtime_seconds` in the agent loop.
- **Max completion tokens**: `completion_max_tokens`.

**Runtime scaling:** `services/system_optimizer.get_effective_config()` may lower `max_tool_calls` and context under `performance_mode` or CPU/RAM pressure — effective values are surfaced on **`GET /health`** in `effective_limits`.

**Note:** The correct key is **`max_runtime_seconds`**, not `max_run_time_seconds`.

---

## 3. Safety invariants

**Guaranteed (when `safe_mode` / approval gates are active as designed):**

- **No writes without approval** (or explicit `allow_write` + governance): tools that mutate the filesystem or run code return `approval_required` until `POST /approve` / MCP approve / CLI approve.
- **Sandbox and path policy**: `sandbox_root`, protected paths, research lab boundaries — enforced in `runtime_safety` and tools (`layla/tools/registry.py`).
- **No arbitrary shell/exec without gates**: `shell` / `run_python` and related paths respect `allow_run`, approval, timeouts, and optional allowlists.

**Tests:** `agent/tests/test_approval_flow.py`, `agent/tests/test_sandbox.py`, and related agent loop tests.

**Ethics layer:** [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md).

---

## 4. Observability

**`GET /health`**

- **Model**: `model_loaded`, optional `model_error`; `model_routing` when available; **`active_model`** (basename of configured GGUF, no full path).
- **Routing / limits**: `model_routing`, **`effective_limits`** (effective `max_tool_calls`, `max_runtime_seconds`, token cap, cache flags, `tool_loop_detection_enabled`, `performance_mode`).
- **Effective snapshot**: **`effective_config`** — whitelisted, non-secret config keys plus **`effective_caps`** (numeric limits merged from `system_optimizer.get_effective_config`). **`features_enabled`** — booleans for chroma, caches, tool-loop detection, scheduler study, voice toggles, planning.
- **Dependencies**: **`dependencies`** — per-component `ok` | `missing` | `error` (and `none`/`unknown` for GPU) for `llama_cpp`, `chroma`, `voice_stt`, `voice_tts`, `tree_sitter`, `gpu`. With **`?deep=true`**, Chroma runs an embed + vector search probe (same as legacy `chroma_ok`); shallow calls only assert import / light checks for Chroma.
- **Knowledge index**: `knowledge_index_ready`, `knowledge_index_status`, optional `knowledge_index_error` (from app startup / indexing).
- **Caches**: `cache_stats` (completion cache hits/misses); **`response_cache_stats`** when response caching is used.
- **Other**: `system_optimizer`, `token_usage`, `vector_store`, `tools_registered`, etc.

**`GET /health/deps`**

- Returns `{ "dependencies": { ... } }` only (optional **`?deep=true`** for Chroma vector probe). For scripts and MCP clients that want a minimal payload.

**Logs (`layla` logger)**

- **Tool outcomes**: `INFO` lines with tool name, `ok`, and `reason` after tool execution (via validated tool paths).
- **Fallbacks**: e.g. semantic memory path logs Chroma failure at `WARNING` and successful FTS retrieval fallback at `INFO`.

---

## 5. Reasoning depth vs "reasoning_default"

There is no config key named `reasoning_default`. Reasoning depth is:

- **Classified per turn**: `services/reasoning_classifier.py` → `none` | `light` | `deep`.
- **Capped under load**: e.g. `performance_mode: low` downgrades `deep` to `light` in the agent loop.

Baseline behavior is **light-oriented** for normal turns; coding-heavy text tends to classify as **deep**.

---

## 6. Default config aligned with public release

See merged defaults in `agent/runtime_safety.py` and the annotated template `agent/runtime_config.example.json`. Typical production-oriented defaults include:

- `performance_mode`: `"auto"`
- `max_tool_calls`: tightened (e.g. `2`) — raise for heavy coding sessions if needed.
- `max_runtime_seconds`: bounded (e.g. `30`)
- `completion_cache_enabled` / `response_cache_enabled`: enabled when duplicate-turn latency should drop (tradeoff: cached replies for identical prompts).
- `learning_quality_gate_enabled`: `true`
- `auto_pip_install_optional`: `false`
- `tool_loop_detection_enabled`: `true` for loop hygiene

---

## Revision

When request limits, `/health` shape, or safety gates change, update this file and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

# 03 -- LLM Gateway & Reasoning Subsystem

> Design document for the Layla AI inference pipeline: model loading, completion
> routing, caching, reasoning strategies, multi-provider support, and output
> processing.

| Attribute | Value |
|-----------|-------|
| Status | Living document |
| Last updated | 2026-05-24 |
| Covers | `agent/services/llm_gateway.py`, `inference_router.py`, `litellm_gateway.py`, `llm_decision.py`, `cognitive_workspace.py`, `reasoning_strategies.py`, `structured_gen.py`, `completion_cache.py`, `response_cache.py`, `token_count.py`, `model_manager.py`, `model_benchmark.py`, `model_recommender.py`, `model_router.py`, `prompt_tier_budget.py`, `output_polish.py`, `output_quality.py`, `style_profile.py`, `agent_loop_formatting.py`, `provider_health.py`, `airllm_runner.py`, `system_head_builder.py` |

---

## 1. Architecture Overview

The LLM subsystem is organized as a layered pipeline. Each layer has a single
responsibility and a well-defined interface to the layers above and below it.

```
                    +---------------------------+
                    |  Callers (agent_loop,      |
                    |  planner, research, tools) |
                    +----------+----------------+
                               |
                    run_completion(prompt, ...)
                    run_completion_async(prompt, ...)
                               |
                    +----------v----------------+
                    |   llm_gateway.py           |  <-- single public entry point
                    |   (token tracking, cache,  |
                    |    model override, retry,   |
                    |    litellm delegation)      |
                    +----------+----------------+
                               |
              +----------------+----------------+
              |                                 |
   litellm_enabled?                    inference_router.py
              |                         (backend detection)
   +----------v----------+      +------+--------+--------+
   | litellm_gateway.py  |      | llama_cpp | openai | ollama |
   | (multi-provider,    |      | (local    | _compat| (HTTP  |
   |  failover, circuit  |      |  GGUF)    | (HTTP) | 11434) |
   |  breaker)           |      +-----------+--------+--------+
   +---------------------+
                                        |
                              +---------v---------+
                              | model_router.py    |
                              | (task classification|
                              |  -> model selection)|
                              +--------------------+
```

### Decision path for a single `run_completion()` call

1. **Cache check** -- If `completion_cache_enabled` and prompt < 12 KB,
   look up SHA-256 hash of `(routing_tag, model_name, temperature,
   max_tokens, prompt)`. Return immediately on hit.
2. **LiteLLM gate** -- If `litellm_enabled`, delegate to
   `litellm_gateway.complete()` which handles provider failover and
   circuit-breaker checks. On failure, fall through to local inference.
3. **Backend routing** -- `inference_router.run_completion()` examines
   `inference_backend` config (auto-detected from URL patterns when set
   to `"auto"`). Routes to one of four backends: `llama_cpp`,
   `openai_compatible`, `ollama`, or `litellm`.
4. **Model selection** -- For local `llama_cpp`, `_effective_model_filename()`
   resolves the GGUF basename via a priority chain: ContextVar override >
   dual-model routing > task classification > `model_filename` default.
5. **Generation** -- The selected backend runs the completion. For
   `llama_cpp`, the model is loaded (or retrieved from the
   `_llm_by_path` cache) and `Llama.create_completion()` is called
   under an inference lock.
6. **Post-processing** -- Token counts are tracked, the result is
   optionally cached, and Prometheus metrics are recorded.

### Concurrency model

| Path | Mechanism | Notes |
|------|-----------|-------|
| Async callers (`/agent`, SSE) | `LLMRequestQueue` (asyncio queue, single worker task) | Serializes all async completions; `run_in_executor` bridges to the sync `run_completion`. |
| Sync callers (prewarm, benchmark) | `llm_serialize_lock` (`threading.RLock`) | Legacy path; same object as `_llm_lock`. |
| Per-workspace isolation | `llm_generation_lock` (`threading.Lock`) | Used when `llm_serialize_per_workspace` is true; prevents two workspaces from calling `create_completion` concurrently on the same process. |
| Per-workspace agent runs | `get_agent_serialize_lock(workspace_key)` | Returns a per-workspace `RLock` keyed by resolved workspace path. |

---

## 2. Model Loading and Management

### 2.1 Local GGUF loading (`llm_gateway._get_llm`)

The `_get_llm()` function is the sole path for obtaining a `llama_cpp.Llama`
instance. It implements:

- **Path-keyed cache** -- `_llm_by_path: dict[str, Llama]` maps resolved
  model paths to loaded instances. A fast path without the lock checks
  this dict first to avoid deadlock during nested completions
  (reflection, critic).
- **Hardware auto-config** -- Thread counts default to `psutil` physical
  cores minus one, capped at 16. Batch threads default to `2x` physical
  threads, capped at logical CPU count.
- **Fallback chain** -- If the routed model GGUF is missing, the loader
  walks `model_fallback_chain` (config list) and then tries
  `model_filename` (default).
- **Speculative decoding** -- When `speculative_decoding_enabled` (default
  true), `LlamaPromptLookupDecoding` is attached as `draft_model`.
  A workaround resizes the `scores` array when a known
  llama-cpp-python bug causes shape mismatches.
- **Flash attention + KV quantization** -- `flash_attn=True` and
  `type_k=type_v=8` (Q8_0) are defaults, halving VRAM for long contexts.
- **Rope scaling** -- Optional `rope_freq_base` and `rope_freq_scale`
  for extended-context models.
- **Benchmark on load** -- When `benchmark_on_load` is true, runs
  `model_benchmark.run_benchmark()` immediately after loading.

Key configuration keys for model loading:

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `model_filename` | str | `"your-model.gguf"` | Primary GGUF basename |
| `models_dir` | str | `~/.layla/models` | Directory containing GGUF files |
| `n_ctx` | int | `4096` | Context window size |
| `n_batch` | int | `512` | Batch size for prompt eval |
| `n_gpu_layers` | int | `-1` | GPU layers (-1 = all) |
| `n_threads` | int | auto | Inference threads |
| `n_threads_batch` | int | auto | Batch processing threads |
| `n_keep` | int | `512` | Tokens pinned in KV cache |
| `use_mlock` | bool | `false` | Lock model in RAM |
| `use_mmap` | bool | `true` | Memory-map model file |
| `flash_attn` | bool | `true` | Flash attention |
| `type_k` / `type_v` | int | `8` | KV cache quantization type |
| `speculative_decoding_enabled` | bool | `true` | Prompt-lookup speculative decoding |
| `speculative_num_pred_tokens` | int | `10` | Prediction window for speculative decoding |
| `rope_freq_base` | float | (none) | RoPE frequency base override |
| `rope_freq_scale` | float | (none) | RoPE frequency scale override |
| `model_fallback_chain` | list | `[]` | Fallback GGUF basenames |
| `benchmark_on_load` | bool | `false` | Run benchmark after loading |

### 2.2 Hot-swap and invalidation

`invalidate_llm_cache()` clears both `_llm` (legacy singleton) and
`_llm_by_path` (multi-model cache). The next `_get_llm()` call reloads
from disk. This is triggered by:

- KV cache corruption (broadcast/shape errors in `create_completion`)
- Local timeout (the completion ThreadPoolExecutor times out)
- Admin API calls

There is no reference-counting or graceful draining -- the old `Llama`
object is simply dropped and the Python GC frees the C++ resources. This
means in-flight completions on the old instance will crash or produce
corrupt output if they race with invalidation.

### 2.3 Model manager (`model_manager.py`)

Provides a user-facing model catalog and lifecycle:

- **`MODELS_CATALOG`** -- Five pre-defined HuggingFace GGUF entries
  (Dolphin-Mistral-7B, Dolphin-Llama3-8B, Hermes-3-8B, Phi-3-Mini,
  Dolphin-Llama3-70B) with download URLs and RAM requirements.
- **`install_model(name)`** -- Downloads a GGUF by catalog key or direct
  URL using `urllib.request.urlretrieve` with progress callback.
- **`list_models()`** -- Enumerates `*.gguf` files in the models
  directory with sizes.
- **`select_best_model()`** -- Uses `model_recommender` hardware
  detection to score installed models against the recommended tier.

### 2.4 Model recommender (`model_recommender.py`)

Rule-based recommendations using VRAM/RAM thresholds:

| VRAM / RAM | Tier | Recommended model |
|------------|------|-------------------|
| >= 48 GB VRAM or >= 64 GB RAM | large | Qwen2.5-72B Q4_K_M |
| >= 24 GB VRAM or >= 48 GB RAM | large | Qwen2.5-32B Q4_K_M |
| >= 16 GB VRAM or >= 32 GB RAM | medium-large | Qwen2.5-14B Q5_K_M |
| >= 8 GB VRAM or >= 16 GB RAM | medium | Qwen2.5-7B Q5_K_M |
| >= 6 GB VRAM | medium | Qwen2.5-7B Q4_K_M |
| >= 4 GB VRAM or >= 8 GB RAM | small | Phi-3.5-mini Q4_K_M |
| >= 2 GB VRAM | small | Llama-3.2-3B Q4_K_M |
| CPU-only / low | tiny | Llama-3.2-1B Q8_0 |

### 2.5 Model benchmark (`model_benchmark.py`)

Measures tokens/sec, first-token latency, and process RSS. Results are
persisted to `~/.layla/benchmarks.json`. Used by `model_router.select_model()`
for latency-aware routing and by `select_fastest_model()` for tie-breaking.

The benchmark prompt is a repeated pangram (`"The quick brown fox..."`),
generating 32 tokens with temperature 0.

### 2.6 AirLLM runner (`airllm_runner.py`)

Layer-by-layer inference for models up to 70B+ on consumer GPUs (4-8 GB
VRAM). Loads one transformer layer at a time, trading 10-50x speed for
the ability to run massive models without the VRAM budget.

- Controlled by `airllm_enabled`, `airllm_model_path`,
  `airllm_compression` (4bit/8bit/None).
- Provides `generate()` and `generate_chat()` with HuggingFace chat
  template support.
- Not integrated into the main `inference_router` dispatch -- it is a
  standalone module used by specific callers (research, KB synthesis).

---

## 3. Completion Pipeline

### 3.1 From prompt to response

```
Caller                 llm_gateway.run_completion()
  |                           |
  |  prompt, max_tokens,      |
  |  temperature, stream      |
  |                           |
  |  1. Set _routing_prompt   |  (ContextVar for model routing)
  |  2. Count prompt tokens   |
  |  3. Resolve model override|  (ContextVar + task classification)
  |  4. Resolve reasoning     |  (ContextVar "high" -> reasoning_budget)
  |     budget                |
  |  5. Check completion      |  (SHA-256 cache key)
  |     cache                 |
  |  6. Try litellm gateway   |  (if litellm_enabled)
  |  7. Dispatch to           |
  |     inference_router      |
  |  8. Count completion      |
  |     tokens                |
  |  9. Record usage          |  (session totals + per-turn trace)
  | 10. Record Prometheus     |
  |     metrics               |
  | 11. Store in completion   |
  |     cache                 |
  |                           |
  v                           v
result dict: {"choices": [{"message": {"content": "..."}}]}
```

### 3.2 System prompt construction (`system_head_builder.py`)

`build_system_head()` assembles the system prompt from approximately 20
context sources, in a defined section order. Major sections include:

1. **System instructions** -- Core identity, personality, aspect
   behavioral blocks, hardware capability summary.
2. **Pinned context** -- Last user message, last tool result, session
   summary, operator file context.
3. **Agent state** -- Repo structure, workspace dependency context,
   project context, study plans, sub-objectives.
4. **Memory block** -- Ordered by `MEMORY_SECTION_ORDER`: git preamble,
   project instructions, repo cognition, project memory, relationship
   codex, skills, aspect memories, learnings, semantic recall, retrieved
   context, working memory, conversation summaries, relationship memory,
   timeline events, style and identity, personal knowledge graph, RL
   feedback, reasoning strategies, golden examples.
5. **Knowledge** -- ChromaDB RAG chunks or static knowledge docs.

Budget enforcement uses `prompt_tier_budget.py` to compute per-section
character caps based on reasoning mode (none/light/deep) and
`system_head_budget_ratio` (default 0.35 of `n_ctx`).

Lightweight chat detection (`is_lightweight_chat_turn`) skips expensive
retrieval for phatic utterances ("hi", "thanks", "ok").

### 3.3 Token budgeting (`prompt_tier_budget.py`)

Three reasoning tiers control how much context each section gets:

| Tier | Identity | Personality | Memory | Knowledge | Workspace | Policy |
|------|----------|-------------|--------|-----------|-----------|--------|
| none | 200 | 300 | 0 | 0 | 0 | 200 |
| light | 200 | 400 | 600 | 400 | 400 | 300 |
| deep | 200 | 500 | 1200 | 1000 | 800 | 400 |

`merge_with_n_ctx()` scales these budgets to fit within
`n_ctx * head_ratio * 3` characters (the `*3` approximates chars-to-tokens).

### 3.4 Stop sequences

`get_stop_sequences()` returns a configurable list (or a hardcoded
default) designed to prevent:

- Model echoing system-prompt section headers back into replies
- Fake multi-speaker roleplay (aspect name tags)
- Memory-artifact leakage ("Snippet:", "Replied.")
- Special tokens (`<|endoftext|>`, `<|im_end|>`)

### 3.5 Token counting (`token_count.py`)

Uses `tiktoken` with `cl100k_base` encoding. Falls back to `len(text) // 4`
heuristic when tiktoken is unavailable. Provides:

- `count_tokens(text)` -- single string
- `count_tokens_messages(messages)` -- list of `{role, content}` with
  +4 per-message overhead
- `token_count_available()` -- boolean probe

---

## 4. Model Routing (`model_router.py`)

### 4.1 Task classification

`classify_task(text, context)` uses keyword heuristics:

| Keywords | Classification |
|----------|---------------|
| code, implement, fix, debug, refactor, write, function, class, test, lint (or code signals in context) | `coding` |
| analyze, explain, why, compare, evaluate, reason, logic, proof (or long/multi-line text) | `reasoning` |
| short text, no research keywords | `chat` |
| fallthrough | `default` |

### 4.2 Model selection priority chain

`select_model(task, context_len, hardware, latency_budget)` uses this
priority order:

1. **Aspect override** -- `aspect_model_overrides` in config can bind a
   specific model to an aspect ID.
2. **Capability registry** -- `get_best_llm_filename_for_task()` checks
   registered model capabilities.
3. **Large-context coding model** -- When context exceeds
   `coding_large_context_threshold` (default 12000), uses
   `coding_model_large_context`.
4. **Magicoder capability** -- If `llm_model_coding` capability is
   Magicoder, uses `coding_model`.
5. **Benchmark fastest** -- For tight latency budgets (< 5s), picks
   the fastest benchmarked model among configured candidates.
6. **Telemetry bias** -- If the user's profile shows > 70% simple
   queries, routes to chat model.
7. **Adaptive success rate** -- Prefers models with >= 20% higher
   historical success rate for this task type.
8. **Config route** -- Falls back to `route_model(task_type)` which reads
   `coding_model`, `reasoning_model`, `chat_model` from config.

### 4.3 Dual-model routing

When `force_dual_models` or sufficient RAM is detected
(`should_use_dual_models()`), two models are loaded simultaneously:

- **Chat model** -- Small/fast, used for reactive turns
  (`model_override == "chat"`)
- **Agent model** -- Large/capable, used for coding and reasoning
  (`model_override in ("coding", "reasoning")`)

`resolve_dual_model_basenames()` resolves these from `chat_model_path`,
`agent_model_path`, or router config fields.

### 4.4 Chain-of-thought model splitting

`split_cot_models()` assigns per-phase models for chain-of-thought:

- Reasoning/planning phase uses the fast/chat model
- Implementation/coding phase uses the coding/agent model
- `split_enabled` is true only when two distinct models are found

Cost tracking is accumulated in `_cot_cost_stats` for the
`/agent/cot_stats` endpoint.

---

## 5. Reasoning Modes

### 5.1 Cognitive workspace (`cognitive_workspace.py`)

Tree-of-thought style deliberation. Given a problem goal:

1. **Generate approaches** -- LLM generates 3 candidate strategies
   (search-first, reasoning-first, tool-first) or falls back to
   hardcoded canonical approaches.
2. **Evaluate approaches** -- LLM evaluates which is most promising
   and returns a JSON choice with rationale.
3. **Return strategy hint** -- The chosen approach's `bias` string is
   injected into the agent's context to steer behavior.

Activation gate (`should_use_cognitive_workspace`):
- Must be enabled in config (`enable_cognitive_workspace`, default true)
- Plan depth must be below `max_plan_depth` (default 3)
- Goal must be >= 120 chars
- Goal must contain complexity keywords (analyze, debug, investigate,
  refactor, design, architecture, complex, complicated)

### 5.2 Reasoning strategies (`reasoning_strategies.py`)

Six named strategies with keyword-based suggestion:

| Strategy | Description | Triggered by |
|----------|-------------|-------------|
| `decomposition` | Break into subproblems | debug, fix, error, implement, build, analyze |
| `analogy` | Adapt from similar problem | implement, build, create |
| `working_backwards` | Start from desired outcome | debug, fix, error, trace |
| `constraint_relaxation` | Ignore a constraint temporarily | optimize, improve, performance |
| `exhaustive_small` | Enumerate small cases | analyze, understand, explain |
| `divide_conquer` | Split, recurse, merge | optimize, improve, performance |

`get_strategy_prompt_hint()` formats these as bullet points for injection
into the system prompt. The `try_strategies()` function is a placeholder
for future multi-strategy execution (run LLM with each strategy and
compare results).

### 5.3 Reasoning effort

The `_reasoning_effort_var` ContextVar controls per-request reasoning
depth. When set to `"high"`, `run_completion()` reads
`reasoning_budget` from config and passes it to the llama_cpp backend
for thinking-model support.

---

## 6. LLM Decision Extraction (`llm_decision.py`)

The agent loop must extract structured decisions (tool calls, reasoning
steps) from LLM output. Three strategies are tried in order:

### Strategy chain

| Priority | Strategy | Library | Requirements |
|----------|----------|---------|-------------|
| 1 | `OutlinesStrategy` | `outlines` | Local Llama, no server URL, `structured_generation_enabled` |
| 2 | `InstructorStrategy` | `instructor` | Local Llama, no server URL, `use_instructor_for_decisions` |
| 3 | `PlainJsonStrategy` | (none) | Always available -- runs `run_completion` + JSON parse |

The Outlines strategy uses `outlines.generate.json(model, AgentDecision)`
for grammar-constrained generation against the `AgentDecision` Pydantic
schema. Multiple API paths are tried for compatibility with different
outlines versions (>= 1.x and 0.0.x).

The Instructor strategy patches `llm.create_chat_completion_openai_v1`
with `instructor.patch()` using `Mode.JSON_SCHEMA`.

Both structured strategies retry once on failure. PlainJsonStrategy
appends a retry suffix on the second attempt.

### Decision normalization (`structured_gen.py`)

`_normalize_outlines_result()` maps the raw Pydantic/dict output to
the canonical decision shape:

```python
{
    "action": "tool" | "reason" | "think",
    "tool": str | None,        # validated against valid_tools
    "args": dict,
    "batch_tools": [{"tool": str, "args": dict}, ...],
    "thought": str | None,
    "objective_complete": bool,
    "revised_objective": str | None,
    "priority_level": "low" | "medium" | "high",
    "impact_estimate": str | None,
    "effort_estimate": str | None,
    "risk_estimate": str | None,
}
```

---

## 7. Caching

### 7.1 Completion cache (`completion_cache.py`)

Short-lived in-memory cache for non-streaming completion results.

| Property | Value |
|----------|-------|
| Storage | `dict[str, tuple[Any, float]]` (hash -> (result, timestamp)) |
| Key | SHA-256 of `f"{routing_tag}|{model_name}|{temperature:.3f}|{max_tokens}|{prompt}"` |
| TTL | `completion_cache_ttl_seconds` (default 45s) |
| Max entries | `completion_cache_max_entries` (default 500) |
| Eviction | LRU-style: evicts oldest 10% when at capacity |
| Thread safety | `threading.Lock` |
| Enabled by | `completion_cache_enabled` in config |
| Size guard | Only caches prompts < 12 KB |

Stats (hits, misses, size, hit_ratio) exposed via `get_cache_stats()`.

### 7.2 Response cache (`response_cache.py`)

Separate cache for repeated short chat turns, keyed by `(message, aspect_id)`.

| Property | Value |
|----------|-------|
| Storage | `dict[str, tuple[float, dict]]` |
| Key | SHA-256 of `f"{message.strip().lower()}::{aspect_id.strip().lower()}"` |
| TTL | Caller-specified (`ttl_seconds` parameter) |
| Max entries | 300 (default, configurable per call) |
| Eviction | Oldest-first when over capacity |
| Thread safety | `threading.Lock` |

This cache is simpler and coarser-grained than the completion cache --
it caches entire response payloads, not raw completions.

---

## 8. Multi-Provider Gateway

### 8.1 Inference router (`inference_router.py`)

Backend detection priority:

1. Explicit `inference_backend` config (if not `"auto"`)
2. `ollama_base_url` present -> `ollama`
3. `llama_server_url` with `:11434` or `"ollama"` in URL -> `ollama`
4. `llama_server_url` present -> `openai_compatible`
5. No URL -> `llama_cpp` (local)

Each backend implements the same interface:
`run_completion_{backend}(cfg, prompt, max_tokens, temperature, top_p,
repeat_penalty, top_k, stop, stream, timeout, lock, ...)` returning
`dict | Generator[str]`.

The OpenAI-compatible backend supports fallback URLs via
`inference_fallback_urls` -- it tries each in order on HTTP 5xx or
connection errors.

### 8.2 LiteLLM gateway (`litellm_gateway.py`)

Wraps the `litellm` library for unified access to 100+ providers.

**Config keys:**

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `litellm_enabled` | bool | `false` | Master switch |
| `litellm_default_model` | str | `""` | Default model (e.g. `"anthropic/claude-3-5-sonnet-20241022"`) |
| `litellm_fallback_chain` | list | `[]` | Ordered fallback models |
| `litellm_api_keys` | dict | `{}` | Provider -> API key mapping |
| `litellm_timeout_seconds` | int | `120` | Per-request timeout |
| `litellm_max_retries` | int | `2` | Retries before next provider |

**Supported providers (API key mapping):**

anthropic, openai, groq, together, mistral, cohere, google (Gemini),
deepseek, openrouter.

**Failover logic:**

1. Build attempt list: primary model first, then fallback chain
2. For each model, check circuit breaker (`provider_health.is_healthy`)
3. Retry up to `max_retries` times per provider
4. On success, record latency + cost via `provider_health`
5. On final failure for a provider, trigger circuit breaker
6. Raise `RuntimeError` if all providers exhausted

Cost tracking uses `litellm.completion_cost()` when available.

### 8.3 Provider health (`provider_health.py`)

Circuit-breaker pattern per provider:

| Parameter | Value |
|-----------|-------|
| `FAILURE_THRESHOLD` | 3 failures within window |
| `FAILURE_WINDOW_SECONDS` | 60s rolling window |
| `COOLDOWN_SECONDS` | 300s circuit-open duration |
| `MAX_LATENCY_SAMPLES` | 50 (rolling window) |

States: **Closed** (healthy) -> **Open** (unhealthy, after threshold) ->
**Half-open** (after cooldown, one probe allowed) -> **Closed** (on
probe success).

Tracks per-provider: total calls, success/failure counts, error rate,
avg/p95 latency, total cost USD, last error string.

### 8.4 Cluster offloading (`inference_router.py`)

Phase 9.3 feature. When `cluster_offload_enabled` is true and local
inference fails:

1. Discover paired peers via mDNS (`mdns_discovery.get_discovered_peers`)
2. Filter to peers with `inference_offload` permission
3. Sort by hardware tier (gpu_high > gpu_mid > gpu_low > cpu)
4. Try each peer's `/v1/chat/completions` endpoint
5. Return error if all peers fail

---

## 9. Output Processing

### 9.1 Output polish (`output_polish.py`)

Lightweight final cleanup:

- Strips leading/trailing whitespace
- Collapses triple+ newlines to double
- Skips processing for code fences, JSON arrays, tool-style JSON
- Optionally delegates to `output_quality.clean_output()` when
  `output_quality_gate_enabled` is true

### 9.2 Output quality gate (`output_quality.py`)

Deterministic (no LLM call) quality checks:

**`clean_output()` transformations:**
- Strip common hedges: "Sure,", "Of course,", "Here's", "I think",
  "As an AI language model"
- Collapse excessive blank lines
- De-duplicate exact/near-exact paragraphs

**`passes_completion_gate()` checks:**

| Check | Failure reason |
|-------|---------------|
| Empty response | `empty_response` |
| Response < 20 chars | `too_short` |
| Jaccard similarity >= 0.70 with goal | `restates_goal(sim=...)` |
| Tools used but none succeeded | `no_successful_tool_steps` |
| Response looks like decision JSON | `looks_like_decision_json` |

Returns `(ok: bool, reasons: list[str])`.

### 9.3 Style profiling (`style_profile.py`)

Tracks user interaction patterns to adapt response style:

- **Tone detection** -- appreciative, urgent, inquisitive, polite,
  problem-solving, brief, detailed
- **Collaboration signals** -- asks_for_direct_feedback,
  prefers_supportive_framing, likes_gradual_explanation, prefers_brevity
- **Topic extraction** -- Keyword frequency analysis (words >= 4 chars,
  excluding stopwords)

Profile data stored via `db.set_style_profile()` under keys:
`response_style`, `topics`, `collaboration`.

Injected into system prompt when `enable_style_profile` is true.

### 9.4 Agent loop formatting (`agent_loop_formatting.py`)

`format_tool_steps_for_prompt()` formats completed tool steps for
re-injection into the next iteration's context. Each step is rendered as
`"{action}: {summary}"` with output truncated to
`tool_step_context_max_tokens` (default 500, reduced to 320 when
aggressive compression is enabled).

---

## 10. Configuration Reference

### Core inference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model_filename` | str | `"your-model.gguf"` | Default GGUF model basename |
| `models_dir` | str | `"~/.layla/models"` | Model storage directory |
| `inference_backend` | str | `"auto"` | `auto`, `llama_cpp`, `openai_compatible`, `ollama`, `litellm` |
| `llama_server_url` | str | `""` | Remote OpenAI-compatible URL |
| `ollama_base_url` | str | `""` | Ollama API base URL |
| `remote_model_name` | str | `"layla"` | Model name for remote backends |
| `llm_timeout_seconds` | int | `120` | Async request timeout |
| `llm_local_timeout_seconds` | int | `180` | Local llama_cpp generation timeout |
| `llm_serialize_per_workspace` | bool | `false` | Per-workspace inference locking |

### Model routing

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `coding_model` | str | `""` | GGUF basename for coding tasks |
| `reasoning_model` | str | `""` | GGUF basename for reasoning tasks |
| `chat_model` | str | `""` | GGUF basename for chat tasks |
| `decision_model` | str | `""` | GGUF for structured decision extraction |
| `models` | dict | `{}` | Block with `default`, `code`, `fast`, `fallback` keys |
| `tool_routing_enabled` | bool | `true` | Enable task-based model routing |
| `model_override_enabled` | bool | `true` | Allow per-request model overrides |
| `force_dual_models` | bool | `false` | Force dual-model mode |
| `route_default_to_chat_model` | bool | `false` | Route default tasks to chat model |
| `aspect_model_overrides` | dict | `{}` | Per-aspect model preferences |
| `latency_budget_ms` | int | `0` | Latency budget for routing decisions |
| `coding_model_large_context` | str | `""` | Model for large coding contexts |
| `coding_large_context_threshold` | int | `12000` | Threshold for large-context model |

### Caching

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `completion_cache_enabled` | bool | `true` | Enable completion cache |
| `completion_cache_ttl_seconds` | float | `45` | Cache entry TTL |
| `completion_cache_max_entries` | int | `500` | Max cache size |

### LiteLLM

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `litellm_enabled` | bool | `false` | Enable multi-provider gateway |
| `litellm_default_model` | str | `""` | Default model string |
| `litellm_fallback_chain` | list | `[]` | Ordered failover list |
| `litellm_api_keys` | dict | `{}` | Provider API keys |
| `litellm_timeout_seconds` | int | `120` | Per-request timeout |
| `litellm_max_retries` | int | `2` | Retries per provider |

### Generation parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `top_p` | float | `0.95` | Nucleus sampling |
| `repeat_penalty` | float | `1.1` | Repetition penalty |
| `top_k` | int | `40` | Top-k sampling |
| `stop_sequences` | list | (hardcoded) | Custom stop sequences |
| `reasoning_budget` | int | `-1` | Token budget for thinking models (-1 = unlimited, 0 = disabled) |

### Prompt budgets

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `prompt_budget_enabled` | bool | `true` | Enforce section budgets |
| `system_head_budget_ratio` | float | `0.35` | Fraction of n_ctx for system head |
| `tiered_prompt_budget_enabled` | bool | `true` | Use reasoning-tier budgets |
| `prompt_budgets` | dict | `{}` | Per-section budget overrides |

### Output processing

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `output_quality_gate_enabled` | bool | `false` | Enable hedge stripping |
| `completion_gate_block_structured_json` | bool | `true` | Block decision JSON in responses |
| `enable_style_profile` | bool | `false` | Enable style profiling |
| `tool_step_context_max_tokens` | int | `500` | Max tokens per tool step in context |
| `context_aggressive_compress_enabled` | bool | `false` | Reduce tool step budget to 320 |

### AirLLM

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `airllm_enabled` | bool | `false` | Enable AirLLM |
| `airllm_model_path` | str | `""` | HuggingFace model ID or local path |
| `airllm_cache_dir` | str | `agent/.airllm_cache` | Layer shard cache |
| `airllm_max_new_tokens` | int | `512` | Max generation length |
| `airllm_compression` | str | `null` | `"4bit"`, `"8bit"`, or null |
| `airllm_device` | str | `"auto"` | `"cuda"` or `"cpu"` |

### Cluster offloading

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cluster_offload_enabled` | bool | `false` | Enable LAN peer offloading |
| `inference_fallback_urls` | list | `[]` | Additional OpenAI-compatible fallback URLs |

---

## 11. Known Issues and Risks

### Thread safety

1. **`_llm_by_path` fast path is racy.** The lockless read at line 411 of
   `llm_gateway.py` avoids deadlock for nested completions, but a
   concurrent `invalidate_llm_cache()` could clear the dict between the
   check and the return. The window is very small but the failure mode
   is a `KeyError` or use of a freed Llama instance.

2. **`invalidate_llm_cache()` has no draining.** In-flight completions
   on the invalidated `Llama` instance will produce undefined behavior.
   There is no mechanism to wait for active requests to finish before
   dropping the reference.

3. **`_ROUTER_CONFIG` module-level cache** in `model_router.py` is never
   invalidated during runtime. Config changes require calling
   `reset_router_config_cache()` or restarting the server.

### Resource leaks

4. **`LLMRequestQueue` worker uses `run_in_executor(None, ...)`** which
   dispatches to the default ThreadPoolExecutor. Each completion blocks a
   thread for the entire generation duration. The queue serializes these,
   but the executor's thread pool size is unbounded by default, and
   abandoned futures are not cleaned up on queue stop.

5. **AirLLM model cache (`_model_cache`)** holds GPU tensors indefinitely.
   `unload_model()` exists but is never called automatically. On VRAM-
   constrained systems, loading a second AirLLM model could OOM.

### Missing error handling

6. **`litellm_gateway` streaming failure is silent.** When a provider
   fails mid-stream, `complete_stream()` logs a warning and tries the
   next provider, but any tokens already yielded from the failed provider
   are lost. The caller receives a partial prefix followed by a complete
   response from the fallback -- creating duplicated or incoherent output.

7. **`run_completion_llama_cpp` broadcast recovery** invalidates the
   entire model cache on shape errors, but does not re-raise the error
   on the final attempt. Instead, it returns a hardcoded error string
   as a "successful" completion. Callers cannot distinguish this from
   a real response.

### Dead code

8. **`airllm_runner.py` is not wired into `inference_router`.** It is a
   standalone module that must be called directly. The `get_info()`
   status is surfaced in `model_router.get_model_routing_summary()` but
   the generation path is never invoked from the main completion pipeline.

9. **`reasoning_strategies.try_strategies()`** is a placeholder that
   returns hints but does not execute any LLM calls. The docstring says
   "In full implementation, would run LLM with each strategy and compare."

10. **`_LLMRequest.priority` field** is stored on request objects but
    never used for ordering. The `asyncio.Queue` is FIFO; there is no
    priority queue implementation despite `PRIORITY_CHAT` and
    `PRIORITY_BACKGROUND` constants being defined.

### Architectural concerns

11. **Dual return type for `run_completion`.** The function returns
    `dict` for non-streaming and `Generator[str]` for streaming. This
    dual return type forces callers to check `stream` before accessing
    the result, and makes it easy to accidentally iterate a dict or
    subscript a generator.

12. **Config loaded repeatedly.** `runtime_safety.load_config()` is
    called multiple times within a single `run_completion` call path
    (gateway, router, inference_router, stop_sequences). There is no
    per-request config snapshot, so config changes mid-request could
    cause inconsistent behavior.

---

## 12. Stability Assessment

| Module | Rating | Notes |
|--------|--------|-------|
| `llm_gateway.py` | **STABLE** | Core path, heavily used, retry logic, good error handling. The fast-path race (issue 1) is low-risk in practice. |
| `inference_router.py` | **STABLE** | Clean backend dispatch, fallback URLs, cluster offloading. Well-tested per CI. |
| `litellm_gateway.py` | **STABLE** | Clean failover logic, provider health integration, cost tracking. Streaming mid-failure (issue 6) is the main gap. |
| `llm_decision.py` | **STABLE** | Strategy chain pattern is well-structured. Conservative integration approach (does not replace agent_loop's `_llm_decision`). |
| `model_router.py` | **STABLE** | Comprehensive routing with aspect overrides, telemetry, adaptive success rates. Config cache staleness (issue 3) is the gap. |
| `model_manager.py` | **STABLE** | Simple catalog + download. No auto-update or integrity checking. |
| `model_benchmark.py` | **STABLE** | Simple, isolated, persists results. Low risk. |
| `model_recommender.py` | **STABLE** | Pure rule-based, no side effects. Recommendations could become stale as new models appear. |
| `completion_cache.py` | **STABLE** | Clean LRU-ish cache with TTL, thread-safe, bounded. |
| `response_cache.py` | **STABLE** | Simple and correct. |
| `token_count.py` | **STABLE** | Minimal, correct fallback behavior. |
| `cognitive_workspace.py` | **FRAGILE** | Depends on LLM producing parseable JSON for approach generation and evaluation. No validation of LLM output beyond regex JSON extraction. Hardcoded fallback masks failures. |
| `reasoning_strategies.py` | **INCOMPLETE** | Strategy suggestion works; `try_strategies()` is a placeholder stub. |
| `structured_gen.py` | **FRAGILE** | Must handle multiple outlines API versions via try/except chains. Correct but brittle across library upgrades. |
| `prompt_tier_budget.py` | **STABLE** | Pure data + arithmetic. No external dependencies. |
| `output_polish.py` | **STABLE** | Minimal, safe, correct skip for structured content. |
| `output_quality.py` | **STABLE** | Deterministic, no LLM calls. Jaccard similarity check is a reasonable heuristic. |
| `style_profile.py` | **STABLE** | Heuristic-based, writes to DB. Non-clinical framing is well-documented. |
| `agent_loop_formatting.py` | **STABLE** | Extracted helper, well-scoped. |
| `provider_health.py` | **STABLE** | Textbook circuit breaker with rolling window, cooldown, half-open probe. Thread-safe. |
| `airllm_runner.py` | **INCOMPLETE** | Functional but not integrated into the main inference pipeline. Requires manual caller invocation. GPU memory management is manual. |
| `system_head_builder.py` | **STABLE** | Large but well-structured. Many try/except blocks prevent any single context source from breaking the prompt. Budget enforcement works correctly. |

---

## Appendix A: File Reference

| File | Lines | Purpose |
|------|-------|---------|
| `agent/services/llm_gateway.py` | ~896 | Central completion gateway, token tracking, cache integration |
| `agent/services/inference_router.py` | ~675 | Backend dispatch (llama_cpp, openai, ollama, cluster) |
| `agent/services/litellm_gateway.py` | ~418 | Multi-provider failover via litellm library |
| `agent/services/llm_decision.py` | ~283 | Strategy-chain decision extraction |
| `agent/services/model_router.py` | ~675 | Task classification and model selection |
| `agent/services/model_manager.py` | ~170 | Model catalog, install, list |
| `agent/services/model_benchmark.py` | ~148 | Performance measurement and persistence |
| `agent/services/model_recommender.py` | ~143 | Hardware-based model recommendation |
| `agent/services/cognitive_workspace.py` | ~141 | Tree-of-thought deliberation |
| `agent/services/reasoning_strategies.py` | ~78 | Strategy suggestion heuristics |
| `agent/services/structured_gen.py` | ~146 | Outlines grammar-constrained generation |
| `agent/services/completion_cache.py` | ~118 | Prompt-level completion cache |
| `agent/services/response_cache.py` | ~70 | Chat-turn response cache |
| `agent/services/token_count.py` | ~47 | Token counting with tiktoken |
| `agent/services/prompt_tier_budget.py` | ~75 | Reasoning-tier section budgets |
| `agent/services/output_polish.py` | ~42 | Response cleanup |
| `agent/services/output_quality.py` | ~133 | Quality gate and hedge stripping |
| `agent/services/style_profile.py` | ~166 | User interaction style profiling |
| `agent/services/agent_loop_formatting.py` | ~43 | Tool step formatting for context |
| `agent/services/provider_health.py` | ~214 | Circuit breaker per LLM provider |
| `agent/services/airllm_runner.py` | ~321 | Layer-by-layer large model inference |
| `agent/services/system_head_builder.py` | ~1087 | System prompt assembly |

# Design Document: Core Agent Loop

**Subsystem:** `agent/agent_loop.py` + supporting modules  
**Status:** Production, actively evolving  
**Last reviewed:** 2026-05-24  
**File sizes:** agent_loop.py = 4119 lines; tool_dispatch.py = 1116 lines; executor.py = 312 lines

---

## 1. Architecture Overview

### 1.1 Entry Points

The agent loop has three public entry points:

| Entry Point | Signature | Purpose |
|---|---|---|
| `autonomous_run()` | 30+ parameters | Primary entry. Prompt-optimizes the goal, sets context vars, acquires scheduling slot + serialize lock, delegates to `_autonomous_run_impl`. |
| `autonomous_run_from_request()` | `AgentRunRequest` dataclass | Convenience wrapper. Unpacks the dataclass and calls `autonomous_run()`. |
| `stream_reason()` | (goal, aspect, ...) | Streaming-only path. Builds head + prompt, calls `run_completion(stream=True)`, yields tokens. |

### 1.2 Call Chain

```
autonomous_run()
  |-- prompt_optimizer.optimize(goal)       # optional rewrite
  |-- set context vars (_goal_original_var, _goal_optimized_var)
  |-- schedule_slot(priority)               # resource manager semaphore
  |-- _autonomous_run_serialize_lock()      # global or per-workspace Lock
  |-- _autonomous_run_impl()
        |-- set_model_override / set_reasoning_effort
        |-- _autonomous_run_impl_core()
              |-- Pre-loop setup (memory commands, content guard, dignity check)
              |-- Reasoning mode classification + stabilization
              |-- System overload gate (psutil CPU/RAM check)
              |-- Aspect selection (orchestrator.select_aspect)
              |-- Quick-reply fast path (trivial turns, reasoning_mode="none")
              |-- Semantic recall + packed context build
              |-- Engineering pipeline intercept (optional)
              |-- Cognitive workspace deliberation (tree-of-thought, optional)
              |-- Planning path (create_plan -> execute_plan, with retry ladder)
              |-- MAIN DECISION LOOP (while depth < 5)
              |-- Post-loop: outcome evaluation, memory writes, telemetry
```

### 1.3 The Main Decision Loop

The core loop runs at most 5 iterations (`while state["depth"] < 5`). Each iteration:

1. **Guard checks:** client abort, runtime timeout, tool call limit
2. **Steer hint injection:** pops operator redirect from `shared_state`
3. **Context protection:** compresses conversation history when >60% of n_ctx
4. **Step summarization:** compresses old steps when count exceeds threshold
5. **LLM decision call:** `_llm_decision()` asks the model for a JSON action
6. **Intent resolution:** Maps decision to one of: `think`, `reason`, `tool`, `none`
7. **Pre-dispatch gates:** planning strict refusal, tool allowlist, preflight validation, tool policy, loop detection, exact duplicate detection, retry-constrained block
8. **Concurrent batch path:** if decision includes `batch_tools`, runs them in parallel via ThreadPoolExecutor
9. **Tool dispatch:** delegates to `services/tool_dispatch.py` -> handler function
10. **Reasoning path:** builds system head + prompt, calls LLM, post-processes response
11. **Depth increment + resource-aware chunking**

### 1.4 Exit Conditions

The loop exits when any of these occur:

| Condition | Status Set | Notes |
|---|---|---|
| `depth >= 5` | (whatever was last set) | Hard cap on iterations |
| `objective_complete == True` | "finished" | LLM declares goal satisfied |
| `tool_calls >= max_tool_calls_effective` | "tool_limit" | Configurable cap |
| `time > max_runtime` | "timeout" | Configurable cap |
| `client_abort_event.is_set()` | "client_abort" | External cancellation |
| Approval required for tool | "finished" | Breaks loop, returns pending ID |
| `parse_failed` | "parse_failed" | Falls through to LLM fallback after loop |
| `stream_final=True` + intent="reason" | "stream_pending" | Returns state for caller to stream |
| `consecutive_high_load >= 2` | "paused_high_load" | Checkpoints for UI resume |

---

## 2. Data Flow

### 2.1 Input

```
User message (goal: str)
  + context: str              # workspace/file context
  + workspace_root: str       # sandbox path
  + allow_write / allow_run   # permission flags
  + conversation_history      # mutable list of {role, content}
  + aspect_id                 # forced personality aspect
  + conversation_id           # session key
  + ...28 more parameters
```

### 2.2 Output

The loop returns an `ExecutionState` (dict subclass) with these stable keys:

```python
{
    "status": "finished" | "timeout" | "tool_limit" | "system_busy" | ...,
    "steps": [{"action": str, "result": dict|str}, ...],
    "aspect": "morrigan",
    "aspect_name": "Morrigan",
    "refused": bool,
    "refusal_reason": str,
    "ux_states": ["thinking", "verifying", ...],
    "memory_influenced": [str, ...],
    "reasoning_mode": "light" | "deep" | "none",
    "tool_calls": int,
    "depth": int,
    "outcome_evaluation": {...},     # when finished
    # ... 40+ additional keys
}
```

### 2.3 Decision JSON Schema

The LLM produces a JSON decision each iteration. Parsed by `decision_schema.parse_decision()`:

```python
{
    "action": "tool" | "reason" | "think" | "none",
    "tool": "read_file",           # when action="tool"
    "args": {"path": "..."},       # tool arguments
    "batch_tools": [               # optional parallel tools
        {"tool": "list_dir", "args": {"path": "..."}}
    ],
    "thought": "...",              # when action="think"
    "objective_complete": bool,
    "revised_objective": str|null,
    "priority_level": "low"|"medium"|"high",
    "impact_estimate": str|null,
    "effort_estimate": str|null,
    "risk_estimate": str|null
}
```

**Parsing strategy (3-tier fallback):**
1. **Outlines** (grammar-constrained generation via llama-cpp) -- fastest, most reliable
2. **Instructor** (Pydantic schema + grammar mode) -- second attempt
3. **Plain JSON parse** with `_extract_json_object()` + `_repair_json_like()` -- final fallback, 2 retries

**Validation:** When Pydantic is available, `AgentDecision.model_validate(data)` runs. If it fails, the decision is rejected (returns `None`).

### 2.4 Tool Dispatch Flow

```
intent (str)
  |-- _HANDLER_MAP.get(intent)     # 20 dedicated handlers
  |-- _EXTENDED_TOOLS set          # 7 no-approval tools
  |-- _handle_generic()            # everything else via core/executor.py
```

Each handler follows a common pattern:
1. Sandbox/lab-root check
2. Approval/permission check (allow_write, is_tool_allowed, session grants)
3. Execute tool function
4. Validate output (`_maybe_validate_tool_output`)
5. Deterministic verification + optional auto-retry
6. Record step in `state["steps"]`
7. Post-tool verification
8. Optional git auto-commit
9. Optional auto lint/test/fix

---

## 3. State Management

### 3.1 ExecutionState

`ExecutionState` (in `execution_state.py`) is a `dict` subclass created fresh per run via `create_execution_state()`. It tracks:

| Key | Type | Mutability | Purpose |
|---|---|---|---|
| `goal` / `original_goal` | str | goal mutates, original_goal preserved | Current vs user-authored goal |
| `depth` | int | incremented each loop iteration | Loop counter |
| `tool_calls` | int | incremented on each tool use | Budget tracking |
| `steps` | list | appended to | Full execution trace |
| `status` | str | set at exit | Final status code |
| `objective_complete` | bool | set from LLM decision | Completion flag |
| `consecutive_no_progress` | int | incremented/reset | Stagnation detection |
| `_recent_exact_calls` | set | accumulates | Duplicate tool detection |
| `last_tool_used` | str | overwritten each tool step | Strategy shift heuristic |
| `reasoning_mode` | str | set once at start | "light"/"deep"/"none" |
| `pipeline_stage` | str | transitions: EXECUTE -> DEBUG -> REFLECT | Pipeline enforcement |

### 3.2 Module-Level Globals

**WARNING: These are thread-safety concerns.**

| Global | Type | Lock | Risk |
|---|---|---|---|
| `_last_reasoning_mode` | str | `_reason_mode_lock` (Lock) | Low -- properly locked with TOCTOU fix |
| `_last_cpu`, `_last_ram` | float | `_load_lock` (Lock) | Low -- smoothing only |
| `_VALID_TOOLS` | frozenset | None (immutable) | Safe |
| `_ASPECTS_CACHE` | list/None | `_aspects_lock` | Low -- TTL-based, double-checked locking |

### 3.3 Shared State (shared_state.py)

Global mutable state accessible from routers and the agent loop:

| State | Thread Safety | Purpose |
|---|---|---|
| `_conv_histories` | `_conv_hist_lock` (Lock) | Per-conversation message history |
| `_steer_hints` | `_steer_lock` (Lock) | Operator redirect queue (FIFO, max 8) |
| `_last_outcome_evaluation` | `_outcome_eval_lock` | Feeds next-turn planning bias |
| `_cancel_events` | `_cancel_lock` | asyncio.Event per conversation for cancellation |
| `_blackboard` | `_bb_lock` | Namespaced key-value store for spawned agents |
| `_workspace_lease` | `_workspace_lease_lock` | Single-writer hint per workspace (best-effort) |
| `pending_file_lock` | Lock | Agent vs router pending file access |

**All shared state uses explicit threading.Lock. No race conditions found in the locking code itself.**

### 3.4 Context Variables

Two `ContextVar` instances preserve the user's original goal text across the optimizer rewrite:

```python
_goal_original_var: ContextVar[str]    # what the user typed
_goal_optimized_var: ContextVar[str]   # optimizer's rewrite (empty if unchanged)
```

These are set/reset in `autonomous_run()` with proper token-based cleanup in `finally`.

---

## 4. Integration Points

### 4.1 External Services Touched

| Service | Module | How Called | Failure Mode |
|---|---|---|---|
| **LLM inference** | `services/llm_gateway.py` | `run_completion()`, `_get_llm()` | Fatal -- no response possible |
| **Memory DB (SQLite)** | `layla/memory/db.py` | FTS search, learnings, aspect memories | Graceful -- skipped on failure |
| **Vector store (ChromaDB)** | `layla/memory/vector_store.py` | Semantic recall, embedding | Graceful -- optional |
| **Tool registry** | `layla/tools/registry.py` | `TOOLS` dict, `set_effective_sandbox()` | Fatal -- no tools available |
| **Orchestrator** | `orchestrator.py` | Aspect selection, deliberation prompts | Fallback aspect if fails |
| **Prompt optimizer** | `services/prompt_optimizer.py` | Goal rewriting | Graceful -- uses original goal |
| **Reasoning classifier** | `services/reasoning_classifier.py` | Classifies light/deep/none | Defaults to "light" |
| **Planner** | `services/planner.py` | Multi-step plan creation + execution | Falls through to loop path |
| **Cognitive workspace** | `services/cognitive_workspace.py` | Tree-of-thought deliberation | Graceful -- skipped |
| **Engineering pipeline** | `services/engineering_pipeline.py` | Execute-mode pipeline intercept | Falls through on error |
| **Decision policy** | `services/decision_policy.py` | Dynamic tool-call budget caps | Falls back to config caps |
| **Tool policy** | `services/tool_policy.py` | OpenClaw-style tool filtering | Falls back to all tools |
| **Tool loop detection** | `services/tool_loop_detection.py` | Prevents repeated tool calls | Graceful -- skipped |
| **Dignity engine** | `services/pre_loop_setup.py` | Abuse detection boundary prompt | Graceful -- empty prompt |
| **Content guard** | `services/pre_loop_setup.py` | Input content filtering | May short-circuit run |
| **Outcome evaluation** | `services/outcome_evaluation.py` | Heuristic success scoring | Graceful -- logged warning |
| **Maturity engine** | `services/maturity_engine.py` | Phase-aware observation mode | Graceful -- skipped |
| **Telemetry** | `services/telemetry.py` | Event logging, model outcome | Fire-and-forget |
| **Request tracer** | `services/request_tracer.py` | Per-request trace lifecycle | Fire-and-forget |
| **Metrics (Prometheus)** | `services/metrics.py` | Tool call counters | Fire-and-forget |
| **Context manager** | `services/context_manager.py` | History compression, token estimates | Graceful -- skipped |
| **Resource manager** | `services/resource_manager.py` | `schedule_slot()`, `classify_load()` | "system_busy" on failure |
| **System optimizer** | `services/system_optimizer.py` | Runtime config overrides | Graceful -- uses base config |
| **Model router** | `services/model_router.py` | Task-based model selection | Graceful -- uses default model |
| **Agent hooks** | `services/agent_hooks.py` | pre_tool, post_tool, session_start | Fire-and-forget |
| **RL feedback** | `services/rl_feedback.py` | Outcome recording for tool latency | Fire-and-forget |
| **Debate engine** | `services/debate_engine.py` | Multi-aspect deliberation | Falls back to standard prompt |
| **Output polish** | `services/output_polish.py` | Final response cleanup | Graceful -- returns original |

### 4.2 Core Pipeline Modules

| Module | File | Role |
|---|---|---|
| **Observer** | `core/observer.py` | Phase 1: builds frozen context snapshot (memories, project context, budgets) |
| **Executor** | `core/executor.py` | Phase 4: wraps tool calls with timeout, output cap, sandbox, tracing |
| **Validator** | `core/validator.py` | Phase 5: schema check, injection scan, size check, consistency heuristic |

---

## 5. Error Handling

### 5.1 Pattern Analysis

The codebase uses a **defensive-to-a-fault** error handling pattern. Almost every external service call is wrapped in `try/except Exception` with `logger.debug()`.

**Exception handling distribution in agent_loop.py:**
- `try/except Exception` blocks: ~120+
- Exceptions re-raised: ~3 (system_busy RuntimeError, keyboard interrupts)
- Exceptions silently logged at DEBUG: ~100+
- Exceptions logged at WARNING: ~10

### 5.2 Problems

1. **Over-suppression:** The vast majority of exceptions are caught with bare `except Exception` and logged at DEBUG level. This makes production debugging extremely difficult because real bugs are hidden in noise.

2. **Inconsistent severity:** Some failures that should be WARNING (e.g., `outcome evaluation failed (feedback loop at risk)`) are correctly logged at WARNING, but similar-severity failures elsewhere are DEBUG.

3. **No structured error propagation:** Tool failures return `{"ok": False, "error": str}` but the loop treats all non-ok results identically. There is no distinction between retryable vs permanent failures at the type level.

4. **DB session management:** `core/executor.py` has a `db_session()` context manager that gets a connection but the `finally` block is a no-op (`pass`). The comment says "Don't close thread-local connections on every use -- they're pooled" which is reasonable but the context manager is misleading.

### 5.3 Robustness Rating

| Area | Rating | Notes |
|---|---|---|
| LLM call failures | **B** | Falls back through 3 extraction strategies; null decision falls back to `classify_intent` |
| Tool execution | **A-** | Timeout via ThreadPoolExecutor, output size cap, structured ToolResult dict, auto-retry |
| Memory/DB failures | **A** | Every memory operation is gracefully degraded |
| Config loading | **B+** | Multiple fallback layers; some repeated `load_config()` calls are wasteful |
| Injection defense | **B+** | Validator scans for 10 injection patterns; flags but does not block |
| State corruption | **C+** | Mutable dict passed everywhere; no defensive copying; set used in dict (serialization hazard) |

---

## 6. Configuration

### 6.1 Config Keys That Control Loop Behavior

| Key | Default | Effect |
|---|---|---|
| `max_tool_calls` | 5 | Hard cap on tool invocations per run |
| `max_runtime_seconds` | 900 | Timeout for the entire run |
| `research_max_tool_calls` | 20 | Tool cap in research mode |
| `research_max_runtime_seconds` | 1800 | Timeout in research mode |
| `chat_light_max_runtime_seconds` | 90 | Timeout for lightweight chat turns |
| `temperature` | 0.2 | LLM sampling temperature |
| `completion_max_tokens` | 256 | Max tokens for reasoning LLM call |
| `n_ctx` | 4096 | Context window size |
| `convo_turns` | 0 | Number of conversation history turns to inject |
| `tool_call_timeout_seconds` | 60 | Per-tool execution timeout |
| `planning_enabled` | True | Enable multi-step planning |
| `tool_routing_enabled` | True | Enable intent-based tool filtering |
| `performance_mode` | "auto" | "low"/"mid"/"auto" -- adjusts caps and feature toggles |
| `context_compression` | True | Enable history compression before reasoning |
| `context_protection_threshold` | 0.60 | Ratio of n_ctx before proactive compression |
| `deterministic_tool_verification_enabled` | True | Post-tool semantic verification |
| `deterministic_tool_verification_auto_retry` | True | Auto-retry on verification failure |
| `decision_policy_enabled` | True | Dynamic tool-call budget caps |
| `prompt_optimizer_enabled` | True | Goal rewriting before processing |
| `structured_generation_enabled` | True | Use Outlines/grammar-constrained generation |
| `use_instructor_for_decisions` | True | Use Instructor library for decisions |
| `decision_few_shot_enabled` | True | Include few-shot examples in decision prompt |
| `decision_model` | "" | Optional separate model for decision JSON |
| `tool_first_enforcement_enabled` | (unset) | Force tool use before reasoning |
| `pipeline_enforcement_enabled` | True | Enforce plan-execute-validate-debug pipeline |
| `in_loop_plan_governance_enabled` | (unset) | Step-level plan governance |
| `completion_gate_enabled` | False | Quality gate on final output |
| `completion_gate_max_retries` | 1 | Retry budget for quality gate |
| `telemetry_enabled` | True | Enable event logging |
| `observation_mode_enabled` | True | Nascent-phase observation bias |
| `background_progress_stream_enabled` | True | Live progress events |
| `background_progress_min_interval_seconds` | 0.35 | Throttle interval for progress |
| `step_summarization_threshold` | 8 | Steps before deterministic summarization kicks in |
| `tool_visibility_cap` | 15 | Max tools shown to LLM in decision prompt |
| `context_sliding_keep_messages` | 0 | Messages to preserve during compression |
| `llmlingua_compression_enabled` | False | Advanced per-message compression |
| `mcp_client_enabled` | (unset) | Enable MCP tool discovery |
| `mcp_inject_tool_summary_in_decisions` | (unset) | Inject MCP tools into decision prompt |
| `task_budget_enabled` | True | Adaptive task budget system |
| `structured_retry_enabled` | True | Multi-level retry with escalation |
| `structured_retry_max_levels` | 3 | Max retry levels (1-3) |
| `coordinator_plan_threshold` | 0.45 | Complexity score threshold for forced planning |
| `llm_serialize_per_workspace` | (unset) | Per-workspace instead of global serialize lock |
| `inline_initiative_enabled` | False | Layla v3 proactive suggestions |
| `deliberation_mode` | "solo" | "solo" or multi-aspect debate |
| `max_patch_lines` | 0 | Patch size limit (0=unlimited) |
| `hard_cpu_percent` / `max_cpu_percent` | 95 | CPU overload threshold |
| `max_ram_percent` | 90 | RAM overload threshold |
| `agent_hooks_enabled` | (implicit) | Enable pre/post tool hooks |

### 6.2 Performance Mode Overrides

When `performance_mode` is set:

| Mode | max_tool_calls | cognitive_workspace | planning | deliberation |
|---|---|---|---|---|
| `low` | min(cfg, 2) | disabled | disabled | skipped |
| `mid` | min(cfg, 4) | disabled | config default | config default |
| `auto` | config default | config default | config default | config default |

---

## 7. Known Issues

### 7.1 Excessive Function Length

`_autonomous_run_impl_core()` spans from line 2455 to line 4119 -- **1,664 lines** in a single function. This is the most critical maintainability problem in the codebase. The function handles:
- Pre-loop setup (memory, content guard, dignity)
- Reasoning mode classification
- Overload detection
- Aspect selection
- Quick-reply fast path
- Semantic recall
- Engineering pipeline intercept
- Cognitive workspace
- Planning (with 3-level retry ladder)
- The main decision loop (lines 3097-3950)
- Post-loop outcome evaluation and memory writes
- Response envelope construction

**Recommendation:** This function should be decomposed into at least 5-7 smaller functions.

### 7.2 Dead Code and Redundancy

1. **`classify_intent()`** (line 2065): Labeled "lightweight heuristic" and "legacy call sites." Still used as fallback when `_llm_decision()` returns None, but most of its branches are unreachable in normal flow since the LLM decision path handles tool selection.

2. **`_reflect_on_response()`** (line 1115): A self-reflection function that calls the LLM to critique and rewrite the response. Called from `stream_reason()` but the call is guarded by `cfg.get("skip_self_reflection")` defaulting to not skipping. However, it duplicates the completion gate's purpose and adds latency.

3. **`db_session()` in executor.py**: Context manager whose `finally` is a no-op. The docstring says "explicit lifecycle management" but it manages nothing.

4. **Repeated `runtime_safety.load_config()` calls:** The config is loaded at least 8 separate times within `_autonomous_run_impl_core()` (lines 2504, 2526, 2776, 3830, 3844, 3877, 3954, 4012). Each call reads from disk or cache. Should be loaded once and passed down.

### 7.3 TODO/FIXME Comments

No explicit TODO/FIXME markers found, but several patterns indicate unfinished work:

- `retrieved_knowledge: []` in observer.py (line 93) with comment "populated by agent_loop._load_knowledge_docs" -- but this population does not appear to happen.
- `_PHATIC_QUICK_PATTERNS` (line 137): Defined but never actually used. The quick-reply path uses `_quick_reply_for_trivial_turn()` instead.

### 7.4 Encoding Issues

Throughout the file, Unicode arrows and symbols appear as mojibake (`ÃÃÃ¶`, `ÃÃ¥Ã`, etc.), indicating the file was edited with inconsistent encodings. This is cosmetic but makes comments hard to read.

### 7.5 Operator Precedence / Logic Issues

1. **Tool allowlist check (line 3297-3305):** The condition `intent not in ("reason", "finish", "wakeup", "none") and intent in _VALID_TOOLS` is repeated verbatim **5 times** in the loop body (lines 3297, 3309, 3442, 3473, 3497, 3512, 3533). Each repetition is a separate gate check. If a new intent category is added, all 5+ locations must be updated.

2. **`_BackgroundProgressSteps.append()` exception swallowing** (line 197): All errors during progress emission are silently caught. If the callback raises, the step is still added to the list (correct) but the caller never knows the notification failed.

### 7.6 Unused Parameters

- `AgentRunRequest.conversation_history` defaults to `None` (mutable default via `field(default=None)`). This is correct behavior for dataclass but worth noting.
- `plan_depth` parameter is accepted but only used to constrain planning recursion; it is not validated against negative values.

### 7.7 Serialization Hazard

`ExecutionState` contains `_recent_exact_calls` as a `set`. The `to_persistable_dict()` method converts it to a list, but if anything tries to JSON-serialize the state dict directly (without calling `to_persistable_dict()`), it will crash. This is mitigated by the method's existence but relies on callers remembering to use it.

---

## 8. Test Coverage

### 8.1 Existing Tests

| Test File | What It Tests | Coverage Level |
|---|---|---|
| `tests/test_agent_loop.py` | `classify_intent()` for 7 intent types; JSON decision parsing | **Shallow** -- only tests the heuristic fallback, not the main decision path |
| `tests/test_agent_loop_batch_tools.py` | Concurrent batch execution (read_file + list_dir) | **Good** -- mocks LLM, verifies both tools ran |
| `tests/test_agent_loop_formatting.py` | `format_tool_steps_for_prompt`, `emit_context_window_ux` | **Adequate** -- tests edge cases |

### 8.2 What Is NOT Tested

- **`autonomous_run()` end-to-end** with a real or fully mocked LLM
- **`_llm_decision()`** prompt construction and multi-strategy parsing
- **`_autonomous_run_impl_core()`** main loop flow (depth, timeout, tool limit exits)
- **Planning path** (plan creation, retry ladder, governance)
- **Approval workflow** (pending writes, grants)
- **Error recovery paths** (parse_failed fallback, completion gate retries)
- **Concurrent access** (serialize lock, steer hints, cancel events)
- **Reasoning mode stabilization** (TOCTOU fix, cross-turn mode stickiness)
- **Output sanitization** (junk reply stripping, echo removal, earned title parsing)
- **Context compression** (history summarization under token pressure)
- **Resource-aware chunking** (paused_high_load checkpoint)
- **`core/observer.py`** (snapshot building)
- **`core/validator.py`** (injection scanning, consistency checks)
- **`core/executor.py`** (timeout, output truncation, trace recording)
- **`decision_schema.py`** (JSON extraction, repair, Pydantic validation)

**Estimated coverage of the core loop logic: 5-10%.** The tests that exist verify peripheral helpers, not the decision cycle.

---

## 9. Stability Assessment

| Component | File(s) | Rating | Rationale |
|---|---|---|---|
| `ExecutionState` | `execution_state.py` | **STABLE** | Clean dataclass pattern, well-typed factory, serialization helper works |
| `decision_schema.parse_decision()` | `decision_schema.py` | **STABLE** | Robust JSON extraction with repair, Pydantic validation, good edge-case handling |
| `core/executor.run_tool()` | `core/executor.py` | **STABLE** | Clean contract (never raises), timeout via futures, output cap, structured traces |
| `core/validator.validate()` | `core/validator.py` | **STABLE** | Well-scoped, deterministic, good injection pattern set. Does not block, only flags. |
| `core/observer.build_snapshot()` | `core/observer.py` | **INCOMPLETE** | `retrieved_knowledge` always empty; snapshot is built but not deeply used by the planner |
| `orchestrator.select_aspect()` | `orchestrator.py` | **STABLE** | 3-tier selection (forced, keyword, embedding cosine), proper fallback chain, thread-safe cache |
| `orchestrator.build_deliberation_prompt()` | `orchestrator.py` | **STABLE** | Clean structured prompt with per-aspect voice cues and relationship codex |
| `shared_state.py` | `shared_state.py` | **STABLE** | All state access is properly locked; cancellation support is clean |
| `services/tool_dispatch.py` | `services/tool_dispatch.py` | **FRAGILE** | Massive duplication across handlers (write_file handler alone is 76 lines of boilerplate). `_base_tool_handler` exists but only some handlers use it. |
| `_autonomous_run_impl_core()` | `agent_loop.py` | **FRAGILE** | 1664-line function, deeply nested, 120+ try/except blocks, repeated config loads, 5+ identical guard conditions. Highest refactoring priority. |
| `_llm_decision()` | `agent_loop.py` | **FRAGILE** | 380-line function mixing prompt construction, model routing, 3 extraction strategies, and cleanup. Partially refactored (see P5-4 comment). |
| `_get_tools_for_goal()` | `agent_loop.py` | **FRAGILE** | 4 layers of tool filtering (policy, deterministic route, toolchain graph, visibility cap) with fallback-on-failure at each layer. Correct but hard to reason about which tools survive all filters. |
| `_PHATIC_QUICK_PATTERNS` | `agent_loop.py` | **DEAD** | Defined but never used; quick-reply logic is in `_quick_reply_for_trivial_turn()` |
| `_reflect_on_response()` | `agent_loop.py` | **DEAD** | Duplicates completion gate purpose; adds an extra LLM call. Only used in stream_reason path. |
| `classify_intent()` | `agent_loop.py` | **DEAD** | Legacy heuristic. Only reachable as fallback when `_llm_decision()` returns None, which is rare with the 3-strategy extraction. |
| Planning retry ladder | `agent_loop.py` | **INCOMPLETE** | 3-level retry with model switch is implemented but has no tests and the retry goal construction is ad-hoc string concatenation |
| Output sanitization | `agent_loop.py` | **FRAGILE** | 50+ lines of regex-based echo stripping (lines 3730-3783) with a loop-of-20 for regex substitution. Likely has edge cases. |
| Resource-aware chunking | `agent_loop.py` | **INCOMPLETE** | Pauses on high load and creates a checkpoint, but no resume mechanism is visible in the loop. |

### Priority Refactoring Recommendations

1. **P0 -- Decompose `_autonomous_run_impl_core()`** into pre-loop setup, main loop, reasoning handler, post-loop cleanup, and response envelope builder.
2. **P1 -- Unify tool dispatch handlers** in `tool_dispatch.py`. Most handlers duplicate the execute-validate-verify-record pattern; `_base_tool_handler()` already exists but only ~4 handlers use it.
3. **P2 -- Add integration tests** for the main decision loop with a mock LLM that returns deterministic decisions.
4. **P3 -- Consolidate config loading** to a single `cfg` read at run start, passed as parameter throughout.
5. **P4 -- Remove dead code:** `_PHATIC_QUICK_PATTERNS`, unused `classify_intent` branches.

---

## Appendix A: File Map

```
agent/
  agent_loop.py              # 4119 lines -- main loop, decision, reasoning, output
  execution_state.py         # 149 lines  -- ExecutionState dict subclass
  decision_schema.py         # 174 lines  -- JSON parsing + Pydantic schema
  orchestrator.py            # 503 lines  -- aspect selection, deliberation prompts
  shared_state.py            # 405 lines  -- global mutable state with locks
  core/
    observer.py              # 102 lines  -- Phase 1: context snapshot builder
    executor.py              # 312 lines  -- Phase 4: tool execution with timeout
    validator.py             # 156 lines  -- Phase 5: output validation + injection scan
  services/
    tool_dispatch.py         # 1116 lines -- extracted tool handlers + dispatch entry point
    llm_gateway.py           # LLM inference abstraction
    context_manager.py       # History compression + token estimation
    planner.py               # Multi-step plan creation + execution
    prompt_optimizer.py      # Goal rewriting
    reasoning_classifier.py  # light/deep/none classification
    decision_policy.py       # Dynamic tool-call budget caps
    tool_policy.py           # OpenClaw-style tool filtering
    tool_loop_detection.py   # Repeated tool call prevention
    outcome_evaluation.py    # Heuristic success scoring
    resource_manager.py      # CPU/RAM-based scheduling
    pre_loop_setup.py        # Memory commands, content guard, dignity check
    system_head_builder.py   # System prompt assembly
    agent_loop_formatting.py # Step formatting helpers
    context_window_ux.py     # Context window UX events
```

## Appendix B: Thread Safety Summary

All mutable shared state is protected by explicit `threading.Lock` instances. The serialize lock (`llm_serialize_lock` or per-workspace variant) ensures only one agent run proceeds at a time per workspace. The `_reason_mode_lock` protects reasoning mode stabilization with a proper read-modify-write pattern that eliminates the TOCTOU race documented in comment P0-5.

The main risk is not lock contention but the `ExecutionState` dict being passed by reference to tool handlers running in thread pools. The `_BackgroundProgressSteps` list is shared between the main thread and tool threads via `state["steps"]`, but since `list.append()` is atomic in CPython (GIL), this is safe in practice. It would not be safe under a free-threaded Python build.

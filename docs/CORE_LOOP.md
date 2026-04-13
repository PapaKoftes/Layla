# Core Loop — Technical Specification

> Canonical reference for the 6-phase execution pipeline.
> See also: **`WORKFLOW.md`** (authoritative invariants), **`ARCHITECTURE.md`** (system overview).

---

## Overview

Every autonomous agent run follows exactly one pipeline:

```
observe → plan → approve → execute → validate → update_state
```

Each phase has defined inputs, outputs, invariants, and failure modes. No phase may be skipped or reordered.

---

## Phase 1 — Observe

**Module:** `agent/core/observer.py`
**Trigger:** Start of every `autonomous_run()` call.

**Purpose:** Assemble a complete, frozen context snapshot before any LLM call is made. Nothing outside this snapshot may influence planning.

**Inputs:**
- `goal: str` — raw user message
- `conversation_id: str`
- `cfg: dict` — config loaded once at phase entry
- `aspect_id: str`
- `allow_write: bool`, `allow_run: bool`
- `workspace_root: str`

**Output:** `ObserveSnapshot`
```python
{
  "goal": str,
  "conversation_id": str,
  "aspect_id": str,
  "config_snapshot": dict,       # frozen at observe time
  "n_ctx": int,                  # actual model context window
  "budget_map": dict,            # per-section token budgets, n_ctx-proportional
  "conversation_history": list,  # capped and deduplicated
  "retrieved_memories": list,    # FTS + vector store results
  "project_context": dict,
  "allow_write": bool,
  "allow_run": bool,
  "workspace_root": str,
  "observed_at": str,            # ISO8601, set before any LLM call
}
```

**Invariants:**
- Config loaded exactly once per loop run (not per iteration)
- Token budgets computed from `n_ctx`, not hardcoded constants
- `observed_at` written before any LLM call
- Vector store failure → fall back to FTS, log WARNING, continue
- DB unavailable → use in-memory history only, log WARNING, continue

**Failure:** Any exception in observe → `status=observe_failed`, loop aborts immediately.

---

## Phase 2 — Plan (micro-decision)

> **Naming note:** This phase is the **per-iteration** tool/reason decision inside `agent_loop`. **Macro-plans** live in `services.planner` / `layla_plans`. The optional **engineering pipeline** (clarifier → planner → critics → refiner → execute → validator) is documented in **`docs/STRUCTURED_ENGINEERING_PARTNER.md`**.

**Module:** `agent_loop._llm_decision` (see also `decision_schema`)
**Trigger:** Each iteration of the decision loop.

**Purpose:** Call the LLM once and produce a single validated Decision.

**Inputs:** `ObserveSnapshot` + `state["steps"]` (prior tool results)

**Output:** `Decision`
```python
{
  "action": Literal["tool", "reason", "complete"],
  "tool_name": str | None,
  "args": dict,
  "objective_complete": bool,
  "rationale": str,   # min 5 chars required
  "iteration": int,
  "planned_at": str,
}
```

**Invariants:**
- LLM called exactly once per iteration
- `action` is exactly one of `tool | reason | complete` — `none` is not valid
- If `action=="tool"` and `tool_name` not in TOOLS → immediate `complete` with error notice
- Parse failure → retry once with correction prompt → if still fails → `complete` with error

**Failure:** Parse failure after retry → `action=complete`, error appended to steps.

---

## Phase 3 — Approve

**Module:** `agent/routers/approvals.py`, `agent/agent_loop.py:_write_pending()`
**Trigger:** When `action=="tool"` and `requires_approval==True`.

**Purpose:** Gate execution of non-safe tools. Human approval required before execution.

**Output:** `ApprovalRecord`
```python
{
  "id": str,            # uuid4
  "tool": str,
  "args": dict,
  "status": Literal["pending", "approved", "rejected", "expired"],
  "requested_at": str,
  "expires_at": str,    # now + approval_ttl_seconds (default 3600s)
  "risk_level": str,
}
```

**Invariants:**
- Every approval record has an `expires_at`
- Expired approvals return HTTP 410 — never executed
- `POST /approve/{id}` on expired record → 410 Gone
- Status transitions: `pending → approved → executed` (one-way)
- Re-approving an `executed` record is idempotent

**Failure:** Expired → 410, log INFO.

---

## Phase 4 — Execute

**Module:** `agent/core/executor.py`
**Trigger:** When tool is approved (auto or by operator).

**Purpose:** Run exactly one tool call with timeout, sandbox check, and output size cap.

**Output:** `ToolResult`
```python
{
  "ok": bool,
  "tool_name": str,
  "error": str | None,
  "duration_ms": int,
  "output_bytes": int,
  "timed_out": bool,
  "_meta": dict,        # injected by executor
}
```

**Invariants:**
- Every tool call has a timeout: `tool_call_timeout_seconds` from config (default 60s)
- Output size capped at 256 KB; truncated with `[OUTPUT TRUNCATED]` suffix
- Unknown tool name → `ok=False`, no execution
- Never raises — all exceptions become `ok=False` results

**Failure:** Timeout → `ok=False, timed_out=True`, loop continues.

---

## Phase 5 — Validate

**Module:** `agent/core/validator.py`
**Trigger:** After every tool execution.

**Purpose:** Verify the tool result is structurally sound and safe to inject into context.

**Output:** `ValidationResult`
```python
{
  "passed": bool,
  "checks": {
    "schema_valid": bool,   # result has ok key
    "not_empty": bool,
    "size_ok": bool,
    "no_injection": bool,
    "consistent": bool,
  },
  "warnings": list[str],
  "flagged_injection": bool,
  "annotated_result": dict,
  "validated_at": str,
}
```

**Injection patterns scanned:**
`\n\nHuman:`, `\n\nAssistant:`, `[INST]`, `<|im_start|>`, `</s>`, `<s>`, `ignore previous`, `system:`, `<system>`

**Invariants:**
- Always runs — cannot be skipped or disabled
- Failed validation does NOT abort the loop; result is annotated with warnings
- Injection detected → flag result; log WARNING; do not drop the result

**Failure:** Validator itself throws → skip validation, log ERROR, continue.

---

## Phase 6 — Update State

**Module:** `agent/agent_loop.py:_save_outcome_memory()`, DB writes
**Trigger:** After validation, before next iteration (or at loop exit).

**Purpose:** Persist all state changes. Only phase that writes to DB, history, or shared_state.

**Invariants:**
- History appended exactly once per turn (at loop end, not per iteration)
- DB writes wrapped in explicit transactions; failure logs ERROR but does not crash loop
- SSE queue drops logged at INFO (not swallowed silently)
- `conversation_messages` written with explicit `conversation_id` + timestamp

**Failure:** DB write failure → log ERROR, continue, retry at post-loop.

---

## Loop Termination

| Condition | `status` written |
|-----------|-----------------|
| `action=="complete"` or `action=="reason"` | `finished` |
| `iteration >= max_tool_calls` | `tool_limit` |
| `elapsed > max_runtime_seconds` | `timeout` |
| `elapsed > chat_light_max_runtime_seconds` on lightweight non-tool chat (`_is_lightweight_chat_turn`, `reasoning_mode` none/light) | `timeout` |
| Tool requires approval | `finished` (approval queued) |
| System load too high | `system_busy` |
| Unrecoverable error | `error` |

---

## Config Keys

| Key | Default | Purpose |
|-----|---------|---------|
| `max_tool_calls` | 2 | Max iterations per loop run |
| `max_runtime_seconds` | 30 | Hard wall-clock limit per run |
| `chat_light_max_runtime_seconds` | 90 | Time cap for lightweight non-tool turns (min 30s floor in code) |
| `tool_call_timeout_seconds` | 60 | Per-tool execution timeout |
| `approval_ttl_seconds` | 3600 | Approval expiry (1 hour default) |
| `n_ctx` | 4096 | Model context window size |
| `hyde_enabled` | false | Enable HyDE retrieval (extra LLM call) |

---

## Invariants Summary

1. Config loaded once per run — not per call, not per iteration
2. Tool execution always has a timeout — no unbounded blocking
3. History appended exactly once per turn — no duplicates
4. Approval records have expiry — no permanent orphans
5. ContextVars cleared on all exit paths — normal and exception
6. Sandbox check runs before every file/shell tool — no bypass
7. Validation always runs after tool execution — not skippable
8. DB migrations explicitly distinguish error types — no silent swallow
9. Phase logging emits one structured line per phase — always
10. No LLM call in the memory module by default — HyDE is opt-in via `hyde_enabled`

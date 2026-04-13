# WORKFLOW — Layla Execution Contract

> **This document is authoritative.** All code in agent/ must honour these invariants.
> If code contradicts this document, the document wins and the code must be fixed.

---

## The 6-Phase Loop

Every autonomous agent run follows exactly this sequence:

```
observe → plan → approve → execute → validate → update_state
```

No phase may be skipped. Each phase has defined inputs, outputs, and invariants.

---

### PHASE 1 — OBSERVE

**Trigger:** Start of every `autonomous_run()` call.

**Inputs:** goal, conversation_id, config (loaded once), aspect_id, workspace_root, allow_write, allow_run

**Outputs:** `ObserveSnapshot` — frozen dict containing:
- `goal`, `conversation_id`, `aspect_id`
- `n_ctx` — actual model context limit
- `config_snapshot` — config loaded once, not re-loaded during the loop
- `budget_map` — per-section token budgets proportional to `n_ctx`
- `retrieved_memories` — from FTS + vector store
- `project_context` — current project state
- `conversation_history` — capped, deduplicated
- `observed_at` — ISO8601 timestamp

**Invariants:**
- Config loaded **exactly once** per loop run (never per iteration)
- Token budgets computed from actual `n_ctx` (not hardcoded constants)
- `observed_at` written before any LLM call
- Vector store failure → fall back to FTS, log WARNING, continue (never abort)

**Failure:** Any exception in observe → status=`observe_failed`, loop aborts immediately.

---

### PHASE 2 — PLAN (micro-decision)

> **Naming note:** This phase is the **per-iteration LLM decision** (tool vs reason). It is **not** the same as **macro-planning** (`services.planner.create_plan`, durable `layla_plans`, or the optional **engineering pipeline** in `docs/STRUCTURED_ENGINEERING_PARTNER.md`).

**Trigger:** Each iteration of the decision loop.

**Inputs:** `ObserveSnapshot` + `state["steps"]` (prior tool results)

**Outputs:** `Decision` — typed dict:
```python
{action: "tool"|"reason"|"complete", tool_name: str|None, args: dict, rationale: str, iteration: int}
```

**Invariants:**
- LLM called once per iteration — never more
- `action` is exactly one of: `tool`, `reason`, `complete`
- `action="none"` does not exist — treated as `complete`
- If `action=="tool"` and `tool_name` not in TOOLS → immediately yield `complete` with error notice
- Decision parse failure → retry once with correction prompt → if still fails → `complete` with error
- Model routing classification timeout: max 10 seconds

**Failure:** Parse failure after retry → `action=complete`, error appended to steps, log ERROR.

---

### PHASE 3 — APPROVE

**Trigger:** When `action=="tool"` and `requires_approval==True`.

**Inputs:** `Decision`

**Outputs:** `ApprovalRecord`:
```python
{id: uuid, tool_name: str, args: dict, status: "pending"|"approved"|"rejected"|"expired",
 created_at: ISO8601, expires_at: ISO8601}
```

**Invariants:**
- Every approval record has an `expires_at` (default: `approval_ttl_seconds` from config, default 3600s)
- Expired approvals → HTTP 410, never executed
- Re-approving an `executed` record → idempotent, returns prior result
- Status transitions are one-way: `pending → approved → executed`

**Failure:** Approval TTL elapsed → status=`expired`, return 410, log INFO.

---

### PHASE 4 — EXECUTE

**Trigger:** When tool is approved (auto or by operator).

**Inputs:** `Decision` (tool_name + args)

**Outputs:** `ToolResult`:
```python
{ok: bool, tool_name: str, result: Any, error: str|None, duration_ms: int, output_bytes: int, timed_out: bool}
```

**Invariants:**
- Every tool call has a timeout: `tool_call_timeout_seconds` from config (default: 60s)
- Sandbox check runs **before** execution; violation = immediate rejection, loop continues
- Output size capped at 256 KB; truncated with `[OUTPUT TRUNCATED]` suffix if exceeded
- Protected files (main.py, agent_loop.py, runtime_safety.py) are never written
- `goal` key stripped from args before passing to tool function

**Failure:** Timeout → `ToolResult(ok=False, timed_out=True)`, log WARNING, loop continues.

---

### PHASE 5 — VALIDATE

**Trigger:** After every tool execution, every iteration.

**Inputs:** `ToolResult`, goal string

**Outputs:** `ValidationResult`:
```python
{passed: bool, checks: {schema_valid, not_empty, size_ok, no_injection, consistent},
 warnings: [str], flagged_injection: bool, annotated_result: dict}
```

**Invariants:**
- **Always runs — cannot be disabled or skipped**
- Injection patterns detected → flag result with `_injection_flagged=True`, log WARNING + audit
- Failed validation does NOT abort the loop; result is annotated and planner continues
- Schema check: result must be dict with `ok` key
- Injection patterns scanned: `\n\nHuman:`, `\n\nAssistant:`, `[INST]`, `<|im_start|>`, `ignore previous instructions`, etc.

**Failure:** Validator itself raises → skip validation, log ERROR, continue.

---

### PHASE 6 — UPDATE STATE

**Trigger:** After validation, before next iteration (or after loop exit).

**Inputs:** `ToolResult`, `ValidationResult`, current `state`

**Outputs:** Updated `state["steps"]`, DB writes, SSE events

**Invariants:**
- History appended **exactly once** per turn (at loop end, not per iteration)
- DB writes wrapped in explicit transactions; failure logs ERROR but does not crash loop
- SSE queue: dropped events logged at INFO (not swallowed at DEBUG)
- `conversation_messages` written with explicit `conversation_id` + timestamp
- `ux_state_queue.put()` uses `block=False`; if dropped, log INFO

**Failure:** DB write failure → log ERROR, continue loop, retry at post-loop.

---

## Loop Termination Conditions

The decision loop exits when any of the following is true:

| Condition | Status written |
|---|---|
| `action=="complete"` or `action=="reason"` | `finished` |
| `iteration >= max_tool_calls` | `tool_limit` |
| `elapsed > max_runtime_seconds` | `timeout` |
| `elapsed > chat_light_max_runtime_seconds` on lightweight non-tool chat | `timeout` |
| Tool requires approval | `finished` (approval queued) |
| System load too high | `system_busy` |
| Unrecoverable error | `error` |

---

## Invariants That Must Always Be True

1. **Config loaded once per run** — not per call, not per iteration
2. **Tool execution always has a timeout** — no unbounded blocking
3. **History appended exactly once per turn** — no duplicates across paths
4. **Approval records have expiry** — no permanent orphans
5. **Sandbox check runs before every file/shell tool** — no bypass
6. **Validation always runs after tool execution** — not skippable
7. **DB migrations distinguish error types** — no silent swallow of non-duplicate errors
8. **Phase logging emits one structured line per phase** — always
9. **No LLM call in the memory module by default** — HyDE is opt-in via `hyde_enabled` config
10. **SSRF filter blocks all RFC-1918 ranges** — 10.x, 172.16-31.x, 192.168.x, 127.x, localhost

---

## Config Keys Referenced By This Contract

| Key | Default | Purpose |
|---|---|---|
| `max_tool_calls` | 12 | Max iterations per loop run |
| `max_runtime_seconds` | 120 | Hard wall-clock limit per run |
| `chat_light_max_runtime_seconds` | 90 | Time cap for lightweight non-tool turns |
| `tool_call_timeout_seconds` | 60 | Per-tool execution timeout |
| `approval_ttl_seconds` | 3600 | Approval expiry (1 hour default) |
| `n_ctx` | 4096 | Model context window size |
| `hyde_enabled` | false | Enable HyDE retrieval (extra LLM call) |
| `retrieval_use_mmr` | false | Use MMR diversity in retrieval |

---

## Multi-Agent Extension Points

When `parent_run_id` is present in a request, the run is treated as a sub-agent task:
- Isolation: scoped to the `conversation_id` of the parent
- Tool manifest: may be restricted to a subset via `allowed_tools` config
- Approval: sub-agent tasks require `allow_write`/`allow_run` explicitly set by parent
- Result routing: sub-agent results posted back to parent via `POST /tasks/{parent_run_id}/result`

See `cursor-layla-mcp/server.py` for the Cursor multi-agent implementation.

# Structured engineering partner (target execution model)

Layla’s **default** `/agent` path remains a flexible local agent (aspects, optional in-loop planning, tool loop). This document defines the **optional engineering pipeline**: a deterministic, multi-stage workflow for reliability-critical work.

**Canonical vision** also appears in `LAYLA_NORTH_STAR.md` (appendix). **HTTP shapes** for pipeline responses: `docs/POST_AGENT_RESPONSE_CONTRACT.md`.

---

## What this is (and is not)

| This is | This is not |
|--------|-------------|
| Plan-first, critique, validate, bounded retry | A generic chatbot or “vibe” assistant |
| Mode-gated (`chat` / `plan` / `execute`) | Infinite autonomy |
| Same local model; different **prompted roles** | Separate fine-tuned models (future) |

**Non-goals (V1):** custom model training, removing approval gates, replacing aspects with agents (aspects remain voice/UI; pipeline adds **structural** roles).

---

## Micro-decision vs macro-plan

- **Micro-decision** (per iteration): the LLM chooses `tool` / `reason` / `think` inside `agent_loop` — what `WORKFLOW.md` / `docs/CORE_LOOP.md` call the decision step after observe.
- **Macro-plan**: `services.planner.create_plan` / durable `layla_plans` / `execute_plan` — step list before tool execution.

The engineering pipeline operates on **macro-plan**; it must not double-fire legacy `should_plan` in the same turn.

---

## Modes and latency

| Mode | Behavior | Approx. LLM calls |
|------|----------|-------------------|
| `chat` | No engineering macro-pipeline; existing `autonomous_run` (optional legacy `should_plan` unchanged) | Baseline |
| `plan` | Blocking **Clarifier** → **Planner** only → `plan_ready` (no critics/refiner/execute) | ~1–2 |
| `execute` | Clarifier → Planner → Critic A → Critic B → Refiner → governed **Executor** → mandatory **Validator** → memory | ~5–7+ |

Enable with `engineering_pipeline_enabled: true` in `runtime_config.json` and per-request `engineering_pipeline_mode` (or legacy `plan_mode` alias when enabled — see `POST_AGENT_RESPONSE_CONTRACT.md`).

---

## Stage contracts (JSON)

### Clarifier (blocking)

Returns exactly one of:

- `{ "status": "ok" }` — planner may run.
- `{ "status": "needs_input", "questions": ["...", ...] }` — **pipeline halts**; no planner, no critics, no execution.

**Continuation:** next `POST /agent` sends the same goal in `message` and operator answers in `clarification_reply` (string). The clarifier sees goal + clarification context.

### Critics (forced disagreement)

- **Critic A:** Must argue the plan is **wrong** (assumptions, risk, ordering).
- **Critic B:** Must argue the plan is **incomplete** (missing steps, tests, acceptance).

Outputs are structured **objections** consumed only by the Refiner (no “looks good” consensus).

### Refiner

**Overwrites** the plan: a **single** JSON array of steps (same shape as `create_plan`: `step`, `task`, `tools`). No appended comment blobs as execution input.

### Validator (execute mode only)

**Required** after `execute_plan`. Returns `{ "ok": true }` or `{ "ok": false, "failure_report": "...", "retry_suggested": bool }`. Bounded retry may re-run execution per config; otherwise surface `failure_report`.

### Executor

Uses existing `planner.execute_plan(..., step_governance=True)` with approvals / `plan_id` / `planning_strict_mode` unchanged.

---

## Single macro-plan source

When `engineering_pipeline_enabled` and the request uses macro-planning (`plan` or `execute`):

- Legacy in-loop `should_plan` → `create_plan` → `execute_plan` is **disabled** for that outer turn.
- Nested step runs set a **context lock** so inner `autonomous_run` does not re-enter macro planning or the full pipeline.

---

## Config keys

See `agent/runtime_config.example.json`:

- `engineering_pipeline_enabled` (default `false`)
- `engineering_pipeline_default_mode` (`chat` | `plan` | `execute`)
- `engineering_pipeline_max_clarify_rounds`
- `engineering_pipeline_validator_max_retries`

---

## Code map

| Area | Location |
|------|----------|
| Pipeline orchestration | `agent/services/engineering_pipeline.py` |
| Execute path hook | `agent/agent_loop.py` (`_autonomous_run_impl_core`) |
| Plan-only + precedence vs `plan_mode` | `agent/routers/agent.py` |
| Plan execution + kwargs filter | `agent/services/planner.py` (`_AUTONOMOUS_KW_KEYS`) |
| MCP passthrough | `cursor-layla-mcp/server.py` |

---

## Current vs target (summary)

| Area | Current default | Target with pipeline |
|------|-----------------|----------------------|
| Macro planning | Optional (`should_plan` heuristics) | Forced path per mode; no double planner |
| Critique | Optional deliberation / cognitive workspace | Forced A/B disagreement on written plan |
| Validation | Step governance + optional hard modes | + mandatory turn-level validator in `execute` |
| UX | Single chat | Modes + plan preview + clarification popup |

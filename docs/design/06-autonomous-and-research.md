# 06 -- Autonomous Mode & Research Subsystem

> Design document for the Layla AI autonomous investigation engine and multi-stage
> research pipeline.  Covers the controller loop, planner, policy/safety gates,
> sub-agents, wiki system, investigation reuse, budget enforcement, the 15-stage
> research pipeline, the engineering pipeline, and the research report formatter.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Autonomous Controller](#2-autonomous-controller)
3. [Planner](#3-planner)
4. [Policy & Value Gate](#4-policy--value-gate)
5. [Sub-agents](#5-sub-agents)
6. [Wiki System](#6-wiki-system)
7. [Investigation Reuse & Prefetch](#7-investigation-reuse--prefetch)
8. [Budget System](#8-budget-system)
9. [Context & Caching](#9-context--caching)
10. [Aggregator](#10-aggregator)
11. [Audit Log](#11-audit-log)
12. [Research Pipeline (15 Stages)](#12-research-pipeline-15-stages)
13. [Research Lab](#13-research-lab)
14. [Research Report Service](#14-research-report-service)
15. [Engineering Pipeline](#15-engineering-pipeline)
16. [Known Issues](#16-known-issues)
17. [Stability Assessment](#17-stability-assessment)

---

## 1. Overview

The autonomous subsystem provides Layla with the ability to perform multi-step,
read-only investigations of a codebase without per-step human approval.  It is
complemented by a separate multi-stage research pipeline that performs deeper,
mission-oriented analysis.

**Two distinct execution models exist:**

| System | Entry point | Nature | Write capability |
|--------|-------------|--------|------------------|
| Autonomous Investigation | `run_autonomous_task()` in `autonomous/controller.py` | Synchronous step loop with LLM planner | Read-only tools; optional wiki markdown export |
| Research Pipeline | `research_stages.py` + `research_intelligence.py` | Async sequential stage runner | Writes only to `.research_lab` and `.research_brain` |
| Engineering Pipeline | `services/engineering_pipeline.py` | Clarify-plan-critic-refine-execute-validate | Full write via governed plan execution |

Key files:

```
agent/autonomous/
    controller.py        # Main entry point and step loop
    planner.py           # LLM-backed single-step decision maker
    policy.py            # Tool allowlist and sandbox enforcement
    budget.py            # Step and time budget enforcement
    value_gate.py        # Deterministic heuristic gate for goal quality
    types.py             # AutonomousTask, PlannerDecision, StepRecord
    context.py           # ContextState, tool result caching, progress tracking
    read_cache.py        # Cross-run LRU cache keyed on file mtime+size
    aggregator.py        # Final response assembly with confidence derivation
    audit.py             # JSONL audit log to .governance/autonomous_audit.jsonl
    wiki.py              # Wiki candidate building and markdown persistence
    wiki_retrieval.py    # Jaccard-based wiki prefetch
    investigation_reuse.py   # JSONL-based high-confidence result persistence
    reuse_retrieval.py       # Jaccard-based investigation reuse prefetch
    chroma_retrieval.py      # Chroma vector store prefetch
    subagents.py             # Stub for bounded sub-agent spawning (not enabled)

agent/
    research_lab.py          # Research lab directory management and source copy
    research_stages.py       # Base 6-stage research pipeline
    research_intelligence.py # Intelligence 9-stage pipeline extension
    research_utils.py        # Shared JSON extraction and text normalization

agent/services/
    research_report.py       # Citation extraction and report formatting
    engineering_pipeline.py  # Full engineering execution pipeline
```

---

## 2. Autonomous Controller

**File:** `autonomous/controller.py`
**Entry point:** `run_autonomous_task(task, cfg, tool_call_hook)`

### 2.1 Lifecycle

```
Caller constructs AutonomousTask
        |
        v
run_autonomous_task()
        |
        +---> Value Gate check (reject trivial/direct-action goals)
        |         |
        |         +---> REJECT --> return aggregate with "value_gate_reject"
        |
        +---> Prefetch cascade (if autonomous_prefetch_enabled):
        |         1. try_reuse_retrieval()  -- JSONL of prior high-confidence runs
        |         2. try_wiki_retrieval()   -- .layla/wiki/*.md files
        |         3. try_chroma_retrieval() -- Chroma vector store learnings
        |         |
        |         +---> HIT on any --> return aggregate_prefetch_hit(), skip planner
        |
        +---> Initialize Budget, Policy, Planner, ContextState
        |
        +---> Step loop (max_steps iterations):
        |         |
        |         +---> budget.consume_step()  (may raise BudgetExceeded)
        |         +---> planner.decide(goal, context, budget_hint)
        |         |         |
        |         |         +---> "final" --> record step, break
        |         |         +---> "tool"  --> validate, execute, cache
        |         |
        |         +---> Policy validation (tool allowlist + sandbox path check)
        |         +---> Cache lookup: in-run cache -> dedupe path reads -> cross-run cache
        |         +---> Tool execution via TOOLS registry
        |         +---> Record result in context, progress, audit
        |
        +---> aggregate() -- build final response
        +---> maybe_append_investigation_reuse() -- persist if high confidence
        +---> _maybe_export_wiki_markdown() -- persist if conditions met
        +---> audit.write_final()
        +---> return final dict
```

### 2.2 Exit Conditions

The step loop terminates when any of the following occur:

| Condition | `stopped_reason` |
|-----------|-----------------|
| Planner emits `type: "final"` | `planner_final` |
| Step count exceeds `max_steps` | `max_steps_exceeded` (BudgetExceeded) |
| Wall-clock time exceeds `timeout_seconds` | `timeout_exceeded` (BudgetExceeded) |
| Policy violation (disallowed tool or path) | `policy_violation` |
| Tool execution raises an exception | `tool_error` |
| Loop ends naturally without break | `max_steps_loop_end` |

### 2.3 Prefetch Cascade

Before entering the step loop, the controller checks three caches in priority order.
The first hit short-circuits the entire run:

1. **Reuse retrieval** -- reads `.layla/investigation_reuse.jsonl`, matches via
   Jaccard similarity on tokenized goal text.  Threshold default: 0.22.
2. **Wiki retrieval** -- scans `.layla/wiki/*.md`, matches via Jaccard with
   frontmatter tag boosting.  Threshold default: 0.18.
3. **Chroma retrieval** -- queries the global Chroma vector store via
   `query_learnings_best_similarity()`.  Threshold default: 0.75 (cosine).

Each hit returns a prefetch payload that is wrapped by `aggregate_prefetch_hit()`
into the same response shape as a full run.  The `source` field is set to
`"reuse"`, `"wiki"`, or `"chroma"` accordingly, and `reused: true`.

### 2.4 Tool Call Hook

The optional `tool_call_hook` callback is invoked just before each non-cached tool
execution, receiving `(tool_name, args)`.  This allows callers (e.g. the API layer)
to emit progress events.

---

## 3. Planner

**File:** `autonomous/planner.py`
**Class:** `Planner`

### 3.1 Decision Model

The planner is a single-step LLM-backed decision maker.  On each iteration it
receives:

- The goal (truncated to 1500 chars)
- A context summary from `ContextState.summarize_for_planner()` (truncated to 6000 chars)
- A budget hint string: `steps_remaining=N time_remaining_seconds=M`

It produces exactly one JSON decision object:

```json
// Tool call
{"type": "tool", "tool": "<tool_name>", "args": {...}}

// Final answer
{"type": "final", "final": {
    "summary": "...",
    "reasoning": "...",
    "findings": [{"insight": "...", "evidence": ["path:line"]}],
    "next_steps": [{"action": "...", "tool": "...", "reason": "...", "confidence": "high|medium|low"}],
    "confidence": "low|medium|high"
}}
```

### 3.2 Tool Allowlist

The planner is initialized with a `tool_allowlist` derived from the Policy.  The
LLM prompt includes this list and instructs the model never to invent tool names.
Validation occurs both in the planner (pre-return) and in the policy (post-return).

### 3.3 Retry Logic

The planner attempts up to 2 LLM calls per `decide()` invocation.  If the first
response fails JSON parsing or schema validation, the second attempt includes an
error correction prompt.  If both fail, a synthetic "final" decision is returned
with `error: "planner_failed_after_retry"`.

### 3.4 LLM Parameters

- `max_tokens`: 320
- `temperature`: 0.12
- `stream`: False

The low max_tokens and temperature are deliberate -- the planner should produce
terse, deterministic JSON, not prose.

---

## 4. Policy & Value Gate

### 4.1 Policy

**File:** `autonomous/policy.py`
**Class:** `Policy`

The policy enforces two constraints:

1. **Tool allowlist** -- only tools in the allowlist may be called.
2. **Sandbox path enforcement** -- all path arguments are resolved and checked
   against `inside_sandbox()` from `layla/tools/sandbox_core.py`.

**Default Tier-0 tools** (read-only):

```
read_file, list_dir, grep_code, glob_files, file_info,
python_ast, workspace_map, search_codebase
```

The allowlist can be overridden via `cfg["autonomous_tool_allowlist"]`.  Network
access is controlled by `cfg["autonomous_allow_network"]` (default: False).

**Path argument keys checked:**
`path`, `paths`, `root`, `repo`, `cwd`, `workspace_root`, `directory`

Any path outside the sandbox raises `PolicyViolation`.  Any path that fails
resolution is also rejected defensively.

### 4.2 Value Gate

**File:** `autonomous/value_gate.py`
**Function:** `evaluate_value_gate(goal, context="")`

A deterministic, heuristic-based gate that runs before any LLM or tool calls.
It decides whether the goal is suitable for autonomous investigation.

**Rejection criteria (returns `ok=False`):**

| Criterion | Reason string |
|-----------|---------------|
| Empty goal | `empty_goal` |
| Short trivial greeting (<=12 chars, starts with hi/hello/thanks/ok/k) | `trivial_greeting` |
| Matches direct-action regex patterns (write file, create file, delete, run, execute, apply patch, git push, pip install, shell, fix the code, implement, add a feature) | `direct_action_use_agent` |
| < 35 chars and no investigation keywords | `simple_task_use_agent` |

**Acceptance criteria (returns `ok=True` when score >= 3):**

Points are accumulated:
- +2 for goal length >= 120 chars
- +2 for terms like audit, explore, map, architecture, trace, root cause
- +2 for terms like repo, codebase, project, workflows, ci, release, docs
- +2 for terms like find all, everywhere, across, multiple files, search for
- +2 for terms like investigate, analyze, debug, why, how does, compare, bug, issue
- +1 for context length > 400 chars

Goals scoring < 3 are rejected with `low_leverage_use_agent`.

---

## 5. Sub-agents

**File:** `autonomous/subagents.py`

### 5.1 Current Status: STUB

The sub-agent system is defined but **not implemented**.  The `SubagentRequest`
dataclass and `run_subagents()` function exist, but the function:

- Enforces bounds (max 3 sub-agents, configurable via `autonomous_max_subagents`)
- Returns `{"ok": False, "error": "subagents_not_enabled"}` for every request
- Does NOT call `agent_loop`, spawn workers, or create nested autonomy

The docstring describes this as "Phase 2" and notes it is an intentional stub.

### 5.2 Design Intent

Based on the dataclass, the design envisions:
- Bounded helpers (max 3, depth 1 -- no recursive sub-agents)
- Each sub-agent receives a `goal` and optional `hint`
- Results would be collected as a list of dicts

---

## 6. Wiki System

### 6.1 Wiki Storage

**File:** `autonomous/wiki.py`

Wiki entries are stored as markdown files under `<workspace>/.layla/wiki/`.

**Key types:**
- `WikiCandidate` -- frozen dataclass with `title`, `slug`, `content_md`
- `WikiError` -- raised for sandbox violations

**Slug generation:** Titles are lowercased, non-alphanumeric characters replaced
with hyphens, truncated to 80 chars.

**Merge policy (`merge_wiki_markdown`):**
- If incoming content is already a substring of existing content, keep existing.
- If existing is empty, use incoming.
- Otherwise append with `\n\n---\n\n` divider.

This is a minimal append-only merge.  There is no conflict resolution, deduplication
of semantic content, or version history.

**Write gating (`write_wiki_entry`):**
- Disabled if `autonomous_wiki_enabled` is False
- Disabled if `allow_write` is False
- All paths are sandbox-checked before write

**Export from controller (`_maybe_export_wiki_markdown`):**
Triggered only when ALL of:
- `task.allow_write` is True
- `autonomous_wiki_enabled` and `autonomous_wiki_export_enabled` are both True
- Final confidence is "high"
- At least 2 unique files were accessed during the investigation

### 6.2 Wiki Retrieval

**File:** `autonomous/wiki_retrieval.py`
**Function:** `try_wiki_retrieval(goal, workspace_root, cfg)`

Scans `.layla/wiki/*.md` for a matching entry using Jaccard token similarity.

**Matching algorithm:**
1. Tokenize goal (split on non-word chars, keep tokens >= 3 chars)
2. For each wiki file: parse optional YAML frontmatter, extract title, tags, body,
   and path-like references
3. Build corpus from title + slug + tags + body[:12000] + path references
4. Compute Jaccard similarity between goal tokens and corpus tokens
5. Boost score by up to 5% if frontmatter tags match
6. Return best match if score >= threshold (default 0.18)

**Returned payload fields:** `summary`, `findings`, `confidence` (always "medium"),
`wiki_path`, `wiki_title`, `wiki_slug`, `match_score`

**Configuration:**
- `autonomous_wiki_match_threshold`: default 0.18
- `autonomous_prefetch_wiki_max_files`: default 80
- `autonomous_prefetch_wiki_max_chars_per_file`: default 48000

---

## 7. Investigation Reuse & Prefetch

### 7.1 Investigation Reuse Storage

**File:** `autonomous/investigation_reuse.py`
**Function:** `maybe_append_investigation_reuse(cfg, workspace_root, goal, summary, findings, confidence, run_id)`

High-confidence investigation results are persisted as JSONL lines in
`<workspace>/.layla/investigation_reuse.jsonl`.

**Gating conditions:**
- Confidence must be "high"
- `investigation_reuse_store_enabled` must be True in config

**Record schema (one JSON line):**
```json
{
    "ts": <unix_timestamp>,
    "run_id": "<uuid>",
    "goal": "<goal text, max 4000 chars>",
    "summary": "<summary, max 12000 chars>",
    "findings": [<max 50 findings>],
    "confidence": "high"
}
```

### 7.2 Reuse Retrieval

**File:** `autonomous/reuse_retrieval.py`
**Function:** `try_reuse_retrieval(goal, workspace_root, cfg)`

Matches the current goal against stored investigation records.

**Matching algorithm:**
1. Read last `autonomous_prefetch_jsonl_max_bytes` (default 2MB) of the JSONL file
2. For each record, compute a combined score:
   - `g_goal` = Jaccard(goal_tokens, record.goal_tokens)
   - `g_sum` = Jaccard(goal_tokens, record.summary_tokens)
   - `score` = max(g_goal, 0.65 * g_goal + 0.35 * g_sum)
3. Return best match if score >= threshold (default 0.22)

### 7.3 Chroma Retrieval

**File:** `autonomous/chroma_retrieval.py`
**Function:** `try_chroma_retrieval(goal, workspace_root, cfg)`

Queries the global Chroma vector store for embedded learnings matching the goal.

**Configuration:**
- `autonomous_chroma_enabled`: default True
- `use_chroma`: default True
- `autonomous_chroma_match_threshold`: default 0.75 (cosine similarity)
- `autonomous_chroma_top_k`: default 3

**Notable:** `workspace_root` is accepted for API symmetry but unused -- Chroma
learnings are global, not workspace-scoped.

---

## 8. Budget System

**File:** `autonomous/budget.py`
**Class:** `Budget`

### 8.1 Dual Budget Enforcement

The budget enforces two independent limits:

| Limit | Configured via | Default |
|-------|---------------|---------|
| Maximum step count | `AutonomousTask.max_steps` | 50 |
| Wall-clock timeout | `AutonomousTask.timeout_seconds` | 60 seconds |

### 8.2 Enforcement Mechanism

`consume_step()` is called at the top of each loop iteration.  It:
1. Increments `steps_used`
2. Checks `steps_used > max_steps` -- raises `BudgetExceeded("max_steps_exceeded")`
3. Checks `elapsed_seconds() > timeout_seconds` -- raises `BudgetExceeded("timeout_exceeded")`

The `BudgetExceeded` exception is caught by the controller's outer try/except and
sets the `stopped_reason` accordingly.

### 8.3 Budget Hint

The planner receives a budget hint string on each step:
```
steps_remaining=N time_remaining_seconds=M
```
This allows the planner to prioritize high-signal actions as budget runs low.

### 8.4 Budget Counters in Response

The final response includes:
```json
{
    "budget_counters": {
        "steps_used": <int>,
        "max_steps": <int>,
        "elapsed_seconds": <float>,
        "timeout_seconds": <int>
    }
}
```

---

## 9. Context & Caching

### 9.1 ContextState

**File:** `autonomous/context.py`
**Class:** `ContextState`

Tracks accumulated state within a single autonomous run:

- **known_facts** -- list of established facts (currently unused by controller)
- **open_questions** -- list of unresolved questions (currently unused by controller)
- **progress** -- rolling list of compressed tool result summaries (capped at 24)
- **last_result_summary** -- compressed summary of the most recent tool result
- **tool_cache** -- in-run cache: `(tool, args_json) -> result dict`
- **path_reads** -- normalized path -> last read_file result (deduplication)

**Planner context summary** (`summarize_for_planner()`):
```json
{
    "goal": "...",
    "known_facts": [...],
    "open_questions": [...],
    "progress": [...],
    "last_result_summary": "...",
    "files_read_this_run": [...]
}
```

### 9.2 Three-Level Read Cache

For `read_file` calls, results are checked in this order:

1. **In-run tool cache** -- exact (tool, args) match
2. **Path deduplication** -- normalized absolute path match (handles different arg
   spellings for the same file)
3. **Cross-run LRU cache** -- keyed by `(resolved_path, mtime_ns, file_size)`,
   shared across runs via a process-global singleton

### 9.3 Cross-Run Read Cache

**File:** `autonomous/read_cache.py`
**Class:** `CrossRunReadCache`

An LRU cache (default 512 entries) that persists across autonomous runs within the
same process.  Keys include file mtime and size so stale entries are automatically
invalidated when files change.

Thread-safe via `threading.Lock`.  Deep-copies values via JSON round-trip to prevent
mutation.

**Configuration:**
- `autonomous_read_cache_enabled`: default True
- `autonomous_read_cache_max_entries`: default 512

### 9.4 Tool Result Compression

`compress_tool_result(tool, result, max_chars=2400)` produces a short summary string
for the planner.  Strategies by priority:
1. Error results: `"tool: ok=false <error>"`
2. Deduped reads: `"tool: deduped_hit <path>"`
3. Named fields (summary, message, path): `"tool: <value>"`
4. Fallback: JSON dump truncated to max_chars

---

## 10. Aggregator

**File:** `autonomous/aggregator.py`

### 10.1 Response Assembly (`aggregate()`)

Builds the final response dict from:
- Steps taken and their results
- Value gate outcome
- Stopped reason (normalized via `normalize_stopped_reason()`)
- Optionally a prefetch final payload

**Response schema:**
```json
{
    "ok": true,
    "goal": "...",
    "value_gate": {"ok": true, "reason": "...", "score": N},
    "stopped_reason": "planner_final|budget_exceeded|...",
    "steps_used": N,
    "summary": "...",
    "reasoning": "...",
    "investigation_trace": "### Steps\n...\n\n### Findings\n...",
    "reasoning_summary": "...",
    "findings": [{"insight": "...", "evidence": [...]}],
    "next_steps": [{"action": "...", "tool": "...", "reason": "...", "confidence": "..."}],
    "proposed_actions": [...],
    "confidence": "low|medium|high",
    "confidence_basis": {...},
    "tool_errors": [...],
    "wiki_candidates": [...],
    "files_accessed": [...],
    "investigation_engine": true,
    "source": "fresh|reuse|wiki|chroma",
    "reused": false,
    "planner_model": "...",
    "budget_counters": {...}
}
```

### 10.2 Confidence Derivation

Confidence is not simply passed through from the LLM.  It is derived via a scoring
model:

**Base score** from model confidence: low=2, medium=3, high=4

**Boosts:**
- +1 if >= 3 unique files read
- +1 if >= 2 findings have evidence

**Penalties:**
- -1 if budget was exhausted without structured final
- -1 if any tool errors occurred
- -1 if >= 2 planner retry attempts
- -1 (additional) if >= 4 planner retry attempts

Score is clamped to [0, 5] and mapped: 0-2 = low, 3 = medium, 4-5 = high.

### 10.3 Fallback Findings

If the planner did not emit structured findings (e.g., budget exhaustion), the
aggregator derives them from tool step results:
- grep_code matches
- read_file content lengths

### 10.4 Investigation Trace

A compressed human-readable trace is built from steps and findings, capped at 2800
chars.  This appears in the response as `investigation_trace`.

---

## 11. Audit Log

**File:** `autonomous/audit.py`
**Class:** `AuditLog`

Writes to `.governance/autonomous_audit.jsonl` (relative to agent dir).

**Event types:**
- `step` -- one per tool call, includes args summary (max 1200 chars), result size,
  and truncated result if > 12000 chars
- `final` -- the complete final response dict

All events include an ISO 8601 UTC timestamp and the run_id (UUID).

---

## 12. Research Pipeline (15 Stages)

### 12.1 Architecture

The research pipeline is a sequential, async stage runner split across two modules:

1. **Base stages** (`research_stages.py`) -- 6 stages
2. **Intelligence stages** (`research_intelligence.py`) -- 9 stages

Each stage:
1. Loads context from all previously completed stages
2. Constructs a goal prompt
3. Calls `autonomous_run()` via `asyncio.to_thread()` (synchronous autonomous engine)
4. Extracts JSON and markdown from the result
5. Persists output to `.research_brain/<subdir>/<filename>`
6. Updates mission state in `.research_brain/mission_state.json`

### 12.2 Base Stages (research_stages.py)

| # | Stage | Output file | Description |
|---|-------|-------------|-------------|
| 1 | **mapping** | `maps/system_map.json` | Map repo structure, entrypoints, dependencies |
| 2 | **investigation** | `investigations/notes.md` | Summarize docs, compare patterns, use fetch_url |
| 3 | **verification** | `verifications/verified.md` | Run read-only probes in .research_lab sandbox |
| 3.5 | **contradiction_check** | `contradictions/check.md` | Compare claims, detect conflicts, annotate uncertainty |
| 4 | **distillation** | `distilled/knowledge.md` | Distill previous outputs into concise knowledge |
| 5 | **synthesis** | `strategic/model.md` | Strategic synthesis and recommendations |

The synthesis stage applies a usefulness gate (`is_useful_output`): if the output
lacks actionable signal words (recommend, should, risk, improve, replace, refactor,
adopt, avoid, opportunity, tradeoff), "INSUFFICIENT_ACTIONABLE_INSIGHT" is appended.

### 12.3 Intelligence Stages (research_intelligence.py)

Run only when `mission_depth == "full"`.  Each stage receives continuity context
from all base stages plus all preceding intelligence stages.

| # | Stage | Output file | Description |
|---|-------|-------------|-------------|
| 6 | **confidence** | `confidence/confidence.json` | Score findings as low/medium/high |
| 7 | **consistency** | `consistency/consistency.md` | Detect contradictions, list confirmed truths and open questions |
| 8 | **risk** | `risk/risk_model.md` | Fragility, tight coupling, maintenance burden, hidden complexity |
| 9 | **tradeoffs** | `tradeoffs/tradeoffs.md` | Benefit, cost, risk, reversibility for each upgrade |
| 10 | **patterns** | `patterns/patterns.md` | Recurring weaknesses, architecture smells, reusable strategies |
| 11 | **actions** | `actions/action_queue.md` | Top 3 high-impact next steps with impact/effort/risk/confidence |
| 12 | **agenda** | `agenda/research_agenda.md` | Next research direction from uncertainty, leverage, risk |
| 13 | **journal** | `journal/mission_journal.md` | What was explored, changed, failed, evolved |
| 14 | **summary** | `summaries/24h_summary.md` | Final synthesis: learned, verified, uncertain, next actions |

### 12.4 Stage Depth Configuration

`stages_for_depth(depth, next_stage)` controls which stages run:

| Depth | Stages |
|-------|--------|
| `"map"` | mapping only |
| `"deep"` | mapping + investigation |
| `"full"` | all 6 base + 9 intelligence = 15 stages |
| (default) | 6 base stages |

If `next_stage=True`, the next stage after the last planned one is appended.

### 12.5 Context Continuity

Each stage loads outputs from all prior stages:

- **Base context** (`load_research_context`): loads `system_map.json`, `notes.md`,
  `verified.md`, `check.md`, `knowledge.md` progressively
- **Intelligence context** (`load_intelligence_context`): loads all base outputs
  plus all intelligence outputs up to (not including) the current stage

Context is injected into the goal prompt, capped at 15000 chars for intelligence
stages and uncapped for base stages (potential issue).

### 12.6 Mission State

Persisted to `.research_brain/mission_state.json`:
```json
{
    "stage": "<current_stage_name>",
    "progress": {},
    "completed": ["mapping", "investigation", ...],
    "status": null,
    "last_run": null
}
```

### 12.7 Promotable Learnings

`get_promotable_research_learnings()` extracts verified truths, patterns, and
strategic insights for promotion to the memory/learnings system.  Sources:
- `verifications/verified.md`
- `consistency/consistency.md` (only if contains "confirmed" or "verified")
- `patterns/patterns.md`
- `strategic/model.md`

Each is truncated to 3000 chars.  Speculative output is deliberately excluded.

---

## 13. Research Lab

**File:** `research_lab.py`

### 13.1 Directory Structure

```
agent/
    .research_lab/
        workspace/
            source_copy/     # Full copy of target repo (excluding .git, venv, etc.)
            experiments/     # Scratch space for probes
            notes/           # Scratch notes
    .research_brain/         # Persistent stage outputs (see Section 12)
    .research_output/        # Final output destination
    research_missions/       # Mission preset JSON files
```

### 13.2 Source Copy

`copy_source_to_lab(workspace_root)` creates a filtered copy of the target
repository into `.research_lab/workspace/source_copy/`.  Excludes:
`.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.research_lab`,
`.research_brain`, `.research_output`.

Files larger than 5MB are skipped.  The previous copy is fully replaced
(`shutil.rmtree` then re-copy).

### 13.3 Mission Presets

`load_mission_preset(mission_type)` loads from `research_missions/<type>.json`.
Falls back to a default read-only objective if the file is missing.

### 13.4 Default Output Structure

The default output template expects:
- System Understanding
- Weakness Map
- Upgrade Opportunities
- Lens Case Study (Carpenter, Assembly, DevOps, Geometry, Product, Strategist)
- Suggested Roadmap

### 13.5 Allowed Brain Files

For external access, only these brain files are exposed:
```
summaries/24h_summary.md
actions/action_queue.md
patterns/patterns.md
risk/risk_model.md
```

---

## 14. Research Report Service

**File:** `services/research_report.py`

### 14.1 Citation Extraction

`extract_citations(state, text_fallback)` walks tool steps and raw text to find:
- URLs (http/https)
- Windows paths (`C:\...`)
- POSIX paths (`/path/to/file`)
- API endpoints (`/api/...`)
- Knowledge sources (from `state["cited_knowledge_sources"]`)

Results are deduplicated and capped (URLs: 80, file paths: 80, API endpoints: 40,
knowledge sources: 50).

### 14.2 Report Templates

`format_research_report(raw_output, tool_steps, template_type, title, citations)`
formats output into one of three templates:

| Template | Structure |
|----------|-----------|
| `technical_report` (default) | Summary, Evidence & trace, Recommendations, Citations |
| `briefing` / `brief` | Executive briefing, Method, Citations |
| `comparison_report` / `compare` | Comparison, Criteria & trade-offs, Recommendation, Citations |

---

## 15. Engineering Pipeline

**File:** `services/engineering_pipeline.py`

### 15.1 Overview

The engineering pipeline is a separate execution path for write-capable operations.
Unlike the autonomous investigation engine (read-only), this pipeline can create,
modify, and delete files.

### 15.2 Pipeline Stages

```
run_execute_pipeline()
    |
    +---> Clarifier (LLM gate: is goal sufficiently specified?)
    |         +---> needs_input --> return questions, halt
    |
    +---> Planner (create_plan: 3-8 steps)
    |
    +---> Critic A: "argue the plan is wrong" (2-5 objections)
    +---> Critic B: "argue the plan is incomplete" (2-5 objections)
    |
    +---> Refiner: merge objections, produce single revised plan
    |
    +---> execute_plan() (governed, with engineering lock)
    |
    +---> Validator (mandatory gate: is objective met?)
    |         +---> retry if suggested (max 2 retries)
    |
    +---> Update plan status in DB (done | blocked)
```

### 15.3 Clarifier

`run_clarifier(goal, context, cfg, clarification_reply)` uses an LLM to check if
the goal is underspecified.  Returns `{"status": "ok"}` or
`{"status": "needs_input", "questions": [...]}`.

This is a blocking gate -- execution cannot proceed without sufficient specification.

### 15.4 Dual Critics

Two forced critics run in sequence (not parallel):
- **Critic A** (`run_critic_wrong`): must argue the plan is wrong or risky
- **Critic B** (`run_critic_incomplete`): must argue the plan is incomplete

Both are prompt-engineered to never approve -- they must always object.  This
ensures adversarial review.

### 15.5 Refiner

`run_refiner(plan, objections_a, objections_b, goal, cfg)` produces a single
revised plan (3-8 steps).  The plan is completely overwritten, not patched.

### 15.6 Execution Lock

`_engineering_planning_locked` (ContextVar) prevents nested engineering pipeline
re-entry during plan execution.  This is critical because `execute_plan` calls
`agent_run_fn` which could otherwise trigger another planning cycle.

### 15.7 Validator

`run_validator(goal, plan_summary, steps_done, all_steps_ok, cfg)` is a mandatory
post-execution gate.  Returns `{ok, failure_report, retry_suggested}`.

If validation fails and retry is suggested, the entire execute_plan is re-run
(max `engineering_pipeline_validator_max_retries` retries, default 1, max 2).

### 15.8 Light Plan Mode

`run_plan_light(goal, context, workspace_root, conversation_id, cfg)` is a
lighter variant that only runs clarifier + planner + persist, without critics,
refiner, execution, or validation.  Returns `plan_ready` status for human review.

---

## 16. Known Issues

### 16.1 Dead Code and Incomplete Features

1. **Sub-agents are entirely stubbed** (`subagents.py`).  The `run_subagents()`
   function always returns `subagents_not_enabled`.  No caller in the codebase
   invokes it.

2. **ContextState.known_facts and open_questions are never populated** by the
   controller.  The planner receives them in context but they are always empty
   lists.

3. **Policy.allow_network** is stored but never checked by `validate_tool_call()`.
   Network-capable tools are simply not in the default allowlist, so this flag has
   no enforcement effect.

### 16.2 Missing Error Handling

4. **Base stage context loading is uncapped** (`load_research_context` in
   `research_stages.py`).  Previous stage outputs are loaded without character
   limits, unlike intelligence stages which cap at 12000/8000/15000 chars.  A large
   system_map.json could cause prompt overflow.

5. **Research stage `_run_stage`** extracts `final` from `steps[-1].get("result")`
   which could silently return empty string if the autonomous run produces no steps.
   The `"no_progress"` status check (< 500 chars) partially mitigates this but does
   not distinguish between "no output" and "short valid output".

6. **Wiki merge is append-only with no size limit.**  Repeated investigations on the
   same topic will cause unbounded growth of wiki markdown files.

7. **JSONL reuse file has no rotation or size limit.**  The retrieval reads the last
   2MB, but the file itself grows indefinitely.

### 16.3 Untested or Fragile Paths

8. **Chroma retrieval silently returns None on any exception** from the vector
   store layer.  Misconfiguration is invisible.

9. **Cross-run read cache uses `st_mtime_ns`** which is platform-dependent.  On
   some filesystems or platforms, nanosecond precision may not be available,
   potentially causing false cache hits.

10. **The investigation stage goal mentions `fetch_url`** but this tool is not in
    the default Tier-0 allowlist.  The stage may not be able to fulfill its stated
    purpose without custom configuration.

11. **Engineering pipeline critic prompts are not adversarial enough** -- they use
    `run_completion` with `temperature=0.2`, which may produce mild objections.

---

## 17. Stability Assessment

| Component | File(s) | Rating | Notes |
|-----------|---------|--------|-------|
| **Autonomous Controller** | `controller.py` | **STABLE** | Well-structured step loop with clean exit conditions, caching, audit. Main execution path is thoroughly wired. |
| **Planner** | `planner.py` | **STABLE** | Simple, focused LLM wrapper with retry. Low token budget keeps it predictable. |
| **Policy** | `policy.py` | **STABLE** | Correct sandbox enforcement, clean allowlist model. `allow_network` flag is wired but unenforced (minor). |
| **Value Gate** | `value_gate.py` | **STABLE** | Pure deterministic function, no side effects. Easy to test and reason about. |
| **Budget** | `budget.py` | **STABLE** | Minimal, correct implementation. No edge cases or race conditions. |
| **Context & Caching** | `context.py`, `read_cache.py` | **STABLE** | Thread-safe cross-run cache, clean deduplication. JSON round-trip copy prevents mutation bugs. |
| **Aggregator** | `aggregator.py` | **STABLE** | Complex but well-structured confidence derivation. All paths produce valid response shapes. |
| **Audit Log** | `audit.py` | **STABLE** | Append-only JSONL with truncation for large results. Simple and reliable. |
| **Wiki System** | `wiki.py`, `wiki_retrieval.py` | **FRAGILE** | Append-only merge with no size bounds. Retrieval uses Jaccard which has limited semantic understanding. Works but will degrade with scale. |
| **Investigation Reuse** | `investigation_reuse.py`, `reuse_retrieval.py` | **FRAGILE** | No file rotation, no size cap on storage side. Retrieval is correct but Jaccard matching may miss semantically similar but lexically different goals. |
| **Chroma Retrieval** | `chroma_retrieval.py` | **FRAGILE** | Thin wrapper that silently swallows all errors. Depends on external Chroma store being correctly configured and populated. |
| **Sub-agents** | `subagents.py` | **DEAD** | Entirely stubbed. No implementation, no callers. |
| **Research Stages (base)** | `research_stages.py` | **STABLE** | Clean sequential runner with state persistence and context continuity. Uncapped context loading is a minor risk. |
| **Research Intelligence** | `research_intelligence.py` | **STABLE** | Follows same pattern as base stages. 9 stages are repetitive but correct. |
| **Research Lab** | `research_lab.py` | **STABLE** | Directory management and filtered copy. Robust error handling. |
| **Research Utilities** | `research_utils.py` | **STABLE** | Two small pure functions. No issues. |
| **Research Report** | `services/research_report.py` | **STABLE** | Pure formatting. Citation extraction is thorough if somewhat regex-heavy. |
| **Engineering Pipeline** | `services/engineering_pipeline.py` | **STABLE** | Full adversarial pipeline with clarifier, dual critics, refiner, validator, retry, and execution lock. Most complex component but well-guarded. |

### Summary

The core autonomous investigation engine (controller, planner, policy, budget,
aggregator) is **stable and production-ready**.  The research pipeline is
**structurally sound** but relies heavily on the autonomous engine underneath.

The main fragility points are in the storage/retrieval layer: wiki append-only
growth, JSONL file size, and Jaccard token matching limitations.  The sub-agent
system is dead code.

The engineering pipeline is the most complex component but benefits from its
multi-critic, forced-adversarial design which provides strong self-correction.

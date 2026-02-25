# Architecture — One-Page Overview

## Pinned versions and paths

- **Python**: 3.10+ (tested 3.10–3.12). Dependencies: `agent/requirements.txt`.
- **Database**: SQLite at **repo root** `layla.db` (defined in `agent/jinx/memory/db.py` as `Path(__file__).resolve().parent.parent.parent.parent / "layla.db"`). All persistent memory (learnings, study_plans, wakeup_log, audit, aspect_memories, project_context, capabilities) lives in this single file.

## Request flow

1. **Client** → HTTP to FastAPI (`agent/main.py`) on `localhost:8000`.
2. **Routes**:
   - `/agent`, `/learn/` → `routers/agent` (uses `shared_state`: history, touch_activity, append_history).
   - `/research_mission`, `/research`, `/research_mission/state`, `/research_output/last`, `/research_brain/file`, `/research_mission/debug`, `/research_mission/verify` → `routers/research` (uses `research_lab` paths and helpers, `shared_state`, `agent_loop`).
   - `/study_plans`, `/wakeup`, … → `routers/study`; `/approve`, `/pending` → `routers/approvals`.
   - `/health`, `/v1/models`, `/v1/chat/completions`, `/system_export`, `/ui`, `/` → `main.py`.
3. **Agent path**: `/agent` (and v1 chat) call `agent_loop.autonomous_run(goal, context, workspace_root, allow_write, allow_run, …)`. Optional `research_mode=True` for research/router endpoints.
4. **agent_loop**:
   - Loads config (`runtime_safety`), aspect (orchestrator), optional deliberation.
   - **Decision step**: `_llm_decision()` asks the LLM for one JSON line (action: tool | reason, tool name, objective_complete, …). Uses `decision_schema.parse_decision()` (Pydantic when available) with a single retry on parse failure.
   - **Tool step**: If action is `tool`, runs one tool from the registry (read_file, write_file, apply_patch, shell, run_python, grep_code, list_dir, git_*, etc.). Write/run are gated by `allow_write`/`allow_run` and approval; in research_mode, writes/runs restricted to `.research_lab`.
   - **Reason step**: If action is `reason` or objective_complete, calls `_completion()` to generate the final reply.
   - Loop until objective_complete or max steps/timeout; returns `{ steps, status, aspect, … }`.
5. **Approval**: When a tool needs approval, the loop returns (or enqueues) an approval request; client approves via `/approve`; the same or a follow-up run can then proceed.

## Where state lives

| What | Where |
|------|--------|
| Learnings, study plans, wakeup log, audit | SQLite **repo root** `layla.db` |
| Optional semantic memory | FAISS/Chroma vector store (config-driven) |
| Conversation history (in-memory) | `main.py` → `shared_state` (deque); used by agent and research routes |
| Pending approvals | In-memory list + audit in DB (see `shared_state`, approvals router) |
| Research lab (sandbox) | `agent/.research_lab/` (lab subdirs: source_copy, notes, experiments) |
| Research outputs | `agent/.research_output/` (e.g. last_research.md), `agent/.research_brain/` (mission_state, maps, strategic, …) |
| Config | `agent/runtime_config.json`; hardware defaults from probe if used |

## Scheduler and wakeup

- **Scheduler**: Optional background job (e.g. APScheduler) runs autonomous study only when there has been recent activity (touch_activity on /agent, /wakeup, /learn, /ui). Config: `scheduler_study_enabled`, `scheduler_interval_minutes`, `scheduler_recent_activity_minutes`.
- **Wakeup**: `GET /wakeup` (or CLI `layla.py wakeup`) marks activity, logs wakeup, and returns last wakeup time, active study plans, and optional “what was studied since last session.” Echo aspect often used for greeting and pattern reflection.

## Key files

- `agent/main.py` — App, lifespan, shared_state setup, health, v1/chat, system_export, UI routes.
- `agent/agent_loop.py` — autonomous_run, _llm_decision (with decision_schema + retry), tools, reason loop.
- `agent/decision_schema.py` — Pydantic decision model and parse_decision(text, valid_tools).
- `agent/research_lab.py` — Research lab paths and helpers (copy_source_to_lab, load_mission_preset, etc.).
- `agent/routers/agent.py` — POST /learn/, POST /agent.
- `agent/routers/research.py` — Research mission and read-only research endpoints.
- `agent/routers/study.py` — Study plans, wakeup.
- `agent/routers/approvals.py` — Approve, pending.
- `agent/shared_state.py` — Refs for history, touch_activity, pending, audit, append_history, run_autonomous_study.

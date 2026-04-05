# Layla — Full Technical Audit (Ground Truth)

**Document role:** Authoritative deep-inspection report for engineers who need verifiable understanding of the system, including gaps, partial implementations, and risks.

**Last verified against tree:** 2026-04-03 (agent runtime, docs cross-check; scope boundaries clause for model/load/OS; planning-first + file-plan executor + step tool allowlist flag).

---

## Methodology (honest bounds)

Evidence gathered via repository traversal, targeted `grep` (TODO/FIXME/NotImplementedError), reading [`agent/main.py`](../agent/main.py), [`agent/agent_loop.py`](../agent/agent_loop.py) (sampled + symbol search), [`agent/shared_state.py`](../agent/shared_state.py), [`agent/core/loop.py`](../agent/core/loop.py), [`docs/PARITY_AUDIT.md`](PARITY_AUDIT.md), [`docs/CCUNPACKED_ALIGNMENT.md`](CCUNPACKED_ALIGNMENT.md), [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md), [`agent/tests/test_registered_tools_count.py`](../agent/tests/test_registered_tools_count.py), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), service/router inventories, and [`agent/layla/tools/registry.py`](../agent/layla/tools/registry.py) (symbols). **Not performed:** line-by-line read of all ~78 `agent/services/*.py`, all tests, all `knowledge/`, or vendored trees. Claims below are **evidence-backed** or tagged **UNVERIFIED (sampled)**.

**Repository scope for “the system”:** Primary runtime = [`agent/`](../agent/) FastAPI app + [`personalities/`](../personalities/). Adjacent but distinct: [`cursor-layla-mcp/`](../cursor-layla-mcp/) (Cursor MCP server), [`fabrication_assist/`](../fabrication_assist/) (separate package per AGENTS), [`openclaude-main/`](../openclaude-main/) (reference/vendored pattern code — **not** imported by Layla main app per AGENTS map). This audit focuses on **Layla agent runtime** unless noted.

### Explicit scope boundaries (not Layla-owned guarantees)

These are **out of scope** for scoring “Layla correctness” and should not be read as implementation gaps in this repo:

1. **Model quality and behavior** — Valid tool JSON, multi-step chaining, reasoning quality, and long-context behavior depend on the **GGUF and/or remote inference backend** (and prompts), not on the FastAPI agent shell. This audit addresses **gating, routing, and loop wiring**, not LM fitness.
2. **Performance under load** — Throughput, tail latency, and behavior under heavy concurrent use are **infrastructure and deployment** concerns. The tree does not define SLOs or provide load-test evidence for scaled multi-tenant operation.
3. **OS-level enforcement edge cases** — Cgroup delegation, RLIMIT semantics, and Windows Job Object behavior are **documented as best-effort** ([`docs/PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md), [`docs/RUNBOOKS.md`](RUNBOOKS.md)). Residual kernel/OS nuance is **operator and platform** responsibility, not an application completeness debt.

---

## 1. Executive Truth Summary

**What this system actually is (verified):** A **self-hosted FastAPI** application ([`agent/main.py`](../agent/main.py)) exposing `/agent`, background task APIs, approvals, memory/study/research routes, static `/ui`, and health. Core cognition is [`agent_loop.autonomous_run()`](../agent/agent_loop.py) — JSON **decision** loop (tool vs reason) with optional streaming, gated writes/runs, SQLite + optional Chroma memory, and a large in-process [`layla.tools.registry.TOOLS`](../agent/layla/tools/registry.py) surface. Tool count is **machine-enforced** as **186** ([`EXPECTED_TOOL_COUNT`](../agent/tests/test_registered_tools_count.py)).

**What it is not (verified):** Not a multi-tenant cloud service; **not** an Ink/TUI-primary product (HTTP-first; TUI/CLI exist per docs but not re-audited here — **UNVERIFIED: CLI surface**); **not** a nested multi-agent orchestration graph (CCUNPACKED explicitly: no teams/ListPeers); **not** in-process seccomp/container isolation (operator-level containers/wrappers only — see [`docs/PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md)).

**Maturity:** **Hybrid** — strong engineering for a **local operator-controlled** deployment (approval gates, config, tests, CI on Ubuntu + Windows for core subset), but **not** “production SaaS at scale”: no formal threat model in-repo, mmap/GPU/LLM paths are environment-variable, and many subsystems are **best-effort** (cgroups, RLIMIT, Windows Job Object) as documented.

**Top 5 strengths (evidence):**

1. **Single enforced tool registry + count test** — drift is detectable ([`test_registered_tools_count.py`](../agent/tests/test_registered_tools_count.py)).
2. **Approval pipeline** — wired through routers and agent loop (AGENTS + [`routers/approvals.py`](../agent/routers/approvals.py) + session grants).
3. **Dual background execution model** — cooperative thread vs hard subprocess cancel ([`routers/agent.py`](../agent/routers/agent.py), [`services/background_subprocess.py`](../agent/services/background_subprocess.py), [`background_job_worker.py`](../agent/background_job_worker.py)); PARITY_AUDIT row matches.
4. **Inference indirection** — [`services/inference_router.py`](../agent/services/inference_router.py) + [`services/llm_gateway.py`](../agent/services/llm_gateway.py) support local GGUF vs HTTP backends (verified file presence + PARITY rows).
5. **CI discipline** — pytest with markers, coverage floor, stub `runtime_config.json`, **Windows job present** (`.github/workflows/ci.yml`).

**Top 5 weaknesses (evidence + inference):**

1. **Monolithic core** — `agent_loop.py` ~3.8k lines, `registry.py` ~5.4k lines (line counts via tooling); maintainability risk (**measured**).
2. **Partial architectural extraction** — [`core/loop.py`](../agent/core/loop.py): `run_loop` only builds a snapshot via `core.observer` and returns; phases 2–6 remain in `agent_loop` (see module docstring).
3. **MCP “incremental”** — [`mcp_client.py`](../agent/services/mcp_client.py) module docstring states wiring is **incremental**; integration is **opt-in** tools + optional prompt injection (`mcp_inject_tool_summary_in_decisions`) and special-casing `mcp_tools_call` in agent_loop. **No** persistent merged tool schema/OAuth in-agent (CCUNPACKED + PARITY align).
4. **Sandbox is path-policy + gates, not kernel isolation** — `inside_sandbox` pervades registry; escape class = **misconfiguration, symlink, tool bypass, or non-sandboxed tools** — **not formally proven** here.
5. **Documentation vs code volume** — Many docs ([`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), handoffs) can lag; parity docs are **explicitly maintained** ([`PARITY_AUDIT.md`](PARITY_AUDIT.md), [`parity_manifest.yaml`](parity_manifest.yaml)) but still require human updates.

---

## 2. System Architecture (Ground Truth)

### 2.1 Core execution loop (`agent_loop`)

- **Entry:** `autonomous_run()` → `schedule_slot` ([`services/resource_manager.py`](../agent/services/resource_manager.py)) → `_autonomous_run_impl` → `_autonomous_run_impl_core`.
- **Decision:** LLM emits JSON per [`decision_schema.py`](../agent/decision_schema.py) (**UNVERIFIED: full schema** in this audit pass); tool path dispatches into `TOOLS[name]` with approval / `allow_write` / `allow_run` checks (AGENTS request flow).
- **Batch tools:** PARITY_AUDIT references `decision["batch_tools"]` + `ThreadPoolExecutor` when `concurrency_safe` — **verified claim in doc**; implementation in agent_loop — **partially verified via** [`test_agent_loop_batch_tools.py`](../agent/tests/test_agent_loop_batch_tools.py).
- **Streaming:** Non-background: `stream_reason` / `StreamingResponse` from [`routers/agent.py`](../agent/routers/agent.py). Background: progress via DB/task API (ARCHITECTURE/RUNBOOKS).
- **State:** Run state dict in-loop (`state["steps"]`, etc.); conversation history in [`shared_state.py`](../agent/shared_state.py) deques per `conversation_id`; pending approvals via refs set in `shared_state.set_refs` from `main`.

### 2.2 Tool system

- **Registry:** [`agent/layla/tools/registry.py`](../agent/layla/tools/registry.py) aggregates domain manifests from [`agent/layla/tools/domains/*.py`](../agent/layla/tools/domains/) (12 domain modules).
- **Execution flow:** Agent loop selects tool name + args → optional approval → `TOOLS[name]["fn"](...)` → validation hooks (e.g. [`services/tool_output_validator.py`](../agent/services/tool_output_validator.py), `core.validator` references in agent_loop).
- **Risk metadata:** `dangerous`, `require_approval`, `risk_level` per AGENTS.

### 2.3 Routers (`agent/routers/*`)

**Verified mounted in** [`main.py`](../agent/main.py) `include_router`: `study`, `approvals`, `agent` (as `agent_router`), `agents`, `research`, `memory`, `projects`. **Additional routes** are defined on `app` directly in `main.py` (compact, health, etc.) — see **Appendix A** for enumerated list.

### 2.4 Services layer (`agent/services/*`)

**78 Python modules** under [`agent/services/`](../agent/services/) (glob count). Categories (by filename, not depth-read): LLM (`llm_gateway`, `inference_router`, `model_router`, …), memory/RAG helpers, browser, voice, hooks, MCP client, background subprocess, worker limits/cgroup, health snapshots, planners, benchmarks, etc. **UNVERIFIED per-module completeness** — treat as **capability library** with uneven test depth.

### 2.5 Background execution

| Mode | Mechanism | Cancel | Isolation |
|------|-----------|--------|-----------|
| **Thread** (default) | `threading.Thread` → `_run_background_task` | `threading.Event` `client_abort_event` in `autonomous_run` | Same process as uvicorn — **no OS cgroup/job** |
| **Subprocess** | `spawn_background_worker` → [`background_job_worker.py`](../agent/background_job_worker.py) | `cancel_worker` terminate/kill + optional psutil tree ([`background_subprocess.py`](../agent/services/background_subprocess.py)) | Separate PID; optional RLIMIT, Windows Job Object, Linux cgroup attach; **not** full container |

**State stores:** In-memory `_TASKS` in [`routers/agent.py`](../agent/routers/agent.py) + SQLite `background_tasks` via [`layla/memory/db.py`](../agent/layla/memory/db.py) (`progress_json`).

### 2.6 MCP integration

- **In-agent:** Stdio JSON-RPC client [`services/mcp_client.py`](../agent/services/mcp_client.py); tools like `mcp_tools_call` in registry; loop branches at `intent == "mcp_tools_call"` with approval/grants path.
- **External:** [`cursor-layla-mcp/`](../cursor-layla-mcp/) separate server (AGENTS map).
- **Missing vs “deep fuse”:** No OAuth handshake in core loop; tool list not merged into native schema as first-class (PARITY + module docstring).

### 2.7 Notebook / Git / sandbox (verified symbols)

- **Notebooks:** `notebook_read_cells`, `notebook_edit_cell` in registry.
- **Worktrees:** `git_worktree_add`, `git_worktree_remove`.
- **Sandbox:** `inside_sandbox`, `sandbox_root`, effective sandbox thread-local pattern at top of registry.

### 2.8 Planning-first, file plans, workspace memory (verified symbols)

- **SQLite plans:** `layla_plans` table + [`routers/plans.py`](../agent/routers/plans.py) (`/plans`, approve, execute) per [`layla/memory/db.py`](../agent/layla/memory/db.py) migrations.
- **File-backed plans:** [`routers/plan_file.py`](../agent/routers/plan_file.py) (`/plan/*`), Pydantic schema in [`services/plan_schema.py`](../agent/services/plan_schema.py) / [`plan_service.py`](../agent/services/plan_service.py); steps may include `tools[]`.
- **Iteration engine:** [`services/engine_plans.py`](../agent/services/engine_plans.py) — `run_plan_iteration`, `execute_next_file_plan_step`, `generate_or_refine_plan`; wired from [`routers/agent.py`](../agent/routers/agent.py) and [`background_job_worker.py`](../agent/background_job_worker.py) when `file_plan_id` / plan modes apply (**UNVERIFIED:** every enqueue path in one pass).
- **`planning_strict_mode`:** [`agent_loop.py`](../agent/agent_loop.py) + `_maybe_planning_strict_refusal` blocks mutating tools unless `plan_approved` (see [`test_planning_strict_mode.py`](../agent/tests/test_planning_strict_mode.py)).
- **Step tool allowlist (hard):** Non-empty `step.tools` on file-plan execution sets a thread-local allowlist ([`services/tool_allowlist_context.py`](../agent/services/tool_allowlist_context.py)); [`agent_loop.py`](../agent/agent_loop.py) rejects other tools (including `batch_tools`) with no config toggle. Empty `step.tools` → no per-step tool restriction (other gates still apply). See [`services/plan_step_governance.py`](../agent/services/plan_step_governance.py) for validation, retries, and pre-approval checks.
- **Project memory (structural JSON):** [`services/project_memory.py`](../agent/services/project_memory.py) → `.layla/project_memory.json`; schema includes `modules`, `issues`, `plans`, `signals`, `aspects`, etc. (see `IMPLEMENTATION_STATUS` / RUNBOOKS).
- **Relationship codex (scaffold):** [`services/relationship_codex.py`](../agent/services/relationship_codex.py) — helpers present; **not** injected into default system prompts (**UNVERIFIED:** all call sites).

### 2.9 Data / control flow (condensed)

```mermaid
sequenceDiagram
  participant Client
  participant Router as routers_agent
  participant Loop as agent_loop
  participant Reg as TOOLS_registry
  participant LLM as llm_gateway
  participant DB as sqlite_chroma

  Client->>Router: POST /agent
  Router->>Loop: autonomous_run
  Loop->>LLM: decision_completion
  LLM-->>Loop: JSON decision
  alt action_tool
    Loop->>Reg: TOOLS[name](args)
    Reg-->>Loop: result dict
    opt approval_required
      Loop-->>Client: pending approval
    end
  else action_reason
    Loop->>LLM: final completion stream_or_json
  end
  Loop->>DB: distill_save_optional
  Loop-->>Router: state dict
  Router-->>Client: JSON or SSE
```

**State mutation loci:** `shared_state` histories; `main` pending approvals; `db.py` learnings/tasks; optional Chroma in `vector_store.py` (**UNVERIFIED: write path details**).

---

## 3. Feature Completeness Audit

| Subsystem | Status | Evidence | Gap |
|-----------|--------|----------|-----|
| Agent loop autonomy | **COMPLETE** (functional) | `autonomous_run` + `test_agent_loop.py` | Extraction to `core/loop` **PARTIAL** |
| Tool execution single | **COMPLETE** | Registry + loop dispatch | — |
| Tool batch | **COMPLETE** (per PARITY + tests) | `test_agent_loop_batch_tools.py` | **UNVERIFIED:** all tools classified correctly |
| MCP client | **PARTIAL** | `mcp_client.py` + opt-in config | No OAuth; incremental docstring |
| MCP loop integration | **PARTIAL** | Special branch `mcp_tools_call` | Not native-tool parity |
| Background thread | **COMPLETE** | router + cancel tests | No OS isolation |
| Background subprocess | **COMPLETE** | spawn/wait/cancel tests | Local GGUF = N× RAM unless HTTP inference |
| Cancellation | **COMPLETE** (dual semantics) | PARITY_AUDIT + code | Races: **UNVERIFIED formal model** |
| Sandbox enforcement | **PARTIAL** | Path checks in registry | Not kernel-enforced |
| OS limits | **PARTIAL** | cgroup/job/rlimit + docs | Best-effort; mmap caveats |
| Inference routing | **COMPLETE** (feature present) | `inference_router.py` | Operator misconfig risk |
| Progress reporting | **COMPLETE** (background) | ARCHITECTURE/RUNBOOKS | Not token stream for background |
| Spawn / sub-agents | **PARTIAL** | `POST /agents/spawn` | No nested graph (CCUNPACKED) |
| SQLite durable plans | **COMPLETE** (API + execute governance) | `POST /plans/{id}/execute` → `planner.execute_plan(step_governance=True)`; `done` vs `blocked` | **`POST /execute_plan`** and in-loop `execute_plan` remain legacy sequential (no step_governance) |
| File-backed plans + engine | **COMPLETE** (functional) | `plan_file`, `engine_plans.run_plan_iteration` | Refinement / thread guards: see plan_file docs |
| Step `tools` hard gate + governance | **COMPLETE** (file plans) | `tool_allowlist_context` + `plan_step_governance` | Retries / blocked steps; `test_plan_step_governance.py` |
| Project memory JSON v2 | **COMPLETE** (feature) | `project_memory.py`, `scan_repo` | Bounded injection; operator `.gitignore` |
| Relationship codex | **SCAFFOLD** | `relationship_codex.py` | Not default prompt injection |
| API contract | **PARTIAL** | OpenAPI via FastAPI | **Appendix A** lists routes; schema at `/openapi.json` |
| UI integration | **PARTIAL** | `/ui`, `agent/ui` | e2e optional per AGENTS |

---

## 4. Gap and Stub Detection (Mandatory)

**`NotImplementedError` (agent tree):** Only [`agent/layla/geometry/backends/base.py`](../agent/layla/geometry/backends/base.py) (abstract backend methods — expected).

**TODO/FIXME:** Many hits in `knowledge/` and `find_todos` tool strings; **not** dense actionable markers in `agent_loop.py` / `registry.py` from sampled grep.

**Structural stub / unwired API:** [`core/loop.py`](../agent/core/loop.py) — `run_loop()` only attaches `_snapshot` and returns; **`agent_loop.autonomous_run()` does not call `run_loop()`** (verified: no imports of `core.loop` in agent tree). The live path calls `core.observer.build_snapshot` directly inside `agent_loop.py`. **Impact: medium** (dead hook + past misleading docs; module docstring corrected to match).

**“Looks implemented but incomplete”:** Six-phase pipeline narrative vs `run_loop` body — **high honesty impact** for new engineers (docstring corrected in this pass to match behavior).

**Duplication:** `_normalize_mcp_tool_args` in agent_loop vs registry — **UNVERIFIED depth**; **refactor hotspot (medium)**.

**Dead branches:** Not systematically enumerated — **UNVERIFIED**.

---

## 5. Parity vs Claimed Capabilities

| Source | Alignment |
|--------|-----------|
| [README.md](../README.md) | **local-first, tool-heavy, approval-gated agent platform** — matches code |
| [AGENTS.md](../AGENTS.md) | **186 tools** — matches `EXPECTED_TOOL_COUNT` |
| [PARITY_AUDIT.md](PARITY_AUDIT.md) | Background cancel: thread + subprocess — consistent |
| [CCUNPACKED_ALIGNMENT.md](CCUNPACKED_ALIGNMENT.md) | **PARTIAL** for agents/teams — honest |

**Stale tool counts in `knowledge/`:** Scan for literal `109` in `knowledge/**/*.md` (2026-04-03): **no matches**. Re-scan for `179` when bumping `EXPECTED_TOOL_COUNT`; sample product docs should track **186** (same as `test_registered_tools_count.py`).

**Parity honesty score:** **0.82 / 1.0**

---

## 6. Concurrency and Execution Model

- **Threads:** Background default; `llm_serialize_lock` in autonomous_run — **UNVERIFIED: all contention points**.
- **Subprocess:** Isolated PID; stdout/stderr caps; cgroup cleanup best-effort (see RUNBOOKS/PRODUCTION_CONTRACT).
- **Cancellation:** Thread = cooperative (`Event`); subprocess = **hard** signals. Stream path: `client_abort_event` (PARITY); **UNVERIFIED:** every tool respects abort promptly.
- **Resource contention:** `resource_manager.schedule_slot` — **UNVERIFIED under stress**.

---

## 7. Safety and Isolation Analysis

- **Sandbox:** `inside_sandbox` prefix checks — weak vs symlink edge cases (**UNVERIFIED**), operator `sandbox_root`, URL/shell tools.
- **Subprocess:** Separate address space; **N×** local GGUF if misconfigured.
- **Cgroup / Job / RLIMIT:** Asymmetric Windows vs Linux; delegation required on Linux.
- **Residual risk:** Runaway native code in-process, mmap RAM, MCP subprocess argv, weak approvals + `allow_run`.

---

## 8. Code Quality and Maintainability

- **Hotspots:** `agent_loop.py`, `registry.py`.
- **MCP client:** ~430 lines (approximate); integration spreads into loop.
- **Coupling:** Router ↔ loop ↔ registry ↔ `runtime_safety` ↔ db — monolith coupling.
- **Fragile areas:** Decision JSON parsing, tool dispatch growth, approval persistence.

---

## 9. Test Coverage Reality Check

- **CI:** `pytest tests/ -m "not slow and not e2e_ui" --timeout=60 --cov` (`.github/workflows/ci.yml`).
- **Skipped / conditional:** `slow`, `e2e_ui`; platform skips; MCP tests if fixture missing.
- **Not typically tested:** Real GGUF, GPU, browser e2e without deps, real cgroup delegation.
- **Windows:** Dedicated CI job reduces Linux-only blind spot.

---

## 10. Confidence Scores (0–1)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Architecture correctness | **0.78** | Entrypoints + loop + routers verified; not all services read |
| Feature completeness | **0.72** | PARITY + symbols; optional features sampled |
| Code reliability | **0.70** | Tests exist; monolith risk |
| Safety / security | **0.55** | Gates; no threat model / adversarial suite |
| Documentation accuracy | **0.80** | Core aligned; knowledge may drift |
| Test coverage realism | **0.68** | CI excludes slow/e2e; stub model |
| Production readiness | **0.62** | Sovereign single-operator; not multi-tenant SaaS |
| **Overall understanding** | **0.70** | Strong skeleton; exhaustive proof absent |

---

## 11. Final Truth Statement

**Full understanding?** **No.** High-confidence **skeleton** (HTTP → `autonomous_run` → tools → memory/approvals → background modes) with **documented uncertainty** on: every service module, every tool edge case, full concurrency model.

**Still uncertain:** Full decision schema; exhaustive `pass`/dead-branch scan; symlink sandbox; MCP failure modes. **Excluded from “Layla uncertainty”:** model quality (backend), multi-tenant load (infra), cgroup/RLIMIT edge cases (documented best-effort — see scope boundaries above).

**Toward high confidence in the application layer:** Route/OpenAPI diff to docs; tool hazard matrix; adversarial sandbox tests; coverage triage on `agent_loop`/`registry`; threat model doc; decision-parser fuzzing. **“Near 100%” is not a meaningful target** for backend LM behavior, production load envelopes, or all OS enforcement corner cases — those are explicitly out of band above.

---

## Appendix A — FastAPI route inventory (generated)

**How to regenerate:** From repo root, `cd agent` then:

```bash
python -c "import sys; sys.path.insert(0,'.'); from main import app
for r in sorted(app.routes, key=lambda x: getattr(x,'path','')):
    p=getattr(r,'path',None)
    m=getattr(r,'methods',None)
    if m: 
        for x in sorted(m-{'HEAD'}): print(x, p)
    elif p: print('MOUNT', p)"
```

**Canonical machine-readable schema:** `GET /openapi.json` (when server is running).

**Snapshot (method + path), count = 110 lines below:**

| Method | Path |
|--------|------|
| GET | / |
| POST | /agent |
| POST | /agent/background |
| POST | /agent/steer |
| GET | /agent/tasks |
| DELETE | /agent/tasks/{task_id} |
| GET | /agent/tasks/{task_id} |
| POST | /agent/tasks/{task_id}/cancel |
| POST | /agents/spawn |
| POST | /approve |
| GET | /aspects/{aspect_id}/title |
| POST | /aspects/{aspect_id}/title |
| GET | /audit |
| GET | /capabilities |
| POST | /compact |
| GET | /conversations |
| POST | /conversations |
| GET | /conversations/search |
| DELETE | /conversations/{conversation_id} |
| GET | /conversations/{conversation_id} |
| GET | /conversations/{conversation_id}/messages |
| POST | /conversations/{conversation_id}/rename |
| GET | /ctx_viz |
| POST | /deny |
| GET | /docs |
| GET | /docs/oauth2-redirect |
| GET | /doctor |
| POST | /execute_plan |
| GET | /file_content |
| GET | /file_intent |
| GET | /health |
| GET | /health/deps |
| GET | /history |
| POST | /knowledge/ingest |
| GET | /knowledge/ingest/sources |
| POST | /learn/ |
| GET | /learnings |
| DELETE | /learnings/{learning_id} |
| GET | /local_access_info |
| GET | /manifest.json |
| GET | /memories |
| GET | /memory/export |
| POST | /memory/import |
| GET | /memory/stats |
| POST | /mission |
| GET | /mission/{mission_id} |
| GET | /missions |
| GET | /openapi.json |
| GET | /pending |
| GET | /platform/knowledge |
| GET | /platform/models |
| GET | /platform/plugins |
| GET | /platform/projects |
| GET | /project_context |
| POST | /project_context |
| GET | /project_discovery |
| GET | /projects |
| POST | /projects |
| DELETE | /projects/{project_id} |
| GET | /projects/{project_id} |
| PATCH | /projects/{project_id} |
| GET | /redoc |
| POST | /refresh_lens_knowledge |
| POST | /research |
| GET | /research_brain/file |
| POST | /research_mission |
| GET | /research_mission/debug |
| GET | /research_mission/state |
| GET | /research_mission/verify |
| GET | /research_output/last |
| POST | /resume |
| POST | /schedule |
| GET | /session/export |
| GET | /session/grants |
| POST | /session/grants/clear |
| GET | /session/stats |
| GET | /settings |
| POST | /settings |
| POST | /settings/preset |
| GET | /settings/schema |
| GET | /setup/download |
| GET | /setup/models |
| GET | /setup_status |
| GET | /skills |
| GET | /study_plans |
| POST | /study_plans |
| POST | /study_plans/derive_topic |
| GET | /study_plans/presets |
| POST | /study_plans/record_progress |
| GET | /study_plans/suggestions |
| DELETE | /study_plans/{plan_id} |
| GET | /system_export |
| GET | /ui |
| POST | /undo |
| POST | /update/apply |
| GET | /update/check |
| GET | /usage |
| POST | /v1/chat/completions |
| GET | /v1/models |
| GET | /values.md |
| GET | /version |
| POST | /voice/speak |
| POST | /voice/transcribe |
| GET | /wakeup |
| GET | /workspace/cognition |
| POST | /workspace/cognition/sync |
| POST | /workspace/index |

*Note: `MOUNT` routes for `/docs` and `/layla-ui` appear as additional route entries in introspection; the table above lists explicit method/path pairs from the regeneration script output.*

---

## Appendix B — Maintenance

- **Regenerate route appendix** when adding/removing FastAPI routes.
- **Re-run knowledge stale scan:** `rg '\\b109\\b' knowledge --glob '*.md'` (legacy tool count); also `rg '\\b179\\b'` after bumps to `EXPECTED_TOOL_COUNT` (currently **186**).

---

## Related documents

- [`PARITY_AUDIT.md`](PARITY_AUDIT.md), [`CCUNPACKED_ALIGNMENT.md`](CCUNPACKED_ALIGNMENT.md), [`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md), [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`AGENTS.md`](../AGENTS.md)

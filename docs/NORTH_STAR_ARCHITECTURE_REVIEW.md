# North Star §8, §10, §14, §18 — Architecture Review

Review of current implementation for architectural soundness and future scalability. Covers separation of concerns, coupling, state ownership, edge-case risks, and a minimal §16 Remote outline.

---

## 1. Architecture Sanity Check

### Separation of concerns

| Concern | Location | Assessment |
|--------|----------|------------|
| **Wakeup initiative** | `routers/study.py`: `_wakeup_initiative_suggestion()` + wakeup handler | Isolated in study router; single entry (wakeup); no write side effects. |
| **Failure classification** | `agent_loop.py`: `_classify_failure_and_recovery()`, `_run_verification_after_tool()` | Pure classification + state mutation; called only from verification path. |
| **Project discovery** | `services/project_discovery.py`: `run_project_discovery()` | Standalone service; single LLM call; returns structured dict only. |
| **LLM decision layer** | `agent_loop.py`: `_llm_decision()` | Consumes `state` (including structured `recovery_hint`); stringifies via `_format_recovery_hint_for_prompt`; does not own failure semantics. |
| **LLM access** | `services/llm_gateway.py` | Single `run_completion` / `get_stop_sequences`; used by agent_loop and project_discovery. |

**✔ Structurally sound**

- Initiative is **read-only** (project context + study plans) and **config-gated** (`wakeup_include_initiative`). No shared mutable state between wakeup and agent loop.
- Failure classification is **scoped to one run**: state is per-`autonomous_run()`; `last_failure_type` / `recovery_hint` are derived from `consecutive_no_progress` and `last_tool_used` and cleared when progress is made.
- Project discovery is **stateless and read-only**: it uses `get_project_context()` and `get_recent_learnings()`; no writes, no approval flow.
- LLM decision **consumes** recovery hints as prompt text; it does not define failure types or verification rules. Recovery logic stays in one place (`_classify_failure_and_recovery`).

---

### Hidden coupling risks

| Risk | Current state | Verdict |
|------|----------------|--------|
| **Runtime config vs behavior** | Initiative: `runtime_safety.load_config().get("wakeup_include_initiative", False)`. Failure/discovery do not depend on config for core logic. | **✔** Config is opt-in for initiative; defaults are safe. |
| **Study plans vs project context** | Initiative uses both: `get_project_context()` and `active_plans` (from `get_active_study_plans()`). Same DB layer; no circular dependency. | **✔** Both are read at wakeup time; order is fixed (plans then initiative). |
| **Recovery hint injection into decision loop** | `_llm_decision()` appends `no_progress_hint` (including §8 hint) to the prompt. State keys `last_failure_type` and `recovery_hint` are set only in `_run_verification_after_tool` → `_classify_failure_and_recovery`. | **⚠** Hint is additive; if more hint sources are added later, `no_progress_hint` could become long and dilute the signal. |

**⚠ What may create future rigidity**

- **Recovery hint aggregation**: All no-progress signals are still concatenated; §8 hint is now structured and stringified at prompt assembly. A cap on total hint length remains optional.
- **Initiative**: Now data-driven via `INITIATIVE_RULES` and `_initiative_condition_matches`; first match wins; rule order is explicit.
- **Project discovery ↔ LLM**: Discovery and agent_loop both use `services.llm_gateway.run_completion`; no dependency on agent_loop for completion.

**🔧 Done**

1. **Recovery hint**: Structured form `{type, message, source}`; stringify at prompt assembly (`_format_recovery_hint_for_prompt`). Optional: cap total `no_progress_hint` length.
2. **Initiative**: Data-driven `INITIATIVE_RULES` + `_initiative_condition_matches`; test for rule ordering.
3. **Discovery**: Timeout guard (ThreadPoolExecutor + timeout), safe fallback, max item length; LLM via `llm_gateway`.
4. **§8**: Documented; classification runs after verified tool step with no progress.

---

### State ownership

| State | Owner | Scoped to | Stateless? |
|------|--------|-----------|------------|
| **Failure state** (`recovery_hint` dict, `consecutive_no_progress`, `last_tool_used`) | `agent_loop.autonomous_run()` state dict | Single run | Yes — state is created at run start; `recovery_hint` is structured and cleared when progress is made. |
| **Initiative suggestion** | Computed inside wakeup handler from DB reads | Request | Yes — no stored suggestion; recomputed each wakeup. |
| **Project discovery** | Return value of `run_project_discovery()` | Request | Yes — no side effects; output is not stored by the service. |

**✔ Failure state** is correctly scoped to the run: initialized in the state dict, updated only in `_run_verification_after_tool` and `_classify_failure_and_recovery`, and used only in `_llm_decision` for that run.

**✔ Initiative** is stateless: no cache, no DB column for “last suggestion”; every wakeup recalculates from current project context and plans.

**✔ Project discovery** is read-only and does not mutate project context, learnings, or any shared state; it only calls read APIs and the shared completion path.

---

## 2. Edge Case Risk Scan

| Risk | Impact | Mitigation (minimal, config-first) |
|------|--------|-----------------------------------|
| **Initiative spam / repetition** | Same suggestion every wakeup (e.g. “You have active study plans”) until context changes; user may perceive as nagging. | **Config**: Add `wakeup_initiative_max_frequency_hours` (e.g. 24): only append suggestion if last_wakeup is older than that. Optional: store `last_initiative_shown` in DB and skip if same text within window. |
| **Suggestion mismatch with user intent** | Rule-based suggestion (e.g. “Set a lifecycle stage”) when user is already in execution; feels off. | **Logic**: Prefer “no suggestion” when stage is `execution` or `reflection` (user is already in flow). Keep initiative for early-stage (idea, planning) and for pending study plans. |
| **Discovery returning low-signal ideas** | LLM returns generic or empty lists; UI or downstream consumers get little value. | **API**: Return structure always; add optional `discovery_quality` or `confidence` from a second small prompt or heuristic (e.g. “fewer than 2 ideas → low”). Client can hide or collapse low-signal. **Config**: `project_discovery_min_ideas_to_show` (default 0) to avoid surfacing empty discovery. |
| **Recovery hint looping / oversteering** | Model over-indexes on “Assist recovery: …” and keeps replying (reason) or reframing instead of trying one more tool. | **Logic**: Already mitigated by strategy_shift_count and “consider replying (reason)” (suggestion, not mandate). **Low-cost**: After 3+ consecutive no-progress, optionally *shorten* or *drop* the detailed recovery hint to reduce repetition. |
| **Wakeup text drift into pseudo-agency** | Greeting starts to sound like “I will do X” instead of “I can help with X when you want.” | **Process**: Keep initiative messages in a fixed list or config (e.g. “I can help … when you’re ready”) and avoid LLM-generated initiative text in wakeup. Current implementation is rule-based and safe. |
| **JSON fragility in project discovery** | Model returns invalid JSON or extra text; `run_project_discovery()` returns empty lists. | **Current**: Regex extract `{...}`, `_ensure_list()`, try/except with fallback to `{"opportunities": [], "ideas": [], "feasibility_notes": []}`. **Optional**: Retry once with “Output only valid JSON” or a smaller max_tokens; log parse failures for tuning. |

---

## 3. §16 Remote — Implemented

Minimal, safe first version: **text-first, no new autonomy, execution opt-in, reusing existing recovery and initiative concepts.** Implemented in `main.py` (middleware), `runtime_safety` (config), and `tests/test_remote.py`.

### Core responsibilities

- **Remote** = “invoke existing Layla endpoints from a non-local client (another machine or a scheduled job),” with auth and a single well-defined entrypoint.
- **No new autonomy**: No background agents; no new execution triggers. Remote call is always initiated by a user or a user-configured trigger (e.g. cron).
- **Same completion pathway**: All LLM calls still go through `_completion` (local or existing `llama_server_url`); no separate “remote model” path in v1.
- **Text-first**: Remote can trigger wakeup (greeting + initiative), project discovery (read-only), and **chat/agent** with the same semantics as local: tool runs only if allowed; write/run still require approval.

### Data flow

1. **Client** (remote) → **HTTPS** → **Layla server** (user’s machine or trusted host).
2. **Auth**: One optional **API key** or **bearer token** in config; validated on a single middleware or per-route. No auth = reject (when remote is enabled).
3. **Allowed endpoints** (v1): `GET /wakeup`, `GET /project_discovery`, `POST /v1/chat/completions` (or existing `/agent` if it’s the main entry). No approval bypass; no new “remote-only” actions.
4. **Response**: Same JSON as local; no extra “remote” fields in v1.

### New components (minimal)

| Component | Responsibility |
|----------|----------------|
| **Config** | `remote_enabled: bool` (default False), `remote_api_key: str` (optional), `remote_allow_endpoints: list` (e.g. `["/wakeup", "/project_discovery", "/agent"]`). |
| **Middleware or dependency** | If `remote_enabled` and request is not from localhost, require `Authorization: Bearer <remote_api_key>`; else 401. Skip check when request is `127.0.0.1` / `localhost`. |
| **No new services** | Reuse existing routers and `autonomous_run()`; no queue, no worker process. |

### Config gates

- `remote_enabled`: must be True for any remote access.
- `remote_api_key`: if set, all non-local requests must send this token.
- `remote_allow_endpoints`: list of path prefixes allowed when called remotely (e.g. block `/approve` or internal routes in v1).

### Failure handling model

- **Network/auth failure**: Client gets 401/403; no state change on server.
- **Timeout**: Use existing request timeouts; no special remote timeout in v1.
- **Agent run (e.g. /agent)**: Same as local: approval_required, reason, tool results. Recovery hints and initiative already live in the same flow; no change.
- **Discovery/wakeup**: Same as local: return JSON or greeting; on error return empty or error payload. No retries or background jobs.

### Suggested first API surface

- **No new routes.** Expose existing routes behind:
  - **Binding**: Listen on `0.0.0.0:8000` only when `remote_enabled` is True (otherwise keep `127.0.0.1`).
  - **Auth**: `Authorization: Bearer <remote_api_key>` for any request whose source IP is not localhost.
- **Optional health for remote**: `GET /health` returns 200 when server and (if desired) DB are ok; can be used by remote clients to check reachability. No secrets in response.

### Constraints satisfied

- **Additive**: Only config + auth middleware + optional bind address; no refactor of agent_loop or study router.
- **No background agents**: Remote is request/response only.
- **Same completion pathway**: No new LLM adapter; `llama_server_url` remains the only remote-model hook.
- **Thin and testable**: Tests can set `remote_enabled=True`, send `Authorization` header, and assert 200 vs 401 for allowed vs disallowed endpoints; mock or real `autonomous_run` unchanged.

---

## Summary

- **§8, §10, §14, §18** are structurally sound: clear ownership, read-only where intended, config-gated initiative, and recovery hint only injected into the decision prompt.
- **Risks** are mostly about repetition (initiative), low-signal discovery, and hint length; mitigations are config or small logic changes.
- **§16 Remote** can be a thin layer: enable remote bind + API key auth + allowlist of endpoints, reusing existing behavior and the same completion and recovery semantics.

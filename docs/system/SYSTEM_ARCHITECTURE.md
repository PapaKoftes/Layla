# System architecture (as implemented)

Sources: [`agent/main.py`](../../agent/main.py), [`agent/routers/agent.py`](../../agent/routers/agent.py), [`agent/services/coordinator.py`](../../agent/services/coordinator.py), [`agent/routers/autonomous.py`](../../agent/routers/autonomous.py), [`agent/agent_loop.py`](../../agent/agent_loop.py), [`agent/autonomous/controller.py`](../../agent/autonomous/controller.py).

## FastAPI application

- **`app = FastAPI(lifespan=lifespan)`** in [`main.py`](../../agent/main.py). Routers are **`app.include_router(...)`** with **no global prefix** for most routers; exceptions use `APIRouter(prefix=...)` inside router modules.
- **Static**: `docs/` mounted at `/docs` when present; UI assets at `/layla-ui`; root **`GET /`**, **`GET /ui`** serve [`agent/ui/index.html`](../../agent/ui/index.html).

## Two different symbols named “autonomous” (do not conflate)

| Symbol | Location | Purpose |
|--------|----------|---------|
| **`agent_loop.autonomous_run`** | [`agent/agent_loop.py`](../../agent/agent_loop.py) | Main **execution loop** for chat/agent work: LLM decisions, tools, streaming, approvals path. Invoked from HTTP via coordinator. |
| **`run_autonomous_task`** | [`agent/autonomous/controller.py`](../../agent/autonomous/controller.py) | **Tier-0 investigation** loop for **`POST /autonomous/run`**: read-only tool allowlist, value gate, prefetch chain, optional wiki export. **Not** the same as `agent_loop.autonomous_run`. |

No rename was performed; this document clarifies naming only.

## POST /agent (high level)

1. [`routers/agent.py`](../../agent/routers/agent.py) **`POST /agent`** parses JSON (`message`, `workspace_root`, `allow_write`, `allow_run`, `stream`, `conversation_id`, etc.).
2. **`_dispatch_autonomous_run`** calls **`services.coordinator.run(agent_loop.autonomous_run, goal, **kwargs)`** ([`agent/routers/agent.py`](../../agent/routers/agent.py)).
3. **`coordinator.run`** ([`services/coordinator.py`](../../agent/services/coordinator.py)) may merge resume state, build **`coordinator_trace`**, optional worktree isolation, then **`dispatch_autonomous_run`** → **`agent_loop.autonomous_run`**.

## POST /autonomous/run (high level)

1. [`routers/autonomous.py`](../../agent/routers/autonomous.py) **`POST /autonomous/run`**: requires **`autonomous_mode`** in config, **`confirm_autonomous: true`** in body, **`goal`**; builds **`AutonomousTask`** with **`allow_network=False`** (fixed in router).
2. Calls **`autonomous.controller.run_autonomous_task`**.

## Shared wiring

- [`main.py`](../../agent/main.py) **`set_refs`** wires history, pending read/write, audit, append_history, study callback into **`shared_state`**.

## Middleware (when enabled)

- **`remote_auth_middleware`**: if **`remote_enabled`**, non-localhost requires **`Authorization: Bearer <remote_api_key>`** and path allowlist ([`main.py`](../../agent/main.py)).
- **`remote_rate_limit_middleware`**: per-IP cap when remote enabled.
- **`trace_id_middleware`**: optional **`X-Trace-Id`** when **`trace_id_enabled`**.

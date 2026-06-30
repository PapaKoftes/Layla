---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Coding Conventions

**Analysis Date:** 2026-06-29

Layla is a Python 3.11/3.12 local-first FastAPI agent platform. The runtime
lives under `agent/` (routers, services, the `layla` package, tools,
capabilities). `fabrication_assist/` is a sibling top-level package. Conventions
below are prescriptive — match them when adding code.

## Naming Patterns

**Files / modules:**
- `snake_case.py` for all modules (`agent_loop.py`, `route_helpers.py`, `secret_filter.py`).
- Routers live in `agent/routers/<feature>.py`, one `APIRouter` per file.
- Services live in `agent/services/<feature>.py` (business logic, no FastAPI imports where avoidable).
- Tests are `agent/tests/test_<subject>.py` (see TESTING.md).

**Functions:**
- `snake_case` for all functions and methods.
- Module-private helpers are `_`-prefixed (`_redact_secrets`, `_is_localhost`, `_build_tools_from_domains`). Treat `_`-prefixed names as not-for-import.
- `async def` for route handlers and anything awaiting I/O; no special prefix — async-ness is conveyed by `await`/`asyncio.to_thread` at call sites. CPU/blocking work inside an async route is wrapped: `await asyncio.to_thread(sync_fn)` (e.g. `routers/session.py::compact_conversation`).

**Variables / constants:**
- `snake_case` for locals.
- `UPPER_SNAKE_CASE` module-level constants, centralized in `agent/constants.py` (`MAX_SAFE_READ_BYTES`, `DEFAULT_MAX_TOOL_CALLS`, `LOCALHOST_HOSTS`). Import from `constants` rather than redefining — see the anti-pattern note below.
- Type-annotate constants: `MAX_MESSAGE_LENGTH: int = 100_000`. Use `_` digit separators for large numbers.

**Types / schemas:**
- `PascalCase` for Pydantic models and dataclasses (`CapabilityImpl`). Pydantic request/response schemas live in `agent/schemas/` and `agent/config_schema.py` / `decision_schema.py`.
- `@dataclass` for plain data holders with `field(default_factory=...)` for mutable defaults (`capabilities/registry.py`).
- Constant tuples/frozensets for closed value sets: `VALID_REASONING_MODES: tuple[str, ...]`, `LOCALHOST_HOSTS: frozenset[str]`.

## Code Style

**Formatting & linting:**
- `ruff` is the single tool (config in `pyproject.toml` `[tool.ruff]`). `line-length = 120`, `target-version = "py311"`, `src = ["agent", "fabrication_assist"]`.
- Lint selection: `E, F, W, I` (pycodestyle, pyflakes, warnings, import-sort). Deliberately ignored globally: `E501` (length — formatter's job), `F401` (intentional re-exports), `E741` (math-heavy single letters), `E402` (intentional non-top-level imports in startup paths).
- Per-file ignores: `agent/tests/*` ignores `F811` (fixture name reuse); fabrication tests ignore `E402` (sys.path bootstrap).
- Run: `python -m ruff check agent fabrication_assist` (the `lint` CI job).

**`from __future__ import annotations`:**
- Required at the top of every module — present in 187/203 service files. Add it to all new modules. It makes annotations lazy strings, which is what lets the codebase annotate with types whose modules aren't imported at top level.

## Import Organization

The codebase runs a **deliberate two-tier import convention** (this is why `E402` is globally ignored):

1. **Top-level imports** — stdlib, then third-party, then first-party — for anything needed at module import time and cheap to load. Standard ruff `I` ordering applies.
2. **In-function / lazy imports** — heavy or optional dependencies are imported *inside* the function that needs them, NOT at module top. Examples: `routers/session.py::ctx_viz` imports `runtime_safety`, `services.context_budget`, `services.context_manager` locally; `routers/ws.py` imports `from services.auth import _is_localhost` inside the handler; `_is_localhost` imports `constants.LOCALHOST_HOSTS` inside the function with an `ImportError` fallback.

Reasons this is intentional, not laziness:
- Keeps app startup fast and lets the `dev` extra import app modules without the GPU/model stack installed (heavy imports never fire until used).
- Breaks import cycles between routers ↔ services ↔ `layla.*`.
- Makes optional features degrade gracefully (a missing `chromadb`/`playwright` only errors when that path runs).

When adding code: import lazily for anything in the `llm`/`voice`/`vision`/`research` optional groups, anything heavy (`torch`, `chromadb`, `sentence_transformers`, `llama_cpp`), or anything that would create a cycle. Import at top for stdlib, FastAPI, pydantic, and sibling helpers.

**First-party absolute imports** are used throughout because `agent/` is on `sys.path` (`conftest.py`, and `[tool.setuptools.packages.find]` exposes `routers`, `services`, `capabilities`, `skills`, `layla`): `from services.route_helpers import ...`, `from layla.time_utils import utcnow`, `from constants import ...`. No relative `from .x` style.

## Error Handling

Two complementary patterns:

**1. Result dicts (`{"ok": bool, ...}`)** — service/tool functions that can fail in expected ways return a dict, never raise across the boundary (~93 occurrences across services/routers). Shape:
```python
return {"ok": False, "error": "not_a_git_repo"}        # machine-readable error code
return {"ok": False, "reason": "...", "message": "..."} # safety refusals add reason/message
return {"ok": True, ...}                                # success, extra keys as needed
```
The `error`/`reason` value is a short snake_case code, not a sentence; human text goes in `message`. Catch-all tail: `except Exception as e: return {"ok": False, "error": str(e)}` (`services/admin_checkpoint.py`).

**2. try/except-degrade** — optional subsystems are wrapped so a failure downgrades rather than crashes:
```python
try:
    import runtime_safety as _rs
    _rs._config_cache = None
except Exception:
    pass
```
Used for optional-dependency imports, cache resets, and best-effort side effects. Pair a narrow `ImportError` with a hard-coded fallback when an optional module supplies constants (`auth._is_localhost`).

Raise real exceptions only for programmer errors / invariant violations and at hard trust boundaries (e.g. Pydantic validation rejecting oversized input via `constants.MAX_MESSAGE_LENGTH`).

## Logging

- One logger per module: `logger = logging.getLogger("layla")` — a single named tree, configured centrally. Do not use bare `print` in runtime code.
- Log at service boundaries and on degraded/except paths; keep utility functions quiet.

## Trust / security checks

Trust decisions go through `agent/services/auth.py`, never ad-hoc host checks:
- `is_direct_local(headers, socket_host)` — the correct "trust the local caller" gate. It returns True only for a DIRECT loopback request; tunnelled requests that merely appear to come from `127.0.0.1` (cloudflared/ngrok) are treated as remote.
- `real_client_ip(headers, socket_host) -> (ip, via_proxy)` — resolves the real peer, honoring forwarding headers only when the socket actually arrived on loopback.
- Loopback membership is `constants.LOCALHOST_HOSTS` (note `0.0.0.0` is deliberately excluded as a bind sentinel).
Recent history (commits `b6bb9aa`, `44cc3b0`) hardened this exact boundary — do not reintroduce bare `host == "127.0.0.1"` checks.

## Patterns to match when adding...

**...a router** (`agent/routers/<feature>.py`):
```python
from __future__ import annotations
from fastapi import APIRouter
router = APIRouter(tags=["<feature>"])

@router.post("/<path>")
async def <handler>():
    ...                      # heavy imports go INSIDE the handler
```
Then register it in `agent/main.py` with `app.include_router(<feature>.router)` (~line 550+).

**...a tool**: add the callable to the appropriate domain module under `agent/layla/tools/impl/<domain>.py`, expose it via the domain's `*_TOOLS` dict, which `layla/tools/registry.py::_build_tools_from_domains` merges into `TOOLS`. Return a `{"ok": ...}` result dict and respect the sandbox (`inside_sandbox`, `shell_command_is_safe_whitelisted` from `sandbox_core`).

**...a config flag**: add it as a typed field to the Pydantic schema in `agent/config_schema.py` with a default there; read it via `runtime_safety.load_config()` (cached). Do NOT hard-code a literal default at the read site (see anti-pattern below). Defaults that are real magic numbers belong in `agent/constants.py`.

**...a trust check**: call `services.auth.is_direct_local(...)` — never inline a host comparison.

**...a test**: `agent/tests/test_<subject>.py`, pure-stdlib where possible, mock `services.llm_gateway.run_completion`. See TESTING.md.

## Anti-patterns present (avoid / clean up)

- **God-file:** `agent/agent_loop.py` is 4,119 lines and concentrates the highest-bug-density logic. Its core decision/gate logic was extracted to `decision_schema.py` and `services/output_quality.py` precisely so it could be tested (see `test_agent_core_logic.py`). Prefer extracting new logic into a service rather than growing `agent_loop.py`.
- **Inlined-default drift:** config defaults appear both in the schema and as `cfg.get("key", <literal>)` literals at call sites (e.g. `int(cfg.get("n_ctx", 4096))`). The two drift apart. Read defaults from the schema/`constants`, not re-typed literals.
- **`window.*` browser globals:** the frontend (`agent/ui/js/*.js`) stores app state on mutable `window.*` globals (`window.currentAspect`, `window.currentConversationId`, `window.__laylaHealth`) with `||` fallbacks. This is implicit global state with load-order coupling; a CI guard (`scripts/check_ui_symbols.py`) checks UI onclick/onchange symbols but does not fix the global-state pattern.

---

*Convention analysis: 2026-06-29*

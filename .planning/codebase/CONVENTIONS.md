# Coding Conventions

**Analysis Date:** 2026-06-30

Layla is a Python 3.11/3.12 codebase (v1.4.0 "Castilla"). The agent lives under
`agent/`; a secondary package `fabrication_assist/` sits at the repo root. All
linting and type targets assume **Python 3.11** semantics.

## Naming Patterns

**Files:**
- `snake_case.py` for all modules: `llm_gateway.py`, `system_head_builder.py`, `maturity_engine.py`.
- Test files: `test_<subject>.py` under `agent/tests/` (required by `python_files = ["test_*.py"]` in `pyproject.toml`).

**Functions:**
- `snake_case`: `real_client_ip()`, `_evict_models_if_needed()`, `run_completion()`.
- Leading underscore for module-private helpers: `_free_llm_instance()`, `_get_llm()`.

**Variables:**
- `snake_case` locals; module-level singletons/caches prefixed `_`: `_llm`, `_llm_by_path`, `_llm_lock`, `_config_cache`.
- Constants in `UPPER_SNAKE`: `REPO_ROOT`, `_DEFAULT_MAX_RESIDENT_MODELS`, `COPYLEFT`, `KNOWN_ROOT_FILES`.

**Types:**
- Modern PEP 585 / 604 builtins: `list[int]`, `dict[str, Any]`, `str | None`. Enabled by `from __future__ import annotations` at the top of most modules.

## Code Style

**Formatting:**
- Tool: **ruff** (`pyproject.toml [tool.ruff]`).
- `line-length = 120`, `target-version = "py311"`, `src = ["agent", "fabrication_assist"]`.
- Line length is *not* enforced as an error (`E501` ignored) — treated as a formatter concern, not a hard gate.

**Linting:**
- Rule sets selected: `E` (pycodestyle errors), `F` (pyflakes), `W` (warnings), `I` (isort import ordering).
- Global ignores (`[tool.ruff.lint] ignore`):
  - `E501` line too long (handled by formatter)
  - `F401` imported-but-unused (intentional re-exports / barrel modules)
  - `E741` ambiguous variable name (math-heavy code)
  - `E402` module-level import not at top (intentional non-top-level imports in startup paths)
- Per-file ignores (`[tool.ruff.lint.per-file-ignores]`):
  - `agent/tests/*` → `F811` (fixture-name redefinition is normal in pytest)
  - `agent/tests/test_fabrication_assist*.py` → `E402` (sys.path bootstrap before repo imports)
- CI invocation (`.github/workflows/ci.yml`, `lint` job): `python -m ruff check agent fabrication_assist`.

## Import Organization

Enforced by ruff's `I` (isort) rules. Standard order:
1. `from __future__ import annotations` (first line after the docstring)
2. Standard library (`asyncio`, `logging`, `os`, `pathlib`, `typing`)
3. Third-party (`pytest`, `fastapi`, `pydantic`)
4. First-party (`services.*`, `layla.*`, `routers.*`, `shared_state`)

**Module resolution:**
- The agent runs with cwd = `agent/`, so top-level packages (`services`, `routers`, `layla`, `capabilities`, `skills`) are importable as roots. See `[tool.setuptools.packages.find]` in `pyproject.toml`.
- Tests that run on a bare interpreter prepend `AGENT_DIR` to `sys.path` themselves (e.g. `agent/tests/test_trust_boundary.py`, `agent/tests/test_architecture_boundaries.py`) so they work without an editable install.

## Backward-Compat Shim Pattern (IMPORTANT)

When a module is reorganized into a sub-package, the old flat path is preserved as
a **shim** so existing imports keep working. This is the dominant structural
convention in `agent/services/`.

Canonical shim form (`agent/services/llm_gateway.py`):

```python
"""Backward compatibility -- module moved to services/llm/llm_gateway.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.llm_gateway")
_sys.modules[__name__] = _real
```

Rules enforced by `agent/tests/test_architecture_boundaries.py`:
- **Every** flat `services/*.py` (other than `__init__.py`) MUST be a shim — detected by `sys.modules[__name__]` reassignment or a `"Backward compatibility" ... import *` docstring (`test_all_flat_services_are_shims`).
- A shim and its canonical module must resolve to the **same** module object (`test_shim_resolves_to_canonical`, e.g. `services.llm_gateway is services.llm.llm_gateway`).
- New logic goes in a sub-package (`services/llm/`, `services/safety/`, `services/personality/`, …), never as a new flat file.

When you move a module: create the real implementation under the right
sub-package, then leave (or add) a shim at the old path. Do not delete the old path.

## Architecture / Layering Conventions

`agent/tests/test_architecture_boundaries.py` codifies these as executable rules:
- **Routers** (`agent/routers/`) must not import `layla.memory.db.get_connection` directly — go through the service layer (`test_routers_dont_import_db_directly`).
- Non-infrastructure code should route DB access through `services/memory_router.py` rather than importing `layla.memory.db*` directly (ratcheted bypass budget, currently ≤85; memory-infra prefixes like `layla/memory/`, `layla/codex/`, `scripts/` are exempt).
- `shared_state` importers are budgeted (≤15) and meant to migrate to `services.session_context` / dependency injection.
- New root-level `agent/*.py` files are discouraged: only the allowlist in `KNOWN_ROOT_FILES` (entrypoints, config, and explicitly-listed legacy shims) is permitted; others raise a warning today (soft gate, intended to harden later).
- `agent_loop.py` size is budgeted (≤1000 lines) and must keep exporting its public names (`autonomous_run`, `stream_reason`, `classify_intent`, `TOOLS`, …) for backward compat (`test_agent_loop_backward_compat_attrs`).
- Required service sub-packages must each contain real modules + an `__init__.py`: `services/agent`, `observability`, `retrieval`, `planning`, `skills`, `tools`, `context`, `personality`, plus `cluster`, `governance`, `infrastructure`, `llm`, `memory`, `prompts`, `reasoning`, `safety`, `sandbox`, `user`, `workspace`.

## Error Handling

- Best-effort cleanup paths use broad `except Exception: pass` deliberately (resource release, optional imports, cache resets) — see `_free_llm_instance`, conftest fixtures. This is an accepted pattern for non-critical side effects, not for control flow.
- Optional dependencies are guarded with `try/import/except ImportError` and degrade gracefully (e.g. `llama_cpp`, `playwright`, `chromadb` falling back to the SQLite+NumPy vector store).
- Security-critical primitives raise/return explicitly and are covered by dedicated stdlib-only tests (see TESTING.md trust-boundary suite).

## Logging

- Single named logger per process: `logger = logging.getLogger("layla")`.
- `%`-style lazy formatting in log calls: `logger.info("... %d ...", n)` — never f-strings inside log calls.

## Comments & Docstrings

- Module docstrings explain the module's role and any non-obvious constraints (e.g. "Serializes all completion calls via asyncio queue").
- Inline comments frequently cite requirement/phase IDs (`REQ-02`, `REQ-72`, `F9`, `Phase 12`) tying code to planning artifacts. Preserve these references when editing.
- Functions carry short docstrings describing intent, invariants, and who holds locks.

## Module Design

- Heavy use of module-level singletons protected by locks (`_llm_lock = threading.RLock()`), with explicit reset hooks for tests (see `_reset_volatile_module_state` in conftest).
- `ContextVar` used for request-scoped state instead of globals where applicable.
- Barrel re-exports are intentional and exempt from `F401`.
- Per-aspect config theming: personality/behavior is parameterized per "aspect" rather than hard-coded; see `agent/services/personality/` (`aspect_behavior.py`, `style_profile.py`, `frame_modifier.py`).

## License Hygiene (REQ-02)

- The project ships under a proprietary "Free for non-commercial use" license, incompatible with strong copyleft.
- `scripts/check_copyleft.py` (run in CI) scans installed distribution metadata via stdlib `importlib.metadata` and fails if any AGPL/GPL/SSPL dependency is present without an escape hatch (dual-license, linking exception, LGPL/MPL-only, or an `ALLOW` justification). Do not add strong-copyleft dependencies.

---

*Convention analysis: 2026-06-30*

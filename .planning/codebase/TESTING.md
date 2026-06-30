# Testing Patterns

**Analysis Date:** 2026-06-30

The suite lives under `agent/tests/` (~234 test files, ~2143 passing on master).
Tests are designed to run **without the GPU/model stack** — a deliberate, central
constraint that drives most of the conftest machinery below.

## Test Framework

**Runner:**
- pytest `>=8.0`, configured in `pyproject.toml [tool.pytest.ini_options]`.
- `testpaths = ["agent/tests"]`, `python_files = ["test_*.py"]`, `python_functions = ["test_*"]`.
- `addopts = "-v --tb=short"`.

**Plugins / async:**
- `pytest-asyncio` (`asyncio_mode = "auto"` — `async def test_*` run without explicit decorators).
- `pytest-timeout` (CI passes `--timeout=60` / `120`).
- `pytest-cov` for coverage; `hypothesis` available for property tests.

**Warning filters:** DeprecationWarning / PendingDeprecationWarning / PytestConfigWarning are ignored.

## Running the Suite

Setup uses a dedicated, GPU-free virtualenv `.venv-test` populated from the `dev`
extra (see `docs/DEV_TESTING.md`). The `dev` extra is a deliberately minimal,
no-GPU, no-model dependency set.

```powershell
# Windows one-command setup (finds a 3.11/3.12 interpreter via the py launcher)
powershell -ExecutionPolicy Bypass -File scripts\setup_test_env.ps1
.\.venv-test\Scripts\Activate.ps1
cd agent
pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"
```

```bash
# Other platforms
python3.12 -m venv .venv-test
.venv-test/bin/pip install -e ".[dev]"
cd agent && pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"
```

**Canonical CI run** (set `CI=1` to get the canonical collection exclusions — see conftest):

```bash
cd agent
CI=1 pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint" --timeout=60
```

**Dependency-free subset** (pure stdlib — runs on ANY Python incl. 3.14, no extras):

```bash
cd agent
python -m pytest tests/test_port_guard.py tests/test_url_guard.py \
  tests/test_sandbox_core.py tests/test_extract_archive_safety.py \
  tests/test_council_models.py tests/test_user_identity.py -q
```

## conftest.py — Critical Patterns

`agent/tests/conftest.py` carries the machinery that keeps the suite green on any
machine. Understand these before adding tests:

**1. `collect_ignore` (collection-time skips):**
- `_TESTCLIENT_FILES` — files needing `TestClient` + full app lifespan (hang in CI: no model/scheduler/DB). Ignored **only when `CI` env var is set**; they run locally with a full environment.
- `_LLAMA_CPP_FILES` — files that reach `llm_gateway → llama_cpp`, which SIGILLs on CI runners (pre-compiled wheel uses AVX-512/VNNI). Ignored **unless `LAYLA_TEST_REAL_LLM` is set**, so even a dev box with real llama-cpp won't hang loading a model on every loop test.

**2. `_block_llama_cpp_on_ci` (autouse, session scope):**
- Safety net that replaces `llama_cpp.Llama` with a stub raising `RuntimeError` unless `LAYLA_TEST_REAL_LLM` is set. Prevents the suite from ever loading a native model (SIGILL on CI; retry-sleep hang elsewhere). Tests that explicitly mock `run_completion`/`llama_cpp.Llama` override this for their scope.

**3. `_force_test_db_path` (autouse, session scope):**
- Points `LAYLA_DATA_DIR` at a tmp dir and patches `layla.memory.db._DB_PATH` so tests never touch the operator's real `layla.db`. Resets `_MIGRATED` flags so migrations re-run against the throwaway DB.

**4. `_reset_volatile_module_state` (autouse, function scope):**
- Clears module-level caches that leak between tests: `runtime_safety._config_cache` (stale TTL'd config) and `layla.memory.learnings._recent_learning_ts` (in-process rate-limiter deque that otherwise trips and makes `save_learning()` silently return -1).

**5. `pytest_collection_modifyitems`:** auto-skips `e2e_ui`-marked tests when playwright isn't importable.

**Implication for new tests:** if your code path calls the LLM, mock
`services.llm_gateway.run_completion` (use the `mock_llm` fixture) — do not rely
on a real model. If it ImportErrors on a missing package, add that package to the
`dev` extra in `pyproject.toml`.

## Markers

Declared in `pyproject.toml`: `slow`, `e2e_ui`. Additional markers filtered in CI:
`browser_smoke`, `voice_smoke`, `gpu_smoke`, `endpoint`. The canonical marker
filter is `not slow and not e2e_ui and not browser_smoke and not voice_smoke and
not gpu_smoke` (plus `not endpoint` in the CI coverage run).

## Test File Organization

- Flat layout under `agent/tests/`, one `test_<subject>.py` per concern.
- Playwright UI tests isolated under `agent/tests/e2e_ui/` (`test_ui_smoke.py`, its own `conftest.py`), marked `e2e_ui`.
- No co-location with source; all tests centralized in `agent/tests/`.

## Shared Fixtures (conftest.py)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `mock_llm` | function | Patches `services.llm_gateway.run_completion` with a `MagicMock` returning a canned completion |
| `mock_config` | function | Minimal runtime config dict (tool/runtime caps, flags off) |
| `isolated_db` | function | Function-scoped SQLite DB; patches `_DB_PATH` on `db` + `db_connection`, runs `migrate()` |
| `no_network` | function | Patches `socket.socket` to raise `OSError` — blocks all outbound network |

## Mocking

- `unittest.mock` (`MagicMock`, `patch`) is the standard tool.
- Mock at the **service boundary**, primarily `services.llm_gateway.run_completion`, never the native `llama_cpp` layer in normal tests (the autouse stub already blocks it).
- Lightweight hand-written stubs for protocol surfaces (e.g. `_Headers` case-insensitive header stub in `test_trust_boundary.py`) rather than full framework objects.

## Architecture-Boundary Test Suite

`agent/tests/test_architecture_boundaries.py` is a cheap (no network/DB,
AST + filesystem only) guard that enforces structural rules and prevents
regressions:
- Critical services import without circular deps (`services.llm_gateway`, `services.context_manager`, `shared_state`, …).
- Routers don't import `layla.memory.db.get_connection` directly.
- Root `agent/*.py` files stay within `KNOWN_ROOT_FILES`; new logic goes in sub-packages.
- `shared_state` importer count ≤15; `memory_router` bypass count ≤85 (ratchets).
- Flat `services/*.py` are **all** backward-compat shims, and each shim resolves to the same module object as its canonical path.
- Dead-code files stay deleted; required sub-packages exist; `agent_loop.py` ≤1000 lines and keeps its public attrs.

This suite is the executable contract for the conventions in CONVENTIONS.md — run
it after any restructuring.

## Security Tests (Trust Boundary)

Pure-stdlib, runnable on any Python (incl. 3.14):
- `agent/tests/test_trust_boundary.py` — `services.auth.is_direct_local()` / `real_client_ip()`. Regression guard for the CRITICAL finding that a tunnel (cloudflared/ngrok) forwarding internet traffic from 127.0.0.1 bypassed auth. Verifies forwarded requests (`Cf-Connecting-Ip`, `X-Forwarded-For`, `X-Real-Ip`, `Forwarded`, `True-Client-Ip`) are treated as NON-local and the rightmost-trusted-hop client IP is extracted (REQ-10/11).
- `agent/tests/test_tunnel_auth.py` — companion tunnel-auth coverage.
- Other stdlib security primitives: `test_port_guard.py`, `test_url_guard.py` (SSRF), `test_sandbox_core.py`, `test_extract_archive_safety.py`.

## Coverage

- Config: `agent/.coveragerc` (used when pytest runs with cwd=`agent/`). `branch = True`, `source = .`, omits `tests/*`, `e2e_ui/*`, `tui.py`.
- Floor: `fail_under = 28` (branch coverage; ratcheted upward over time). Linux CI enforces the floor; Windows CI runs without it.

```bash
cd agent
pytest tests/ -m "<canonical filter>" --cov=. --cov-config=.coveragerc --cov-report=term-missing:skip-covered
```

## CI Workflow (`.github/workflows/ci.yml`)

Jobs:
- **test** — matrix Python 3.11 + 3.12 on ubuntu; writes a stub `runtime_config.json` (`ci-stub.gguf`, `use_chroma=false`), runs the canonical marker-filtered suite with the coverage floor.
- **test-windows** — Python 3.12 on windows-latest; same suite, no coverage floor, `--timeout=120`.
- **e2e-ui** — installs `requirements-e2e.txt` + `playwright install chromium`, runs `tests/e2e_ui/` with `-m e2e_ui`.
- **lint** — `python -m ruff check agent fabrication_assist`.
- License-compliance step (`python scripts/check_copyleft.py`) and UI-symbol check (`scripts/check_ui_symbols.py`) run inside the test jobs. A targeted daily-driver smoke (`tests/test_edit_loop_tools.py`) runs before the full suite.

## Test Types

- **Unit:** dominant — service functions + pure primitives with mocked LLM/DB.
- **Architecture/contract:** `test_architecture_boundaries.py` (structural invariants).
- **Security:** trust-boundary / sandbox / SSRF primitives (stdlib-only).
- **Integration / HTTP:** `TestClient`-based (skipped in CI via `collect_ignore`, run locally).
- **E2E UI:** Playwright under `tests/e2e_ui/`, marker-gated.
- **Inference smoke (opt-in):** set `LAYLA_TEST_REAL_LLM` to exercise a real local model.

## Benchmark Harness

Not part of pytest — a separate quality-tracking tool:
- `scripts/benchmark_coding.py` — HumanEval/MBPP-style **pass@1** coding benchmark for the local model. Prompts the model, extracts the function, runs canonical tests in a sandboxed subprocess with a timeout, emits a JSON + markdown scorecard (model, quant, tok/s, per-problem). `--self-test` scores a known-good solver with no model (REQ-74, Phase 12).
- `benchmarks/` — committed scorecards (e.g. `scorecard_qwen2.5-coder-7b.json`) + `README.md`.

```bash
python scripts/benchmark_coding.py --model models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
python scripts/benchmark_coding.py --self-test
```

---

*Testing analysis: 2026-06-30*

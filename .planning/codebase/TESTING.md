---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Testing Patterns

**Analysis Date:** 2026-06-29

## Test Framework

**Runner:**
- `pytest >= 8.0`, configured in two places: `pyproject.toml` `[tool.pytest.ini_options]` (canonical, `testpaths = ["agent/tests"]`, `asyncio_mode = "auto"`, `addopts = "-v --tb=short"`) and `agent/pytest.ini` (marker docs + `timeout = 120`).
- Plugins: `pytest-asyncio >= 0.23` (auto mode — no `@pytest.mark.asyncio` needed), `pytest-timeout >= 2.3`, `pytest-cov >= 5.0`. `hypothesis >= 6.0` is declared in the `dev` extra but is **not currently exercised** by any test (only referenced as a runtime import in `services/cognitive_workspace.py`); property-based tests are an available-but-unused capability.

**Assertion library:**
- Plain `assert` (pytest rewriting). Mocking via `unittest.mock` (`MagicMock`, `patch`, `monkeypatch`).

**Run commands:**
```bash
# Full fast suite (what CI runs), from agent/:
cd agent
pytest tests/ -v --tb=short \
  -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint" \
  --timeout=60

# dev extra (no GPU/model build) — see docs/DEV_TESTING.md:
python3.12 -m venv .venv-test && .venv-test/bin/pip install -e ".[dev]"
cd agent && pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"

# Pure-stdlib subset — runs on ANY Python (incl. 3.13/3.14), no third-party deps:
cd agent
python -m pytest tests/test_port_guard.py tests/test_url_guard.py \
  tests/test_sandbox_core.py tests/test_extract_archive_safety.py \
  tests/test_council_models.py tests/test_user_identity.py -q

# Single file:
pytest tests/test_agent_core_logic.py -q
```
`scripts/setup_test_env.ps1` is a one-command Windows bootstrap (finds a 3.11/3.12 interpreter via the `py` launcher, builds `.venv-test`, installs `dev`).

## Test File Organization

**Layout** — separate `agent/tests/` tree (~202 `test_*.py` files), not co-located with source:
```
agent/
  conftest.py                 # adds agent/ to sys.path; stubs setup.python_compat
  tests/
    conftest.py               # CI collect_ignore + autouse isolation fixtures
    test_<subject>.py         # bulk of the suite (one subject per file)
    fixtures/                 # shared helpers (e.g. fake_mcp_stdio.py)
    integration/              # multi-module flows (conftest.py + test_full_pipeline.py, ...)
    integration_smoke/        # marked smoke: gpu_smoke / voice_smoke / browser_smoke
    e2e_ui/                   # Playwright tests, marker e2e_ui (test_ui_smoke.py)
```

**Naming / markers** (`pyproject.toml` + `agent/pytest.ini`):
- `slow` — needs a live LLM model. `endpoint` — spins up FastAPI `TestClient` / real HTTP.
- `e2e_ui` — Playwright vs live uvicorn (needs `requirements-e2e.txt` + `playwright install chromium`).
- `browser_smoke`, `voice_smoke`, `gpu_smoke` — heavy smokes, all deselected in PR CI.

## Isolation Fixtures (the safety layer)

`agent/tests/conftest.py` defines autouse fixtures that make the suite hermetic:
- `_force_test_db_path` (session, autouse) — sets `LAYLA_DATA_DIR` to a tmp dir and repoints `layla.memory.db._DB_PATH` so tests **never touch the operator's real `layla.db`**.
- `_reset_volatile_module_state` (function, autouse) — clears module-level caches that leak between tests (`runtime_safety._config_cache`, `learnings._recent_learning_ts` rate-limiter deque).
- `_block_llama_cpp_on_ci` (session, autouse) — on CI, replaces `llama_cpp.Llama` with a stub that raises, so the AVX-512 prebuilt wheel can't SIGILL (exit 132) the whole session.
- `agent/conftest.py::_relax_python_compat_for_tests` — patches `setup.python_compat.check_python_compatibility` to a "supported" stub (override with the `real_python_compat` marker).

Opt-in fixtures: `mock_llm` (patches `services.llm_gateway.run_completion`), `mock_config` (minimal runtime config dict), `isolated_db` (function-scoped migrated SQLite via `patch("layla.memory.db._DB_PATH", ...)`), `no_network` (raises on `socket.socket`).

## Test Structure

Flat `test_*` functions (not `describe`/class-based). Pure-stdlib targets import the unit directly and assert on its contract:
```python
from decision_schema import parse_decision            # noqa: E402
from services.output_quality import passes_completion_gate

TOOLS = frozenset({"read_file", "write_file", "shell", "grep_code"})

def test_unknown_tool_is_nulled():
    d = parse_decision('{"action":"tool","tool":"definitely_not_a_tool"}', TOOLS)
    assert d is not None and d["tool"] is None   # unknown tool dropped, not executed
```
`asyncio_mode = "auto"` means `async def test_*` runs without a marker. Files that import app modules add the `agent/` sys.path bootstrap at top (hence `# noqa: E402`).

## Mocking

- `unittest.mock.patch` against the import path, targeting **app behavior over the full stack**: mock `services.llm_gateway.run_completion` so no real inference runs; patch `layla.memory.db._DB_PATH` for DB isolation; the `no_network` fixture monkeypatches `socket.socket`.
- **What to mock:** the LLM gateway, the DB path, the network socket, `setup.python_compat`, and `llama_cpp.Llama` (CI). **What NOT to mock:** the pure decision/gate/sandbox/guard logic — those are tested directly with real inputs.

## What IS vs IS NOT covered

**Covered (deliberately, because pure-stdlib & high-bug-density):**
- Security primitives: SSRF/url guard, port guard, sandbox containment, archive-extraction safety (`test_url_guard.py`, `test_port_guard.py`, `test_sandbox_core.py`, `test_extract_archive_safety.py`) — the documented stdlib subset.
- Agent core decision logic: `parse_decision` JSON extraction (brace-balancing, fence stripping, trailing-comma repair, unknown-tool nulling) and the completion gate (`test_agent_core_logic.py` — added in commit `dc0b9c0` precisely because `agent_loop.py` is collect-ignored).
- Council/model routing, user identity, config migration, tool dispatch, edit-loop tools (the CI "daily-driver smoke" runs `test_edit_loop_tools.py`).

**NOT covered (known gaps — do not assume green CI means these work):**
- **Real inference never runs in CI.** CI writes a stub `model_filename: "ci-stub.gguf"` runtime config, and `_block_llama_cpp_on_ci` hard-blocks `llama_cpp.Llama` (prebuilt wheel SIGILLs on GitHub VMs). No test loads a real GGUF or generates real tokens in PR CI.
- **The agent loop's end-to-end path is `collect_ignore`d on CI.** `_LLAMA_CPP_FILES` (`test_agent_loop.py`, `test_completion.py`, `test_engineering_pipeline.py`, ...) reach `autonomous_run() → llm_gateway → llama_cpp` and are skipped via `collect_ignore` when `CI` is set. Only the extracted pure pieces run.
- **`TestClient`/HTTP routes are collect-ignored on CI** (`_TESTCLIENT_FILES`: `test_health_endpoint.py`, `test_pairing.py`, `test_e2e_agent.py`, `test_plans_api.py`, ...) — the app lifespan hangs without model/scheduler/DB. There are effectively **no `/v1` OpenAI-compat contract tests** running in CI.
- **No quality / grounding / hallucination eval.** Coverage is behavioral and structural; there is no LLM-judge, golden-answer, or grounding-accuracy harness gating merges.
- GPU / voice / browser smokes (`integration_smoke/`, `e2e_ui/`) are deselected in PR CI and gated behind extra installs / env vars (`LAYLA_GPU_SMOKE`).

## Coverage

- Linux CI enforces a coverage floor: `--cov=. --cov-config=.coveragerc --cov-report=term-missing:skip-covered` (`agent/.coveragerc`). Windows CI runs tests **without** a coverage floor.
- Coverage reflects the fast subset only — heavy/ignored modules (`agent_loop.py` full path, HTTP routes, inference) are not exercised, so the number understates real risk in those areas.

## CI Workflows (`.github/workflows/`)

- **`ci.yml`** — jobs: `test` (ubuntu, Python 3.11 + 3.12 matrix; installs `agent/requirements.txt`, editable install, `scripts/check_ui_symbols.py`, daily-driver smoke, writes stub runtime config, runs fast suite with coverage floor); `test-windows` (windows-latest, 3.12, no coverage floor, longer 120s timeout); `e2e-ui` (Playwright Chromium, `-m e2e_ui`); `lint` (`ruff check agent fabrication_assist`).
- **`release.yml`**, **`verify-deep.yml`** — release and deeper verification pipelines.
- The fast suite marker filter on every PR: `not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint`, `--timeout=60` (Linux) / `--timeout=120` (Windows).

## Common Patterns

**Async** — no decorator (auto mode):
```python
async def test_compacts():
    result = await compact_conversation()
    assert result["ok"]
```
**Error / refusal** — assert on the result dict, not on a raised exception:
```python
out = some_service(bad_input)
assert out["ok"] is False and out["error"] == "expected_code"
```
**Stdlib-only contract test** — import the unit, feed crafted strings, assert exact behavior (`test_agent_core_logic.py`). Prefer this shape; it runs everywhere and survives the heavy-stack gates.

Snapshot testing: not used.

---

*Testing analysis: 2026-06-29*

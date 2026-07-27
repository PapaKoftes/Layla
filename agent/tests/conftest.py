"""Shared pytest hooks and fixtures for the Layla test suite."""
from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# R6: TestClient-based tests trigger the FastAPI lifespan, whose heavy subsystems
# (embedder preload, scheduler, knowledge indexing, cluster) used to hang when no
# model/scheduler/DB is present — so they were CI-skipped. We now run them
# everywhere by switching the app to minimal startup (see main.py lifespan), which
# mounts the routes but skips the blocking subsystems. Must be set before the app
# module is imported by any test.
os.environ.setdefault("LAYLA_MINIMAL_STARTUP", "1")

# ---------------------------------------------------------------------------------------------
# OPERATOR-STATE ISOLATION. Set at conftest IMPORT time, not in a fixture body.
#
# `_force_test_db_path` (below) also sets LAYLA_DATA_DIR, but a session-scoped fixture body does not
# run until the first test is SET UP — i.e. after every test module has been imported. Anything a test
# module does at import/collection time therefore ran against the operator's real data dir.
#
# That window is not hypothetical. Traced with `tests/_write_tracer.py` over a full `--collect-only`
# with this block removed, collection reaches the operator's real repo-root `layla.db`:
#
#     sqlite3.connect  C:\Work\Programming\Layla\layla.db
#         via layla/memory/db_connection.py:44 in _make_connection
#
# and `_make_connection` immediately runs `PRAGMA journal_mode=WAL` — a write that materialises
# -wal/-shm beside the operator's 3.6 MB database. A census that does not wrap `sqlite3.connect`
# reports this window as empty, because SQLite opens its file through its own C layer and never
# touches `io.open`/`os.open`.
#
# ORDERING IS LOAD-BEARING. `runtime_safety.CONFIG_FILE` is resolved at *its* import (runtime_safety
# .py:60) and honours LAYLA_DATA_DIR, so setting the variable before that import silently moves the
# whole suite off `agent/runtime_config.json` and onto a non-existent file — load_config() then
# returns DEFAULTS (max_tool_calls 20 instead of 8, use_chroma True instead of False), quietly
# changing what every gate MEANS. So: import runtime_safety FIRST, binding CONFIG_FILE to the real
# config while LAYLA_DATA_DIR is still unset, and only then redirect the data dir.
import runtime_safety as _runtime_safety  # noqa: E402  (imported for its import-time binding)

_REAL_CONFIG_FILE = _runtime_safety.CONFIG_FILE

# `setdefault`, not assignment — an outer harness (the release CI job, a bisect script) that has
# already pointed LAYLA_DATA_DIR somewhere deliberate keeps its choice.
_ISOLATED_DATA_DIR = Path(tempfile.mkdtemp(prefix="layla-test-data-"))
os.environ.setdefault("LAYLA_DATA_DIR", str(_ISOLATED_DATA_DIR))
os.environ.pop("LAYLA_DB_PATH", None)

# Fail loudly rather than silently running the entire suite against default config.
assert _runtime_safety.CONFIG_FILE == _REAL_CONFIG_FILE, (
    "LAYLA_DATA_DIR redirection moved runtime_safety.CONFIG_FILE "
    f"({_REAL_CONFIG_FILE} -> {_runtime_safety.CONFIG_FILE}); the suite would read default config."
)

# ---------------------------------------------------------------------------
# TestClient-based tests that require a working app lifespan (kept for reference;
# they now run via LAYLA_MINIMAL_STARTUP rather than being collection-skipped).
# ---------------------------------------------------------------------------
_TESTCLIENT_FILES = [
    "test_remote.py",
    "test_tool_tracing.py",
    "test_meilisearch_bridge.py",
    "test_character_creator.py",
    "test_pairing.py",
    "test_request_tracer.py",
    "test_startup_imports.py",
    "test_german_mode.py",
    "test_health_endpoint.py",
    "test_e2e_agent.py",
    "test_golden_flow_http.py",
    "test_smoke_comprehensive.py",
    "test_install.py",
    "test_autonomous_v2.py",
    "test_runtime_validation_plan.py",
    "test_agents_spawn.py",
    "test_background_task_cancel.py",
    "test_codex_router.py",
    "test_plans_api.py",
    "test_platform_ui.py",
    "test_workspace_cognition_http.py",
    "test_session_export.py",
    "test_projects_api.py",
    "test_approval_flow.py",
    "test_study_integration.py",
    "test_mission_api.py",
]

# Tests that call autonomous_run() directly → eventually reach llm_gateway →
# llama_cpp which SIGILL on CI runners (pre-compiled llama-cpp-python uses
# AVX-512/VNNI instructions unsupported by GitHub Actions VMs).
# SIGILL is process-fatal so even one bad test kills the entire pytest session.
_LLAMA_CPP_FILES = [
    "test_agent_loop.py",
    "test_agent_loop_batch_tools.py",
    "test_completion.py",
    "test_engineering_pipeline.py",
    "test_goal_preservation.py",
    "test_in_loop_plan_governance.py",
    "test_plan_step_tool_allowlist.py",
    "test_project_memory.py",
    "test_structured_retry.py",
    "test_reasoning_classifier.py",
]

# Opt-in to exercise a REAL local model (the inference-smoke job sets this). Without
# it, real-Llama tests are skipped and Llama is stubbed — so the suite is green on ANY
# machine, including a dev box with real llama-cpp installed (which would otherwise hang
# loading a real model on every loop test). See .planning/phases/12-*/CONTEXT.md.
_REAL_LLM = bool(os.environ.get("LAYLA_TEST_REAL_LLM"))

collect_ignore: list[str] = []
# R6: _TESTCLIENT_FILES are no longer collection-skipped on CI — LAYLA_MINIMAL_STARTUP
# (set above) makes their TestClient lifespan non-blocking, so they run everywhere.
# Default-skip the real-Llama loop tests unless explicitly opted in. (On CI they were
# always skipped; locally with real llama-cpp they'd run a real model and hang.)
if not _REAL_LLM:
    collect_ignore.extend(_LLAMA_CPP_FILES)


@pytest.fixture(autouse=True, scope="session")
def _block_llama_cpp_on_ci():
    """
    Safety net: prevent llama_cpp.Llama from loading a native binary during unit tests.

    Two reasons: (1) on CI the pre-compiled wheel uses AVX-512/VNNI → process-fatal
    SIGILL; (2) on any machine, loading a real model in a unit test is slow and, against
    a stub/missing model, retry-sleeps until the per-test timeout — hanging the suite.

    We replace llama_cpp.Llama with a stub that raises RuntimeError, UNLESS the run opts
    into a real backend via LAYLA_TEST_REAL_LLM (the inference-smoke job). Tests that
    explicitly mock llama_cpp.Llama or run_completion override this for their function.
    """
    if _REAL_LLM:
        yield
        return

    try:
        import llama_cpp

        class _BlockedLlama:
            def __init__(self, *args, **kwargs):
                raise RuntimeError(
                    "llama_cpp.Llama blocked on CI — mock run_completion in your test"
                )

        _orig = llama_cpp.Llama
        llama_cpp.Llama = _BlockedLlama  # type: ignore[misc,assignment]
        yield
        llama_cpp.Llama = _orig  # type: ignore[misc,assignment]
    except ImportError:
        yield


@pytest.fixture(autouse=True, scope="session")
def _force_test_db_path(tmp_path_factory):
    """
    Safety: never let tests touch the operator's real layla.db.

    The DB connection layer resolves the path from:
    - `LAYLA_DATA_DIR` (preferred)
    - or the patched barrel module `layla.memory.db._DB_PATH`
    """
    # Reuse the dir claimed at import time rather than minting a second one. Switching
    # LAYLA_DATA_DIR here would mean the data dir in force during collection differs from the one
    # in force during the run, so anything that cached a resolved path at import would read from a
    # directory nothing else writes to — a silent, order-dependent split-brain.
    data_dir = Path(os.environ.get("LAYLA_DATA_DIR") or tmp_path_factory.mktemp("layla_data"))
    os.environ["LAYLA_DATA_DIR"] = str(data_dir)
    os.environ.pop("LAYLA_DB_PATH", None)
    try:
        import layla.memory.db as db_mod
        import layla.memory.migrations as mig

        db_mod._DB_PATH = Path(data_dir) / "layla.db"  # type: ignore[attr-defined]
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False  # type: ignore[attr-defined]
        if hasattr(mig, "_MIGRATED"):
            mig._MIGRATED = False  # type: ignore[attr-defined]
    except Exception:
        # Some tests import selectively; env var is still enough to keep isolation.
        pass


def reset_volatile_module_state():
    """The volatile-state reset the autouse fixture performs, exposed as a callable so a single
    self-contained test can trigger it and verify it (rather than an order-dependent populate→verify
    test PAIR that passes vacuously when run alone — audit round-4 #1)."""
    try:
        import runtime_safety as _rs
        _rs._config_cache = None
        _rs._config_last_check = 0.0
    except Exception:
        pass

    try:
        import layla.memory.learnings as _lm
        _lm._recent_learning_ts.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_volatile_module_state():
    """
    Reset module-level caches that leak between tests.

    Runs before every test function (scope="function", autouse=True).

    Why each reset is needed:
    - runtime_safety._config_cache: load_config() caches the result for
      _CONFIG_CHECK_TTL seconds. A test that calls load_config() without
      patching populates this cache; the next test then reads stale values
      (e.g. a temp-dir sandbox_root left by a previous test's live run).
    - learnings._recent_learning_ts: an in-process deque rate-limiter.
      After ~20 save_learning() calls across the suite the limiter trips and
      save_learning() silently returns -1, causing tests that check DB
      contents or graph-invalidation to fail.
    """
    reset_volatile_module_state()
    yield  # test runs here


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a predictable response."""
    mock = MagicMock()
    mock.return_value = {"choices": [{"message": {"content": "Mock LLM response."}}]}
    with patch("services.llm.llm_gateway.run_completion", mock):
        yield mock


@pytest.fixture
def mock_config():
    """Minimal runtime config dict."""
    return {
        "max_tool_calls": 5,
        "max_runtime_seconds": 60,
        "remote_enabled": False,
        "temperature": 0.2,
        "allow_write": True,
        "allow_run": False,
        "task_budget_enabled": False,
        "scheduler_study_enabled": False,
    }


@pytest.fixture
def isolated_db(tmp_path):
    """Function-scoped isolated SQLite DB for tests that need real DB operations."""
    db_path = tmp_path / "test_layla.db"
    with patch("layla.memory.db._DB_PATH", db_path), \
         patch("layla.memory.db_connection._DB_PATH", db_path):
        import layla.memory.db as db_mod
        import layla.memory.migrations as mig
        from layla.memory.migrations import migrate

        # migrate() runs at most once per process (guarded by _MIGRATED). Any prior
        # DB-touching test flips the guard True, so without resetting it here migrate()
        # short-circuits and this freshly-patched tmp DB is left with ZERO tables.
        # Reset both guards (barrel + module) so the isolated DB is really migrated,
        # matching the session-scoped _force_test_db_path fixture.
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False  # type: ignore[attr-defined]
        if hasattr(mig, "_MIGRATED"):
            mig._MIGRATED = False  # type: ignore[attr-defined]
        migrate()
        try:
            yield db_path
        finally:
            # Reset the migrate() guards on TEARDOWN too — migrate() set them True against the tmp DB,
            # so without this the NEXT test that touches the REAL DB finds _MIGRATED=True, skips its
            # migration, and can hit a half-migrated/empty schema (500 instead of the expected result).
            # This is the isolated_db teardown leak; resetting here makes the DB re-migrate on next use.
            if hasattr(db_mod, "_MIGRATED"):
                db_mod._MIGRATED = False  # type: ignore[attr-defined]
            if hasattr(mig, "_MIGRATED"):
                mig._MIGRATED = False  # type: ignore[attr-defined]


@pytest.fixture
def populated_profile(tmp_path):
    """A REALISTIC operator profile seeded into an isolated temp DB via the repo's own public write APIs.

    ITEM 11. The head-budget tests otherwise run against an EMPTY DB (the session fixture points
    LAYLA_DATA_DIR at a fresh mkdtemp), which is exactly why the protected-prefix budget regression was
    invisible: with no durable_facts and no workspace_context, nothing downstream grew to crowd the
    per-turn directives out of `system_instructions`. This fixture seeds the nine canonical durable
    identity facts (user_profile.DURABLE_FACT_KEYS), a handful of learnings, and real project/world
    context, so get_durable_facts() and world_state.summarize() return substantial text — reproducing
    the pressure a real profile puts on the head budget.

    Fully isolated (its own tmp DB, migration guards reset on setup AND teardown, mirroring isolated_db)
    so it can never leak into the empty-DB variants of the same tests.
    """
    db_path = tmp_path / "populated_layla.db"
    with patch("layla.memory.db._DB_PATH", db_path), \
         patch("layla.memory.db_connection._DB_PATH", db_path):
        import layla.memory.db as db_mod
        import layla.memory.migrations as mig
        from layla.memory.migrations import migrate

        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False  # type: ignore[attr-defined]
        if hasattr(mig, "_MIGRATED"):
            mig._MIGRATED = False  # type: ignore[attr-defined]
        migrate()

        # 1) The nine durable identity facts — authoritative ground truth injected verbatim.
        from layla.memory.user_profile import set_user_identity
        for _k, _v in {
            "name": "Mina",
            "pronouns": "she/her",
            "timezone": "Europe/Berlin",
            "locale": "en-GB",
            "os_platform": "Windows 11 Pro (build 26200)",
            "editor": "VS Code",
            "indent_style": "4 spaces, never tabs",
            "shell": "PowerShell 5.1 and Git Bash",
            "project_roots": "C:/Work/Programming/Layla; C:/Work/Programming/sideproject",
        }.items():
            set_user_identity(_k, _v)

        # 2) A handful of learnings — several relevant to an ordinary coding turn so they surface in memory.
        from layla.memory.learnings import save_learning
        for _c in (
            "The operator prefers concise, direct answers and dislikes filler or flattery.",
            "When fixing a Python bug, run the failing pytest first and read the traceback before editing code.",
            "The Layla codebase keeps the agent app under agent/ and runs its tests from a separate .venv-test.",
            "Prefer replace_in_file or apply_patch over rewriting whole files when editing this repository.",
            "The operator works mostly in Python, with some TypeScript for the browser UI layer.",
            "CI must stay green; the head-budget tests are the canary for prompt-assembly regressions.",
        ):
            save_learning(_c, kind="fact", confidence=0.85, score=1.0)

        # 3) Project + world context so world_state.summarize() returns real text (inflates workspace_context).
        from layla.memory.projects_db import set_project_context
        set_project_context(
            project_name="Layla",
            domains=["ai-agents", "prompt-engineering", "python", "local-inference"],
            key_files=[
                "agent/services/prompts/system_head_builder.py",
                "agent/services/context/context_manager.py",
            ],
            goals="Ship a bounded local AI companion and engineering agent with a hard-reserved protected prompt prefix.",
            lifecycle_stage="execution",
            progress="Head-budget hardening in progress; capability-manifest injection stabilised.",
            blockers="A populated profile regressed the protected per-turn directives out of the prompt.",
            last_discussed="prompt assembly token budgets and the protected prefix",
        )

        try:
            yield db_path
        finally:
            if hasattr(db_mod, "_MIGRATED"):
                db_mod._MIGRATED = False  # type: ignore[attr-defined]
            if hasattr(mig, "_MIGRATED"):
                mig._MIGRATED = False  # type: ignore[attr-defined]


@pytest.fixture
def shipped_defaults_config(tmp_path, monkeypatch):
    """ITEM 32. Neutralise the operator's live ``agent/runtime_config.json`` for one test, so a
    config-asserting test reads the SHIPPED defaults regardless of what the operator toggled locally.

    WHY THIS EXISTS. ``runtime_config.json`` is gitignored operator state (see ``agent/.gitignore``).
    The operator's live file turns on features that ship OFF — ``litellm_enabled``,
    ``meilisearch_enabled``, ``discord_bot_autostart`` — and sets a ``stop_sequences`` override.
    Tests that assert the shipped default therefore FAIL on the operator's box while PASSING in CI,
    which writes its own minimal stub (``.github/workflows/ci.yml`` -> "Write CI runtime config").
    That stub omits every key these tests assert, so in CI they fall through to the shipped default.
    This is the recurring "operator-config artifact" failure.

    WHAT IT DOES. Point ``runtime_safety.CONFIG_FILE`` at an EMPTY tmp stub and reset the TTL config
    cache, so ``load_config()`` returns pure shipped defaults. The only overlays ``load_config``
    applies on top of the static defaults are ``_hardware_derived_defaults()`` and the auto-tune
    profile (``PROFILE_KEYS``); neither touches the feature flags / ``stop_sequences`` under test, so
    an empty stub is deterministic for those keys on any machine. Same mechanism as
    ``test_config_defaults_honesty.py::empty_cfg``, lifted here for reuse across the offender files.

    NOT A MASK. The test still asserts the TRUE shipped default: with an empty stub, ``load_config``
    returns exactly the values ``runtime_safety`` ships, so a real regression in a shipped default
    (e.g. someone flips ``litellm_enabled`` to True in the defaults dict) still fails the test. The
    fixture only removes the operator-file override. The in-setup assertion below proves the
    neutralisation actually took effect — if ``load_config`` were still reading the operator file
    (which ships these ON), it would fail LOUDLY here in setup rather than silently in the test body.
    Passes both locally (operator file present) and under the CI stub (which already omits these keys).
    """
    import runtime_safety as rs

    stub = tmp_path / "runtime_config.json"
    stub.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", stub)
    rs.invalidate_config_cache()

    # Neutralisation proof. Both ship OFF (runtime_safety.load_config defaults); the operator's live
    # file turns both ON. Reading the shipped default here confirms the redirect + cache reset took.
    _cfg = rs.load_config()
    assert _cfg["litellm_enabled"] is False and _cfg["meilisearch_enabled"] is False, (
        "shipped_defaults_config failed to neutralise the operator runtime_config.json — "
        "load_config() still reflects operator overrides, so the test would not assert shipped defaults."
    )
    try:
        yield stub
    finally:
        rs.invalidate_config_cache()  # drop the stub-derived cache; next test re-reads the real file


@pytest.fixture
def no_network():
    """Block all outbound network calls."""
    _orig = socket.socket

    def _blocked(*args, **kwargs):
        raise OSError("Network blocked by no_network fixture")

    with patch.object(socket, "socket", _blocked):
        yield


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    try:
        import playwright  # noqa: F401
    except ImportError:
        skip_e2e = pytest.mark.skip(
            reason="e2e_ui: pip install -r requirements-e2e.txt && python -m playwright install chromium",
        )
        for item in items:
            if "e2e_ui" in item.keywords:
                item.add_marker(skip_e2e)

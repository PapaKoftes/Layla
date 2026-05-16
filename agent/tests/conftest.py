"""Shared pytest hooks and fixtures for the Layla test suite."""
from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# TestClient-based tests that require a working app lifespan.
# In CI the lifespan hangs (no model, no scheduler env, no DB) so we skip
# collection entirely.  Locally they run fine with a full environment.
# ---------------------------------------------------------------------------
# Tests that require TestClient + full app lifespan (hang in CI: no model, no scheduler, no DB)
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
    "test_plan_file_routes.py",
    "test_platform_ui.py",
    "test_workspace_cognition_http.py",
    "test_session_export.py",
    "test_projects_api.py",
    "test_approval_flow.py",
    "test_study_integration.py",
    "test_mission_api.py",
]

# Tests that call autonomous_run → llm_gateway → llama_cpp which SIGILL on CI runners
# (pre-compiled llama-cpp-python uses AVX-512/VNNI unsupported by GitHub Actions VMs)
_LLAMA_CPP_FILES = [
    "test_agent_loop.py",
]

collect_ignore: list[str] = []
if os.environ.get("CI"):
    collect_ignore.extend(_TESTCLIENT_FILES)
    collect_ignore.extend(_LLAMA_CPP_FILES)


@pytest.fixture(autouse=True, scope="session")
def _force_test_db_path(tmp_path_factory):
    """
    Safety: never let tests touch the operator's real layla.db.

    The DB connection layer resolves the path from:
    - `LAYLA_DATA_DIR` (preferred)
    - or the patched barrel module `layla.memory.db._DB_PATH`
    """
    data_dir = tmp_path_factory.mktemp("layla_data")
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

    yield  # test runs here


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a predictable response."""
    mock = MagicMock()
    mock.return_value = {"choices": [{"message": {"content": "Mock LLM response."}}]}
    with patch("services.llm_gateway.run_completion", mock):
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
        from layla.memory.migrations import migrate
        migrate()
        yield db_path


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

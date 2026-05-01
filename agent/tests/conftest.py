"""Shared pytest hooks (skip browser e2e when Playwright is not installed)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


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

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

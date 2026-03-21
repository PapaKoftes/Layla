"""Shared pytest hooks (skip browser e2e when Playwright is not installed)."""
from __future__ import annotations

import pytest


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

"""Playwright smoke: Chromium launches and loads a public page (not localhost; matches browser SSRF policy)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[2]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

pytestmark = pytest.mark.browser_smoke


def test_playwright_chromium_loads_example_com():
    # External-dependency smoke: needs the playwright package, an installed Chromium,
    # AND outbound internet. Skip gracefully when any is absent (matches the e2e_ui
    # philosophy) but still assert correctness when the environment supports it.
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:  # browser binary not installed (`playwright install chromium`)
            pytest.skip(f"Chromium not available: {e}")
        try:
            page = browser.new_page()
            try:
                page.goto("https://example.com", timeout=60000)
            except Exception as e:  # no outbound network in this environment
                pytest.skip(f"network unavailable for browser smoke: {e}")
            title = page.title() or ""
            assert "Example" in title
        finally:
            browser.close()

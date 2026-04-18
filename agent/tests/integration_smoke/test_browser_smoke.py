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
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto("https://example.com", timeout=60000)
            title = page.title() or ""
            assert "Example" in title
        finally:
            browser.close()

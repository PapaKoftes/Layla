"""Browser E2E smoke tests (requires: pip install -r requirements-e2e.txt && playwright install chromium)."""
from __future__ import annotations

import json
import urllib.request

import pytest

try:
    from playwright.sync_api import Page, expect
except ImportError:
    pytest.skip(
        "e2e_ui: pip install -r requirements-e2e.txt && python -m playwright install chromium",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e_ui


def test_health_json(base_url: str) -> None:
    raw = urllib.request.urlopen(base_url + "/health", timeout=15).read()
    data = json.loads(raw)
    assert "status" in data


def test_ui_shell_loads(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    expect(page.locator("#header-system-status")).to_be_visible(timeout=15000)


def test_settings_modal_opens(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    page.get_by_role("button", name="Settings").click()
    expect(page.locator("#settings-overlay.visible")).to_be_visible(timeout=15000)

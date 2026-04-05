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


def test_help_shortcuts_sheet(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    page.locator('#layla-right-panel .rcp-tab[data-rcp="help"]').click()
    page.get_by_role("button", name="Shortcuts sheet").click()
    expect(page.locator("#keyboard-shortcuts-sheet")).to_be_visible(timeout=15000)
    expect(page.get_by_text("Keyboard shortcuts")).to_be_visible(timeout=5000)


def test_send_button_posts_to_agent(page: Page, base_url: str) -> None:
    """Behavioral contract: filling chat and clicking Send issues POST /agent."""
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    with page.expect_request(
        lambda req: req.url.rstrip("/").endswith("/agent") and req.method == "POST",
        timeout=120000,
    ):
        page.locator("#msg-input").fill("e2e ping")
        page.locator("#send-btn").click()

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

# playwright may be importable without the pytest plugin providing the `page` fixture.
try:
    import pytest_playwright  # noqa: F401
except Exception:
    pytest.skip(
        "e2e_ui: pytest-playwright plugin not installed (missing `page` fixture). "
        "Install via requirements-e2e.txt to enable UI tests.",
        allow_module_level=True,
    )

pytestmark = pytest.mark.e2e_ui


def _dismiss_wizard(page: Page) -> None:
    # The onboarding wizard is a modal overlay that blocks clicks until completion.
    # For E2E smoke tests we bypass it to validate baseline UI contracts.
    # Pin a desktop viewport so the responsive shell is deterministic — the live UI
    # is the `.topbar` inside `.main-area`; the legacy `<header>` is display:none
    # ("Preserved IDs for JS compatibility"), so tests must target the visible shell.
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script("localStorage.setItem('layla_wizard_v2_done','1'); localStorage.setItem('layla_wizard_done','1');")


def test_health_json(base_url: str) -> None:
    raw = urllib.request.urlopen(base_url + "/health", timeout=15).read()
    data = json.loads(raw)
    assert "status" in data


def test_ui_shell_loads(page: Page, base_url: str) -> None:
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    # Status pill lives in the live `.topbar` shell (the legacy `<header>` one,
    # #header-system-status, is display:none — preserved for JS only).
    expect(page.locator("#topbar-system-status")).to_be_visible(timeout=15000)


def test_settings_modal_opens(page: Page, base_url: str) -> None:
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    # The visible settings entry point is the topbar ⚙ (openOverlayPanel → prefs);
    # target it specifically to avoid matching the sidebar's "Settings" nav button.
    # (The full-modal openSettings flow lives only on the hidden legacy header.)
    page.locator('.topbar-btn[data-action="openOverlayPanel"][data-arg="prefs"]').click()
    expect(page.locator("#layla-right-panel.rp-open")).to_be_visible(timeout=15000)
    expect(page.locator('#panel-prefs[data-rcp="prefs"]')).to_be_visible(timeout=15000)


def test_command_palette_opens_on_ctrl_k(page: Page, base_url: str) -> None:
    """⌘K/Ctrl+K opens the command palette (previously untested)."""
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    page.keyboard.press("Control+k")
    expect(page.locator("#cmd-palette")).to_be_visible(timeout=15000)
    expect(page.locator("#cmd-palette .cmdp-input")).to_be_focused(timeout=5000)


def test_help_shortcuts_sheet(page: Page, base_url: str) -> None:
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    # Post-overhaul: Help content lives in a modal opened via Ctrl+/.
    page.keyboard.press("Control+/")
    expect(page.locator("#keyboard-shortcuts-sheet")).to_be_visible(timeout=15000)
    expect(page.get_by_text("Help & shortcuts")).to_be_visible(timeout=5000)


def test_send_button_posts_to_agent(page: Page, base_url: str) -> None:
    """Behavioral contract: filling chat and clicking Send issues POST /agent."""
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    with page.expect_request(
        lambda req: req.url.rstrip("/").endswith("/agent") and req.method == "POST",
        timeout=120000,
    ):
        page.locator("#msg-input").fill("e2e ping")
        page.locator("#send-btn").click()


def test_i18n_language_switch_and_rtl(page: Page, base_url: str) -> None:
    """i18n: switching to Spanish translates the chrome; Arabic sets dir=rtl."""
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    # setLanguage returns a promise (loads the catalog); Playwright awaits it.
    page.evaluate("() => window.i18n.setLanguage('es', {persistServer:false})")
    expect(page.locator("#tab-prefs")).to_have_text("Ajustes", timeout=10000)
    page.evaluate("() => window.i18n.setLanguage('ar', {persistServer:false})")
    expect(page.locator("html")).to_have_attribute("dir", "rtl", timeout=10000)
    page.evaluate("() => window.i18n.setLanguage('en', {persistServer:false})")
    expect(page.locator("#tab-prefs")).to_have_text("Settings", timeout=10000)


def test_toast_has_aria_live(page: Page, base_url: str) -> None:
    """a11y: toast notifications carry role/aria-live so screen readers announce them."""
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)
    page.evaluate("async () => { const u = await import('/layla-ui/services/utils.js'); u.showToast('e2e toast'); }")
    toast = page.locator(".toast").first
    expect(toast).to_have_attribute("role", "status", timeout=5000)
    expect(toast).to_have_attribute("aria-live", "polite", timeout=5000)

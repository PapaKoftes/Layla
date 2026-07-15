"""E2E browser guard for the chat rail — the layer a Python contract test can't reach. Creates a
conversation through the running app, gives it a title, reloads the UI, and asserts the JS actually
RENDERS it in the sidebar with that title. If a future edit to conversations.js breaks the list render
(reads the wrong field, drops the title), this fails in a real browser. Complements the API/JS contract
tests (test_conversation_ui_contract.py / test_ui_js_contract.py)."""
from __future__ import annotations

import uuid

import pytest

try:
    from playwright.sync_api import Page, expect
except ImportError:
    pytest.skip("e2e_ui: playwright not installed", allow_module_level=True)

try:
    import pytest_playwright  # noqa: F401
except Exception:
    pytest.skip("e2e_ui: pytest-playwright plugin not installed", allow_module_level=True)

pytestmark = pytest.mark.e2e_ui


def _dismiss_wizard(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script("localStorage.setItem('layla_wizard_v2_done','1'); localStorage.setItem('layla_wizard_done','1');")


def test_created_conversation_renders_in_rail_with_title(page: Page, base_url: str) -> None:
    title = "E2E rail check " + uuid.uuid4().hex[:6]
    _dismiss_wizard(page)
    page.goto(f"{base_url}/ui", wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)

    # Create a conversation + title it through the SAME endpoints the UI uses (no model turn needed).
    cid = page.evaluate(
        """async (title) => {
            const c = await (await fetch('/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({aspect_id:'morrigan'})})).json();
            const id = c.conversation.id;
            await fetch('/conversations/' + encodeURIComponent(id) + '/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({title})});
            return id;
        }""",
        title,
    )
    assert cid, "conversation should be created via the API the UI uses"

    # Reload so the rail re-fetches /conversations and renders through conversations.js.
    page.reload(wait_until="domcontentloaded", timeout=90000)
    expect(page.locator("#msg-input")).to_be_visible(timeout=45000)

    # The rail must show our conversation WITH its title (the exact render the user reports broken).
    item = page.locator(f'.chat-rail-item[data-conv-id="{cid}"], .session-item[data-conv-id="{cid}"]').first
    expect(item).to_be_visible(timeout=20000)
    expect(item).to_contain_text(title, timeout=10000)

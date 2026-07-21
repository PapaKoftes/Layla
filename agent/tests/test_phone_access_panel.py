"""BL-337 / Phase 13 criterion 3: the phone-access feature was a caller and two elements short.

`loadPhoneAccess()` and `copyPhoneUrl()` shipped COMPLETE in settings-full.js — computing the LAN
URL from `location.*` and offering a same-WiFi tip — and were exported to nobody. They reached for
`#phone-access-url` and `#phone-access-status`, which existed in no markup. Three separate layers
each looked finished in isolation; nothing connected them, so the feature had never once run.

That is the signature defect of this codebase, and the reason the element-contract ratchet exists:
`if (el)` converts the failure into silence, so a dead feature looks like a working one.

The ratchet posed the choice — build the panel, or delete the function — and the operator chose
build: phone access is part of the remote pillar (continue work away from the desk), alongside LAN
clustering and multi-device.

These tests assert the WIRING, since the logic was never what was broken.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
INDEX = UI_DIR / "index.html"
MAIN_JS = UI_DIR / "main.js"
SETTINGS_JS = UI_DIR / "components" / "settings-full.js"


@pytest.mark.parametrize("element_id", ["phone-access-url", "phone-access-status"])
def test_the_elements_the_js_reaches_for_actually_exist(element_id):
    html = INDEX.read_text(encoding="utf-8")
    assert f'id="{element_id}"' in html, (
        f"#{element_id} is read by settings-full.js but exists in no markup — `if (el)` makes that "
        "silent, which is exactly how this feature stayed dead"
    )


def test_load_phone_access_has_a_caller():
    """It was `export`ed and imported by nobody: complete code that never ran."""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    calls = [m for m in re.finditer(r"^\s*loadPhoneAccess\(\)", src, re.M)]
    assert calls, (
        "loadPhoneAccess() is defined and exported but never invoked — the panel would render "
        "its placeholder and never populate"
    )


def test_the_caller_is_on_the_path_that_shows_the_panel():
    """Called from openSettings, so opening the panel populates it. Anywhere else is decoration."""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    start = src.index("export async function openSettings")
    body = src[start:start + 1500]
    assert "loadPhoneAccess()" in body, (
        "loadPhoneAccess() is called, but not from openSettings — the URL would be stale or absent "
        "when the user actually looks at the panel"
    )


def test_the_copy_button_is_bound_to_a_real_handler():
    """A data-action with no entry in main.js's table is a button that does nothing."""
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-action="copyPhoneUrl"' in html, "no copy control in the markup"
    main = MAIN_JS.read_text(encoding="utf-8")
    assert re.search(r"copyPhoneUrl\s*:\s*settingsFull\.copyPhoneUrl", main), (
        "the Copy link button declares data-action=\"copyPhoneUrl\" but main.js's action table has "
        "no such entry — clicking it would silently do nothing"
    )


def test_the_ratchet_is_empty_and_must_stay_empty():
    """Criterion 3 is 'every getElementById resolves'. An empty exception list IS the criterion."""
    from tests.test_ui_element_contract import _KNOWN_DEAD

    assert _KNOWN_DEAD == {}, (
        "the known-dead ratchet has entries again: "
        f"{sorted(_KNOWN_DEAD)}. Each one is a feature whose JS reaches for markup that does not "
        "exist. Fix the wiring or delete the feature — do not park it here."
    )

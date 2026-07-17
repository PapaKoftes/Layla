"""BL-335 / BL-352 / BL-366: "Save appearance & lite" must save, and must not claim it did otherwise.

THE BUG. The button toasted "Appearance saved" and saved nothing, at four independent layers:

    const fontSize = (document.getElementById('app-font-size') || {}).value;  // element never existed
    if (fontSize) body.ui_font_size = fontSize;                               // undefined -> skipped
    await fetch('/settings', {body: JSON.stringify({})});                     // empty POST
    showToast(d.ok ? 'Appearance saved' : 'Save failed');                     // -> "Appearance saved"

...and `ui_font_size` is in no schema, so even a populated POST /settings would have been dropped by
runtime_safety and still answered ok:true. The casualty was the TEXT-SIZE ACCESSIBILITY CONTROL.

A fifth layer went unreported until this repair: the four controls that DID exist in the markup
(#ui_avatar_seed, #ui_avatar_style, #chat_lite_mode, #ui_decision_trace_enabled) and the #appearance-save-msg
span were referenced by ZERO javascript — the button never saved them either, and nothing populated them
on open. Six controls, none wired.

THE FIX RESTS ON TWO THINGS THAT ALREADY EXISTED:
  BL-352  GET/POST /settings/appearance — purpose-built for non-schema UI keys, zero callers.
  BL-366  save_config_keys already RETURNED the keys it saved; the router computed the truth and threw
          it away. Reporting {saved, rejected} kills this lie class for every future key.

WHAT THESE TESTS DO NOT COVER — stated plainly rather than implied: I cannot see the rendered UI. These
pin the data path (element exists -> right endpoint -> key accepted -> value stored -> read back) and the
honesty of the response. That the <select> is legible, correctly placed, or that 22px does not overflow
some panel, is NOT verified here and needs a human eye.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

UI = AGENT / "ui"


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """Point config writes at a temp file. NEVER the operator's agent/runtime_config.json."""
    import runtime_safety as rs

    cfg = tmp_path / "runtime_config.json"
    cfg.write_text(json.dumps({"model_filename": "stub.gguf"}), encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", cfg)  # raising=True: renaming CONFIG_FILE must break this
    return cfg


# ── The data path ─────────────────────────────────────────────────────────────────────────────────────

def test_font_size_is_accepted_and_persisted(temp_config):
    """The single assertion the old code could not satisfy: the value reaches disk."""
    from services.infrastructure.route_helpers import sync_save_appearance

    res = sync_save_appearance({"ui_font_size": 20, "ui_animation_level": "reduced"})

    assert res["ok"] is True, res
    assert set(res["saved"]) == {"ui_font_size", "ui_animation_level"}
    assert res["rejected"] == []

    stored = json.loads(temp_config.read_text(encoding="utf-8"))
    assert stored["ui_font_size"] == 20, "the text size must actually be written to the config"
    assert stored["ui_animation_level"] == "reduced"


def test_the_other_four_controls_save_too(temp_config):
    """The unreported fifth layer: these were rendered but read by no JS and saved by nothing."""
    from services.infrastructure.route_helpers import sync_save_appearance

    res = sync_save_appearance({
        "ui_avatar_seed": "abc",
        "ui_avatar_style": "rings",
        "chat_lite_mode": True,
        "ui_decision_trace_enabled": True,
    })
    assert res["ok"] is True and res["rejected"] == []
    stored = json.loads(temp_config.read_text(encoding="utf-8"))
    assert stored["ui_avatar_seed"] == "abc"
    assert stored["chat_lite_mode"] is True


def test_unknown_keys_are_REPORTED_not_swallowed(temp_config):
    """BL-366, the general fix. An unknown key must come back in `rejected` with ok=False.

    The endpoint's allowlist is hand-maintained, which is precisely how a guard misses the thing it was
    built to catch. It survives only because forgetting a key is now LOUD: the caller is told the key was
    dropped instead of being handed a success toast over a no-op.
    """
    from services.infrastructure.route_helpers import sync_save_appearance

    res = sync_save_appearance({"ui_font_size": 18, "totally_made_up_key": "x"})

    assert res["saved"] == ["ui_font_size"]
    assert res["rejected"] == ["totally_made_up_key"]
    assert res["ok"] is False, (
        "ok must be False when a key was dropped. If this returns True, every caller that toasts on "
        "`d.ok` starts lying again — which is the entire defect."
    )
    stored = json.loads(temp_config.read_text(encoding="utf-8"))
    assert "totally_made_up_key" not in stored, "the allowlist must still hold — this is a security boundary"


def test_a_write_of_only_unknown_keys_never_reports_success(temp_config):
    """The exact old failure: an empty/garbage body producing 'Appearance saved'."""
    from services.infrastructure.route_helpers import sync_save_appearance

    res = sync_save_appearance({"app-font-size": "20"})  # the element id, not the config key
    assert res["ok"] is False
    assert res["saved"] == []
    assert res["rejected"] == ["app-font-size"]


def test_get_and_post_use_the_same_key_list():
    """A second hand-copied list in the GET is how a key becomes writable but not readable — it saves,
    then renders blank on reload, which the user reads as 'it didn't save'."""
    from services.infrastructure.route_helpers import APPEARANCE_KEYS

    src = (AGENT / "routers" / "settings.py").read_text(encoding="utf-8")
    assert "from services.infrastructure.route_helpers import APPEARANCE_KEYS" in src, (
        "GET /settings/appearance must derive its keys from APPEARANCE_KEYS, not re-list them"
    )
    assert "ui_font_size" in APPEARANCE_KEYS and "ui_animation_level" in APPEARANCE_KEYS


# ── The wiring the JS depends on ──────────────────────────────────────────────────────────────────────

def test_save_button_targets_the_appearance_endpoint_not_settings():
    """POST /settings silently drops non-schema keys and answers ok:true — pointing back at it restores
    the bug in full while every test here still passes on the backend alone."""
    src = (UI / "components" / "settings-full.js").read_text(encoding="utf-8")
    body = src.split("export async function saveAppearanceLite")[1].split("\nexport ")[0]
    assert "'/settings/appearance'" in body, (
        "saveAppearanceLite must POST to /settings/appearance (BL-352). /settings drops ui_font_size."
    )
    assert re.search(r"fetch\(\s*'/settings'", body) is None, "must not POST to /settings"


def test_toast_is_driven_by_what_the_server_saved():
    """`d.ok ? 'Appearance saved' : ...` is the lie itself. The toast must consult saved/rejected."""
    src = (UI / "components" / "settings-full.js").read_text(encoding="utf-8")
    body = src.split("export async function saveAppearanceLite")[1].split("\nexport ")[0]
    assert "d.saved" in body and "d.rejected" in body, (
        "the toast must report the server's saved/rejected, not assume success from ok"
    )
    assert "d.ok ? 'Appearance saved'" not in body


def test_font_size_is_actually_applied_to_the_document():
    """A stored value that never reaches the DOM is the same no-op with extra steps. layla.css has ~259
    rem-based sizes, so the root font-size is what makes this real."""
    src = (UI / "components" / "settings-full.js").read_text(encoding="utf-8")
    assert "documentElement.style.fontSize" in src, (
        "applyAppearance must scale the root font-size — otherwise the setting is stored and ignored"
    )
    assert "loadAppearance()" in src.split("export function initSettings")[1], (
        "the saved size must be applied at BOOT, not only when Settings is opened"
    )


def test_animation_level_has_css_that_honours_it():
    """data-anim must have rules behind it, or the Animations dropdown is BL-335 all over again."""
    css = (UI / "css" / "layla-rebuild.css").read_text(encoding="utf-8")
    assert '[data-anim="reduced"]' in css and '[data-anim="none"]' in css, (
        "applyAppearance stamps data-anim on <html>; without CSS keyed to it the control does nothing"
    )

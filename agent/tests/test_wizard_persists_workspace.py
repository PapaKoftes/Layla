"""Release blocker: a fresh user's chosen workspace must actually be saved.

The first-run wizard has a workspace field (#wizard-workspace-path). syncWorkspaceToSettings() copied
its value into two hidden inputs and STOPPED — it never POSTed. The only code that persists
sandbox_root (saveSetupWorkspaceIfNeeded, POST /settings) was reachable only from the setup overlay,
which checkSetupStatus() HIDES when a model is already provisioned — i.e. exactly when the install
went smoothly. So a new user typed their project path, clicked Next, and it was discarded:
sandbox_root stayed the empty ~/layla-workspace and every file tool silently returned nothing on day
one. This asserts the wizard now persists it, and that sandbox_root is a setting the backend accepts.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


def test_wizard_sync_actually_persists_the_workspace():
    src = (UI / "components" / "wizard.js").read_text(encoding="utf-8")
    m = re.search(r"function syncWorkspaceToSettings\([^)]*\)\s*\{(.+?)\n\}", src, re.S)
    assert m, "syncWorkspaceToSettings not found"
    body = m.group(1)
    assert "saveSetupWorkspaceIfNeeded" in body, (
        "syncWorkspaceToSettings copies the value into hidden inputs but never persists it — the "
        "fresh-install workspace is discarded and file tools stay blind (the shipped bug)"
    )
    assert "async function syncWorkspaceToSettings" in src, "must be async to await the POST"


def test_the_next_handler_awaits_the_persist():
    src = (UI / "components" / "wizard.js").read_text(encoding="utf-8")
    assert re.search(r"step === 2\)\s*await syncWorkspaceToSettings\(\)", src), (
        "onNext must AWAIT syncWorkspaceToSettings, or the POST races the wizard advancing"
    )


def test_backend_accepts_sandbox_root():
    """The POST target must actually be a writable setting, or persistence silently no-ops."""
    import sys
    sys.path.insert(0, str(UI.parent))
    from config_schema import EDITABLE_SCHEMA
    assert any(e["key"] == "sandbox_root" for e in EDITABLE_SCHEMA), "sandbox_root not an editable setting"
    settings_src = (UI.parent / "routers" / "settings.py").read_text(encoding="utf-8")
    assert '"sandbox_root"' in settings_src, "settings router does not list sandbox_root as writable"

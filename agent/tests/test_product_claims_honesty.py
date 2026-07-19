"""
A1 + A2 last mile, and A3 — the product must not advertise or confirm what it did not do.

Two kinds of check live here:

  * DOC CLAIMS (A3): the README sold Voice I/O with no caveat while the engines are not
    installed by the standard installer and /voice/speak returns 503, and sold Playwright
    browser automation without its separate `playwright install chromium` step.
    .identity/capabilities.md was already honest about both — it is the file that was
    DRIVEN last slice, so it is the reference the README has to agree with.

  * UI WIRING (the last mile): a wired endpoint with no UI feedback is not a fix. The
    operator must SEE the install run, SEE it fail, SEE that a key is auto-tune-owned, and
    SEE a rejected write.

Like tests/test_voice_toggle_honesty.py, the UI checks are source-contract tests over ES
modules — this repo has no JS test runner, so they assert the wiring exists rather than
execute it. That is a real limit and is stated rather than papered over: they prove the call
and the render path are present, not that a browser then paints them. Each fails if its
defect is reintroduced, which was verified by reverting each in turn.
"""
from __future__ import annotations

from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
REPO = AGENT.parent
UI = AGENT / "ui"

README = (REPO / "README.md").read_text(encoding="utf-8")
CAPABILITIES = (REPO / ".identity" / "capabilities.md").read_text(encoding="utf-8")
SETUP_WIZ = (UI / "components" / "setup-profiles.js").read_text(encoding="utf-8")
MARKETPLACE = (UI / "components" / "marketplace.js").read_text(encoding="utf-8")
SETTINGS = (UI / "components" / "settings-full.js").read_text(encoding="utf-8")


# ── A3: README claims match the manifest that was actually driven ────────────────
def test_readme_caveats_voice_instead_of_advertising_it_flat():
    """The engines are not installed by the standard installer and /voice/speak returns 503.
    capabilities.md says so; the README said "supports voice I/O" with no caveat."""
    assert "503" in CAPABILITIES, "premise check: capabilities.md documents the 503"
    assert "503" in README, "README must state that voice returns 503 until installed"
    assert "not installed by default" in README or "NOT installed by the standard installer" in README


def test_readme_states_the_playwright_browser_install_step():
    """Real code, but it needs `playwright install chromium`; the tools return that exact
    string when it is missing. Advertising the feature without the step is the same class
    of claim-outruns-behaviour defect."""
    web_tool = (AGENT / "layla" / "tools" / "impl" / "web.py").read_text(encoding="utf-8")
    assert "playwright install chromium" in web_tool, "premise check: the tool demands this step"
    assert "playwright install chromium" in README


def test_readme_does_not_call_a_voice_extra_shipped_by_default():
    """pyttsx3 lives in the [voice] extra, and the installer installs [cpu,llm,research,crawl] —
    so "shipped default" named a package no standard install has."""
    assert "TTS — shipped default" not in README


def test_installer_installs_the_web_facing_deps_it_advertises():
    """README advertises web search + article extraction. bootstrap installed only [cpu,llm],
    so those tools were dead on every fresh install."""
    for script in ("bootstrap.ps1", "bootstrap.sh"):
        text = (REPO / "install" / script).read_text(encoding="utf-8")
        assert "research" in text and "crawl" in text, f"{script} omits the research/crawl extras"


def test_study_scheduler_claim_is_true_and_kept():
    """A3 asked for the "optional study scheduler" claim to be cut as dead. It is NOT dead —
    _scheduled_study_job is a registered APScheduler job that runs real study plans — so the
    claim stays. This test pins the fact that justified keeping it."""
    from layla.scheduler.jobs import _scheduled_study_job  # noqa: F401

    registry = (AGENT / "layla" / "scheduler" / "registry.py").read_text(encoding="utf-8")
    assert "_scheduled_study_job" in registry and "scheduled_study" in registry
    assert "study scheduler" in README


# ── A1 last mile: the operator sees the install run, and sees it fail ────────────
def test_wizard_calls_the_install_endpoint_it_advertises():
    """The wizard rendered "installs: <deps>" and POSTed only to /setup/apply, which flips
    flags. The install endpoint had ZERO product callers."""
    assert "installs: " in SETUP_WIZ, "premise check: the wizard still makes the claim"
    assert "'/setup/feature/install'" in SETUP_WIZ, "the wizard must call the installer"
    assert "confirm: true" in SETUP_WIZ


def test_wizard_acts_on_the_install_plan_the_server_returns():
    assert "d.to_install" in SETUP_WIZ, "/setup/apply returns to_install; the wizard must use it"


def test_wizard_shows_progress_and_the_real_failure_reason():
    assert "_runInstalls" in SETUP_WIZ
    assert "state: 'running'" in SETUP_WIZ, "no visible in-progress state"
    assert "state: 'fail'" in SETUP_WIZ, "no visible failure state"
    # The pip stderr must reach the screen, not just a generic 'failed'.
    assert "d.failed" in SETUP_WIZ and "x.error" in SETUP_WIZ


def test_wizard_asks_before_spending_bandwidth():
    """A real pip install is heavy and network-bound; it must not start unannounced."""
    assert "install now" in SETUP_WIZ and "setupwiz-run-inst" in SETUP_WIZ


def test_wizard_skip_path_states_what_did_not_happen():
    assert "Enabled, but not installed" in SETUP_WIZ


def test_marketplace_does_not_toast_installed_before_checking():
    """kit_catalog discarded the plan and the UI toasted "Installed <kit>" regardless."""
    idx_fail = MARKETPLACE.index("d.ok === false")
    idx_toast = MARKETPLACE.index('"Installed " + kitId')
    assert idx_fail < idx_toast, "the success toast must come after the failure check"
    assert "not installed — " in MARKETPLACE, "a failed kit install must say so on the row"


def test_marketplace_surfaces_the_failing_package():
    assert "d.failed" in MARKETPLACE and "x.dep" in MARKETPLACE


def test_install_css_has_a_visible_failure_state():
    css = (UI / "css" / "layla-rebuild.css").read_text(encoding="utf-8")
    assert '.setupwiz-irow[data-state="fail"]' in css
    assert '.mkt-status[data-kind="err"]' in css


# ── A2 last mile: the operator sees ownership and sees rejections ────────────────
def test_settings_ui_reads_the_response_body_instead_of_just_the_status():
    """It toasted "Settings saved" off res.ok alone, so a dropped or reverted write produced
    the same confident message as one that landed."""
    assert "d.rejected" in SETTINGS
    assert "res.json()" in SETTINGS
    # S3: the per-key read-back, which superseded the flat `overridden` list — the UI must show
    # WHICH key did not take effect and WHO holds it, not just that something went wrong.
    assert "d.report" in SETTINGS
    assert "_renderNotInForce" in SETTINGS


def test_settings_ui_shows_a_save_that_did_not_take_effect():
    """S3, the last mile. The server can be perfectly honest and the operator still learns
    nothing if the answer never reaches the screen — or reaches it in green.

    C3 — WHAT THIS TEST COULD NOT SEE, AND WHY IT IS NARROWER NOW. It used to assert
    `"NOT in force" in SETTINGS` and call that the last mile covered. The string was present
    and the behaviour was wrong: the panel drew the warning only from the response to a save,
    so an unrelated save retracted it and left a ticked checkbox under a green success. A grep
    for a phrase cannot distinguish those, exactly as the 17 text-grep tests that passed
    against a dead UI earlier in this phase could not.

    So this now asserts only what a static file CAN prove — that the panel is wired into the
    page at all. The behaviour is driven, as a sequence, in
    tests/test_settings_readback.py::test_not_in_force_survives_a_later_unrelated_save.
    """
    assert "settings-not-in-force" in SETTINGS
    # It must be reachable from the page, not just defined in a module.
    assert 'id="settings-not-in-force"' in (UI / "index.html").read_text(encoding="utf-8")


def test_the_settings_panel_can_learn_what_is_held_without_saving():
    """C3, the structural gap under the retraction bug: `key_owner` had NO GET consumer, so
    "not in force" was knowable only as a side effect of saving that exact key. The panel must
    load the state, or reopening it shows a snapped-back control and no explanation."""
    import routers.settings as rs_router

    with open(rs_router.__file__, encoding="utf-8") as fh:
        assert "/settings/not_in_force" in fh.read(), "no GET consumer for the read-back"
    # …and the panel must actually call it on load, not merely define the helper.
    assert "/settings/not_in_force" in SETTINGS
    assert "_loadNotInForce" in SETTINGS
    open_fn = SETTINGS[SETTINGS.index("export async function openSettings"):]
    open_fn = open_fn[:open_fn.index("export function closeSettings")]
    assert "_loadNotInForce" in open_fn, "the panel does not load the held-key state on open"


def test_a_save_that_did_not_take_effect_is_amber_not_green_and_not_red():
    """A third outcome — the bytes DID land — so a third colour. Green would repeat the
    original lie; red is reserved for a write that was refused.

    A stylesheet is one of the few things a static assertion genuinely settles: the rule
    either exists in the bundle or it does not. That the rule reaches the right ELEMENT is a
    behaviour, and is verified in the browser.
    """
    css = (UI / "css" / "layla.css").read_text(encoding="utf-8")
    assert ".settings-not-in-force" in css
    assert "#ffb454" in css.split(".settings-not-in-force")[1][:900], "not styled as a warning"
    assert ".settings-row.is-not-in-force" in css, "the control itself is not marked"


def test_the_preset_toast_cannot_report_a_preset_it_did_not_put_in_force():
    """C1's client half. `showToast(d.ok ? 'Preset applied: ' + name : ...)` printed green off
    a flag the server returned unconditionally — for the "potato" preset, on the box whose
    hardware auto-tune reverts three of its keys."""
    fn = SETTINGS[SETTINGS.index("export async function applySettingsPreset"):]
    fn = fn[:fn.index("// ── Appearance panel")]
    assert "not_in_force" in fn, "the preset toast ignores the read-back"
    assert "d.ok ? 'Preset applied: '" not in fn, "still toasting success off the ok flag alone"


def test_the_theme_toggle_renders_the_effective_state_not_the_click():
    """C2's client half. The checkbox renders from the effective config, so a flag an owner
    reverts snapped back on reopen — with a green success toast still over it."""
    fn = SETTINGS[SETTINGS.index("export async function laylaToggleFeatureTheme"):]
    fn = fn[:fn.index("try { window.laylaToggleFeatureTheme")]
    assert "d.enabled" in fn, "the toggle does not read the server's effective state"
    assert "box.checked = effective" in fn, "the control is not corrected to what is in force"
    assert "in_force" in fn


def test_settings_ui_marks_auto_tune_owned_controls():
    assert "auto_tune_owned" in SETTINGS
    assert "auto-tune owns this" in SETTINGS
    assert "cfg-owner" in SETTINGS


def test_settings_ui_tells_the_user_how_to_make_the_value_stick():
    assert "auto_tune_locked_keys" in SETTINGS or "Auto tune locked keys" in SETTINGS
    assert "does not stick" in SETTINGS


def test_settings_ui_renders_the_list_type_control():
    """auto_tune_locked_keys is the escape hatch; a `list` field rendered by the string branch
    would post the literal text "n_ctx,hyde" as a value and quietly fail to lock anything."""
    assert "'list'" in SETTINGS


def test_settings_warning_is_not_styled_as_success():
    css = (UI / "css" / "layla.css").read_text(encoding="utf-8")
    assert '.settings-save-msg[data-kind="warn"]' in css
    assert ".cfg-owner" in css


def test_theme_toggle_reports_the_lock_it_took():
    assert "auto_tune_locked_keys" in SETTINGS
    assert "cannot revert it" in SETTINGS


def test_service_worker_cache_was_bumped():
    """A UI change behind a stale service-worker cache ships nothing to the operator."""
    sw = (UI / "sw.js").read_text(encoding="utf-8")
    assert 'const CACHE = "layla-ui-v19"' not in sw, "sw.js CACHE not bumped — assets will be stale"

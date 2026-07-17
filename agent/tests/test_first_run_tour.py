"""BL-249 — the first-run tour must actually render and teach Ctrl+K.

The tour was dead for months: setup.js reached for #onboarding-text / -next / -done, none of which existed,
so maybeStartTour() bailed on every run and nothing errored. The fix gives it real markup (#tour-*), real
handler registration, and a wizard handoff.

This runs ui/tools/test_first_run.mjs, which IMPORTS setup.js and EXECUTES its real exported functions against
a stub DOM — asserting the tour opens, steps through, reaches the Ctrl+K step, dismisses, persists its marker,
and (critically) refuses to open while the wizard still owns first-run. It is not a text grep: if the tour
stops rendering or the Ctrl+K step disappears, this fails.

The static element-contract guard (test_ui_element_contract.py) is the complement: it proves #tour-* exists
and that the old #onboarding-text/-next/-done lookups are gone from the ratchet. Together they cover "the
markup exists" AND "the behaviour is real".
"""
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui"
SCRIPT = UI / "tools" / "test_first_run.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def test_first_run_tour_behaviour():
    assert SCRIPT.exists(), f"tour behaviour script missing: {SCRIPT}"
    proc = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=str(UI),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0 and "all assertions passed" in proc.stdout, (
        "The first-run tour behaviour test FAILED — the tour does not render/teach/dismiss as required:\n"
        + combined
    )


def test_tour_markup_present_and_wired():
    """Belt-and-braces on the markup side: the tour ids exist in index.html with their data-actions, and the
    dead #onboarding-* tour ids are gone from the JS. (The ratchet in test_ui_element_contract.py enforces the
    latter globally; this pins the specific feature.)"""
    html = (UI / "index.html").read_text(encoding="utf-8", errors="replace")
    for tid in ("tour-overlay", "tour-text", "tour-next", "tour-done"):
        assert f'id="{tid}"' in html, f"#{tid} missing from index.html — the tour has no DOM to render into"
    assert 'data-action="tourNext"' in html, "tour Next button is not wired to tourNext"
    assert 'data-action="dismissTour"' in html, "tour Done button is not wired to dismissTour"

    setup_src = (UI / "components" / "setup.js").read_text(encoding="utf-8", errors="replace")
    for dead in ("'onboarding-text'", "'onboarding-next'", "'onboarding-done'"):
        assert dead not in setup_src, f"setup.js still reaches for the dead id {dead}"

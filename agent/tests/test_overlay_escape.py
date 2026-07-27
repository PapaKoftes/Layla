"""BL-386 follow-up — every ⌘K overlay must be escapable, not just setup-profiles.

BL-386 fixed the "set up layla" modal's dead Escape by moving its keydown listener off _root (which
never receives a keydown while focus is on <body>) onto document (capture). Twenty-one sibling overlays
in ui/components/ shipped the identical latent bug: the Escape handler lived on _root, and none of them
focus anything on open, so the advertised "esc" chip promised an exit that never fired — the same trap
the operator hit. (approvals, agent-tasks, custom-aspect, missions, kb, codex, journal, improvements,
marketplace, plans, intake-quiz, macros, intelligence, self-test, german, sync, system-diagnostics,
tools-history, tutor, verify, debate.)

This runs ui/tools/test_overlay_escape.mjs, which IMPORTS each real module and EXECUTES its real
openX()/closeX() against a stub DOM — asserting, for every overlay: it opens+shows, registers exactly
one document keydown listener, a document Escape (focus on <body>) closes it AND removes the listener,
reopening does not accumulate listeners (no leak), and the esc-chip click closes it. It is not a text
grep: if any overlay regresses to a _root-only handler or a non-clickable chip, this fails.

Complements test_setup_profiles_escape.py (the modal that started this) and test_ui_link.py (the graph
still links).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui"
SCRIPT = UI / "tools" / "test_overlay_escape.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def test_all_overlays_escapable():
    assert SCRIPT.exists(), f"overlay escape behaviour script missing: {SCRIPT}"
    proc = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=str(UI),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0 and "all assertions passed" in proc.stdout, (
        "One or more ⌘K overlays are inescapable again — an 'esc' chip that advertises an exit that "
        "never fires (the BL-386 defect):\n" + combined
    )

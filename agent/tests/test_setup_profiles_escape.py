"""BL-386 — the "set up layla" modal must be answerable AND escapable.

The operator hit a modal with ZERO options rendered, a "continue" that said "pick at least one"
forever, and an "esc" chip / Escape key that did nothing — an unwinnable, inescapable trap. Two
defects in ui/components/setup-profiles.js:

  1. A failed/empty /setup/profiles load rendered a SILENT empty forEach (no cards, no error, no
     way forward) instead of a visible failure with retry + escape.
  2. The Escape handler lived on _root, which never receives a keydown when focus is on <body>
     (the first-run default), so the advertised exit never fired; the esc chip was not clickable.

This runs ui/tools/test_setup_profiles_escape.mjs, which IMPORTS the real setup-profiles.js and
EXECUTES its openSetupProfiles()/closeSetupProfiles() against a stub DOM — asserting options render,
a failed load fails visibly (error + retry + skip, continue hidden), Escape via document closes it,
the esc chip closes it, and the document listener is removed on close (no accumulation). It is not a
text grep: if any of those regress, this fails. The link check (linkcheck.mjs, run by
test_ui_link.py::test_main_module_graph_links) is the complement that proves the graph still links.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui"
SCRIPT = UI / "tools" / "test_setup_profiles_escape.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def test_setup_profiles_escape_and_empty_behaviour():
    assert SCRIPT.exists(), f"setup-profiles behaviour script missing: {SCRIPT}"
    proc = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=str(UI),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0 and "all assertions passed" in proc.stdout, (
        "The setup-profiles escape/empty behaviour test FAILED — the modal is a dead-end or "
        "inescapable again:\n" + combined
    )

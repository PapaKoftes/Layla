"""The guard that would have caught the dead UI: the ES-module graph must LINK.

An earlier attempt at this phase shipped a 100% dead app — every feature broken, the sidebar stuck on
"Loading…" forever — because one module imported a named export that did not exist. A missing/renamed export
is an ES-module INSTANTIATION error: the whole graph fails to link before a single line runs, so nothing
errors at edit time and every "test" that reads the .js as text still passes. 24 of them did.

This test EXECUTES the module graph in Node with a stub DOM (ui/tools/linkcheck.mjs). If any import cannot be
resolved — a missing export, a renamed function, a deleted file — `import('./main.js')` rejects at
instantiation and this fails. It cannot pass against a graph that would not link in a browser.

It is paired with a NEGATIVE self-test: the harness is pointed at a module that imports a name that does not
exist, and we assert it reports LINK FAILED. A green checkmark that cannot go red is worthless; this proves
the check has teeth in the same run.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "ui"
HARNESS = UI / "tools" / "linkcheck.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run_harness(entry: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(HARNESS), entry],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_main_module_graph_links():
    """The real assertion: ui/main.js (and everything it imports) links cleanly."""
    assert HARNESS.exists(), f"link harness missing: {HARNESS}"
    proc = _run_harness("./main.js", UI)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0 and "LINK OK" in proc.stdout, (
        "The Layla UI module graph FAILED TO LINK — the app would boot to a dead page.\n"
        "This is almost always a missing or renamed export somewhere in the import chain.\n\n"
        + combined
    )


def test_harness_has_teeth(tmp_path):
    """A link check that cannot fail is theatre. Point it at a module importing a non-existent export and
    assert it reports LINK FAILED — proving THIS test would catch the exact bug that shipped a dead UI."""
    bad = UI / "tools" / "_link_negtest_tmp.mjs"
    bad.write_text(
        "import { __definitely_not_a_real_export__ } from '../components/setup.js';\n"
        "console.log(typeof __definitely_not_a_real_export__);\n",
        encoding="utf-8",
    )
    try:
        proc = _run_harness("./tools/_link_negtest_tmp.mjs", UI)
    finally:
        bad.unlink(missing_ok=True)
    assert proc.returncode != 0, "harness passed a module with a missing export — it has no teeth"
    assert "LINK FAILED" in (proc.stderr or "") and "does not provide an export" in (proc.stderr or ""), (
        "harness did not classify a missing export as a LINK failure:\n" + (proc.stderr or "")
    )

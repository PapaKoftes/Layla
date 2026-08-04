"""The UI last mile is proven by Playwright e2e tests (agent/tests/e2e_ui/). Those are deselected in
the local ci-gate (no chromium) and only run in the GitHub `e2e-ui` job. That job is therefore the
ONLY thing standing between a broken Castilla shell and a green release — so lock it in place: this
test fails if the e2e-ui CI job (or its chromium install / marker run) is ever silently removed."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_yml_exists():
    assert CI_YML.is_file(), "ci.yml missing — CI is the only gate that runs the UI e2e tests"


def _e2e_job_block(ci: str) -> str:
    """The e2e-ui job text, from its header to the next top-level job (2-space-indented 'name:')."""
    start = ci.index("e2e-ui:")
    rest = ci[start + len("e2e-ui:"):]
    # next top-level job starts with a 2-space-indented '<name>:' line
    import re
    m = re.search(r"\n  [A-Za-z0-9_-]+:\n", rest)
    return rest[: m.start()] if m else rest


def test_e2e_ui_job_is_wired_and_runs_playwright():
    ci = CI_YML.read_text(encoding="utf-8")
    # the dedicated job
    assert "e2e-ui:" in ci, "the e2e-ui CI job was removed — UI coverage would ship unverified"
    block = _e2e_job_block(ci)
    # it must install the e2e deps + a real browser, and actually run the e2e_ui marker
    assert "requirements-e2e.txt" in block
    assert "playwright install chromium" in block
    assert "-m e2e_ui" in block
    # and the e2e-ui job itself must NOT be allowed to fail silently
    assert "continue-on-error" not in block, "the e2e-ui job must not continue-on-error"


def test_unit_jobs_deselect_e2e_so_it_is_not_double_counted_or_skipped_silently():
    # The unit jobs correctly exclude e2e_ui (it needs a browser); this asserts the marker split is
    # intact so e2e tests can't silently vanish into a 'not e2e_ui' deselection with no job running them.
    ci = CI_YML.read_text(encoding="utf-8")
    assert "not e2e_ui" in ci  # unit jobs exclude it
    assert ci.count("-m e2e_ui") >= 1  # ...and a job includes it

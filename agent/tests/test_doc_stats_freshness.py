"""Regression guard for stale hardcoded stats in collaborator-facing docs.

The root README and docs/README once advertised "858 tests" while the real
suite had grown to ~3,000 `def test_` functions — off by ~3-4x. These docs are
what collaborators read to gauge suite size/health, so a stale figure materially
misrepresents the project. This test fails if the stale figure reappears and
sanity-checks that the documented magnitude is not wildly below reality.
"""

from pathlib import Path

# tests/ -> agent/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_TESTS = _REPO_ROOT / "agent" / "tests"

_LIVE_DOCS = [
    _REPO_ROOT / "docs" / "README.md",
    _REPO_ROOT / "README.md",
]


def _actual_test_function_count() -> int:
    count = 0
    for py in _AGENT_TESTS.rglob("test_*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if line.lstrip().startswith("def test_"):
                count += 1
    return count


def test_live_docs_do_not_advertise_stale_858_test_count():
    """The stale '858 tests'/'858 passing' figure must not resurface."""
    for doc in _LIVE_DOCS:
        assert doc.exists(), f"expected doc missing: {doc}"
        text = doc.read_text(encoding="utf-8")
        assert "858 passing" not in text, (
            f"{doc} still advertises the stale '858 passing' test count"
        )
        assert "858 tests" not in text, (
            f"{doc} still advertises the stale '858 tests' count"
        )


def test_actual_suite_is_far_larger_than_the_old_858_figure():
    """Sanity anchor: the real suite is ~3,000 tests, proving 858 was stale."""
    actual = _actual_test_function_count()
    assert actual > 2000, (
        f"expected the test suite to contain >2000 test functions, found {actual}; "
        "if the suite genuinely shrank, the doc figures need revisiting"
    )

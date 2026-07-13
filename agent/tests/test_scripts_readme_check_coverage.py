"""Regression guard: scripts/README.md must document every wired health check.

The "Scripts" table in agent/scripts/README.md drifted out of sync with the
authoritative `CHECKS` list in scripts/run_all_checks.py — it documented only 7
of the 11 wired checks, omitting check_memory_coherence and check_repo_index
(both FAIL-severity CI gates), check_wiring, and check_memory_router_enforcement.
This test parses run_all_checks.py as the source of truth and fails if any wired
check is missing from the README or documented with the wrong severity.
"""

import re
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _AGENT_DIR / "scripts"
_RUN_ALL = _SCRIPTS_DIR / "run_all_checks.py"
_README = _SCRIPTS_DIR / "README.md"

# Matches CHECKS rows like:  ("Bug patterns", SCRIPTS_DIR / "check_patterns.py", "FAIL"),
_CHECK_ROW = re.compile(
    r'SCRIPTS_DIR\s*/\s*"(check_[a-z_]+\.py)"\s*,\s*"(FAIL|WARN)"'
)


def _wired_checks() -> dict[str, str]:
    """{script_basename: severity} extracted from run_all_checks.py CHECKS."""
    text = _RUN_ALL.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in _CHECK_ROW.finditer(text)}


def _readme_rows() -> dict[str, str]:
    """{script_basename: severity} extracted from the README Scripts table."""
    rows: dict[str, str] = {}
    for line in _README.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`(check_[a-z_]+\.py)`\s*\|\s*(FAIL|WARN|—)\s*\|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_readme_documents_every_wired_check_with_matching_severity():
    wired = _wired_checks()
    # Sanity: run_all_checks.py should wire the known 11 checks.
    assert len(wired) >= 11, f"expected >=11 wired checks, parsed {len(wired)}: {wired}"

    documented = _readme_rows()
    for script, severity in wired.items():
        assert script in documented, (
            f"{script} is wired in run_all_checks.py but missing from "
            f"scripts/README.md Scripts table"
        )
        assert documented[script] == severity, (
            f"{script} severity mismatch: run_all_checks.py says {severity}, "
            f"README says {documented[script]}"
        )


def test_readme_mentions_standalone_check_architecture():
    """check_architecture.py exists on disk but is not wired; it must still be documented."""
    assert (_SCRIPTS_DIR / "check_architecture.py").exists()
    text = _README.read_text(encoding="utf-8")
    assert "check_architecture.py" in text, (
        "check_architecture.py exists but is undocumented in scripts/README.md"
    )

"""Regression tests for defects found by the total adversarial audit (wf_b0ad28f4, 2026-08-01)."""
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class _FakeProc:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_security_scan_does_not_fake_clean_when_bandit_absent(tmp_path):
    """BROKEN finding: `python -m bandit` with bandit absent exits 1 with empty stdout, and the old
    code json.loads('{}')-ed that into ok:True / 0 issues — a FALSE 'no security issues'. It must now
    report failure, never a clean bill of health."""
    from layla.tools.impl import code as code_mod

    f = tmp_path / "x.py"
    f.write_text("import os\n", encoding="utf-8")

    # bandit absent: non-zero exit, empty stdout, "No module named bandit" on stderr.
    with patch.object(code_mod, "inside_sandbox", return_value=True), \
         patch("subprocess.run", return_value=_FakeProc(1, "", "No module named bandit")):
        res = code_mod.security_scan(str(f), scan_type="bandit")
    assert res.get("ok") is False, "a scan that did not run must NOT report ok:True"
    assert "bandit" in (res.get("error") or "").lower()
    assert res.get("issue_count") in (None, 0) and "issues" not in res or not res.get("issues")


def test_security_scan_parses_a_real_bandit_result(tmp_path):
    """A genuine bandit run (valid JSON with results/metrics) still works."""
    from layla.tools.impl import code as code_mod

    f = tmp_path / "y.py"
    f.write_text("x = 1\n", encoding="utf-8")
    good = '{"results": [], "metrics": {"_totals": {"loc": 1}}}'
    with patch.object(code_mod, "inside_sandbox", return_value=True), \
         patch("subprocess.run", return_value=_FakeProc(0, good, "")):
        res = code_mod.security_scan(str(f), scan_type="bandit")
    assert res.get("ok") is True
    assert res.get("issue_count") == 0

"""v1.7.5 new tools: code_definition (jedi), ml_analyze (sklearn), security_scan semgrep mode.

Robust to whether the optional deps are installed: with the dep present, assert real behavior;
without it, assert the graceful ok:False + install hint (never a fake success)."""
import csv
import os
import tempfile

import pytest

import layla.tools.sandbox_core as sc
from layla.tools.impl.code import code_definition, security_scan
from layla.tools.impl.data import ml_analyze


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    try:
        sc.set_effective_sandbox(str(tmp_path))
    except Exception:
        monkeypatch.setattr(sc._effective_sandbox, "path", str(tmp_path), raising=False)
    return tmp_path


def test_registered_at_206():
    from layla.tools import registry
    assert "code_definition" in registry.TOOLS
    assert "ml_analyze" in registry.TOOLS


def test_code_definition(sandbox):
    f = sandbox / "sample.py"
    f.write_text("def greet(name):\n    return 'hi ' + name\n\nx = greet('a')\n", encoding="utf-8")
    r = code_definition(str(f), 4, 5)  # the greet(...) call
    if not r["ok"]:
        assert "jedi not installed" in r["error"]
        return
    assert any(d["name"] == "greet" and d["line"] == 1 for d in r["definitions"])


def test_ml_analyze(sandbox):
    csvf = sandbox / "d.csv"
    with csvf.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["a", "b", "y"])
        for i in range(30):
            w.writerow([i, i * 2 + 1, i % 2])
    cl = ml_analyze(str(csvf), task="cluster", n_clusters=2)
    if not cl["ok"]:
        assert "not installed" in cl["error"]
        return
    assert sum(cl["cluster_sizes"].values()) == 30
    assert ml_analyze(str(csvf), task="regress", target_column="b")["r2"] == pytest.approx(1.0, abs=1e-6)
    assert ml_analyze(str(csvf), task="frobnicate")["ok"] is False  # unknown task, not a crash


def test_semgrep_mode_is_graceful(sandbox):
    f = sandbox / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    r = security_scan(str(f), scan_type="semgrep")
    # Either it ran (ok True) or it's absent — but NEVER a fake clean result with no scan.
    assert r["ok"] is True or "semgrep" in r["error"].lower()


def test_benchmark_hardware_reports_tier_and_profile():
    from layla.tools.impl.system import benchmark_hardware
    r = benchmark_hardware()  # measure_speed defaults False -> no model needed, cheap
    assert r["ok"] is True
    assert r["tier"] in ("potato", "cpu", "cpu_plus", "gpu_low", "gpu_mid", "gpu_high", "unknown")
    assert r["accelerator"] in ("cpu", "gpu")
    assert "n_ctx" in r["applied_settings"]
    assert isinstance(r["summary"], str) and r["summary"]

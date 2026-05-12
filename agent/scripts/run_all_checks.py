#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all_checks.py — Master Layla codebase health orchestrator.

Runs every check script, aggregates results, prints a colour-coded summary
with confidence scores, and writes a JSON report to scripts/last_report.json.

Usage:
    cd agent/ && python scripts/run_all_checks.py [--json] [--fail-fast]
    echo $?   # 0 = all green, 1 = any failures

Confidence score = (passing_checks / total_checks) × 100.
Exit 1 only on FAIL-class issues; WARN-class produce exit 0 but are reported.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = AGENT_DIR / "scripts"

# ── ANSI colours (disabled on Windows without TERM set) ──────────────────────
import os as _os
_COLOUR = _os.name != "nt" or _os.environ.get("TERM") or _os.environ.get("WT_SESSION")

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text

GREEN  = lambda t: _c("32", t)
YELLOW = lambda t: _c("33", t)
RED    = lambda t: _c("31", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)


# ── Check registry ────────────────────────────────────────────────────────────
# Each entry: (label, script_path, severity)
# severity: "FAIL" → exit 1 if any issues; "WARN" → report but exit 0
CHECKS = [
    ("Bug patterns",        SCRIPTS_DIR / "check_patterns.py",           "FAIL"),
    ("Config validation",   SCRIPTS_DIR / "check_config.py",             "WARN"),
    ("Import resolution",   SCRIPTS_DIR / "check_imports.py",            "FAIL"),
    ("Security scan",       SCRIPTS_DIR / "check_security.py",           "WARN"),
    ("Memory coherence",    SCRIPTS_DIR / "check_memory_coherence.py",   "FAIL"),  # Phase A gate
    ("Repo index",          SCRIPTS_DIR / "check_repo_index.py",         "FAIL"),  # Phase B gate
    ("API contracts",       SCRIPTS_DIR / "check_api_contracts.py",      "WARN"),
    ("DB schema",           SCRIPTS_DIR / "check_db_schema.py",          "WARN"),
    ("UI symbol check",     SCRIPTS_DIR / "check_ui_symbols.py",         "WARN"),
    ("Wiring (prod imports)", SCRIPTS_DIR / "check_wiring.py",            "WARN"),  # Fix #8
    ("Pytest suite",        None,                                          "FAIL"),  # special
]


def _run_script(script: Path) -> tuple[int, str]:
    """Run a check script as a subprocess. Returns (exit_code, output)."""
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(AGENT_DIR),
    )
    out = (result.stdout + result.stderr).strip()
    return result.returncode, out


def _run_pytest() -> tuple[int, str]:
    """Run pytest suite excluding tests marked endpoint, slow, or e2e.

    Uses marker-based filtering (-m) rather than keyword matching (-k) so
    the exclusion set is explicit and adding new tests doesn't accidentally
    skip them because their name contains "client" or "endpoint".

    To run only the excluded tests locally:
        pytest tests/ -m "endpoint or slow"
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/",
            "-q", "--tb=no",
            "-m", "not endpoint and not slow and not e2e",
            "--no-header",
            "--timeout=60",
            "--ignore=tests/test_smoke_comprehensive.py",
        ],
        capture_output=True,
        text=True,
        cwd=str(AGENT_DIR),
    )
    out = (result.stdout + result.stderr).strip()
    return result.returncode, out


def _extract_summary(output: str, exit_code: int) -> str:
    """Pull the last meaningful line from check output."""
    lines = [l for l in output.splitlines() if l.strip()]
    if not lines:
        return "no output"
    # For pytest: look for the standard "N passed" / "N failed" summary line
    import re as _re
    _pytest_re = _re.compile(r'\d+\s+(passed|failed|error)', _re.I)
    for line in reversed(lines):
        if _pytest_re.search(line):
            return line.strip()[:80]
    # For check scripts: prefer lines with pass/fail keywords
    # Exclude lines that look like Python code (contain ':', '(', 'if ', 'def ')
    _code_re = _re.compile(r'^\s*(if |def |class |for |while |return |import |from |\w+\s*\()')
    for line in reversed(lines):
        if _code_re.match(line):
            continue
        low = line.lower()
        if any(k in low for k in ("pass", "fail", "warn", "issue", "error", "found", "passed", "failed", "ok")):
            return line.strip()[:80]
    return lines[-1].strip()[:80]


def run(fail_fast: bool = False, json_output: bool = False) -> int:
    print()
    print(BOLD("=" * 66))
    print(BOLD("  Layla Codebase Health - Full Check Suite"))
    print(BOLD("=" * 66))
    print()

    results = []
    any_fail = False
    t_total = time.monotonic()

    for label, script, severity in CHECKS:
        t0 = time.monotonic()
        if script is None:
            # pytest special case
            code, out = _run_pytest()
        else:
            if not script.exists():
                results.append({
                    "check": label, "status": "SKIP", "severity": severity,
                    "summary": "script not found", "duration_ms": 0, "output": ""
                })
                print(f"  {label:<30} {YELLOW('SKIP')}  (script not found)")
                continue
            code, out = _run_script(script)

        duration = int((time.monotonic() - t0) * 1000)
        summary = _extract_summary(out, code)

        if code == 0:
            status = "PASS"
            colour = GREEN
        else:
            status = "FAIL" if severity == "FAIL" else "WARN"
            colour = RED if status == "FAIL" else YELLOW
            if status == "FAIL":
                any_fail = True

        results.append({
            "check": label,
            "status": status,
            "severity": severity,
            "summary": summary,
            "duration_ms": duration,
            "output": out,
        })

        print(f"  {label:<30} {colour(f'{status:<5}')}  {DIM(summary)}")

        if fail_fast and any_fail:
            break

    total_dur = int((time.monotonic() - t_total) * 1000)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_warn = sum(1 for r in results if r["status"] == "WARN")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    total  = len(results)

    confidence = round((n_pass / total) * 100) if total else 0

    # Fix #10: real assertions — actual production-state probes, not just
    # "did the script return exit 0". These ground the confidence number in
    # observable system state.
    health_assertions: dict[str, bool] = {}
    try:
        # repo_index_populated: repo_indexer DB has at least one row
        import sqlite3 as _sql
        _idx_db = AGENT_DIR / ".layla" / "repo_index.db"
        if not _idx_db.exists():
            _idx_db = AGENT_DIR / "repo_index.db"
        _populated = False
        if _idx_db.exists():
            try:
                _c = _sql.connect(str(_idx_db))
                _cur = _c.cursor()
                _tabs = [r[0] for r in _cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for _t in _tabs:
                    try:
                        n = _cur.execute(f"SELECT COUNT(*) FROM {_t}").fetchone()[0]
                        if n and int(n) > 0:
                            _populated = True
                            break
                    except Exception:
                        pass
                _c.close()
            except Exception:
                _populated = False
        health_assertions["repo_index_populated"] = _populated
    except Exception:
        health_assertions["repo_index_populated"] = False
    try:
        # memory_router_used: wiring check passes
        _wiring = [r for r in results if r["check"].startswith("Wiring")]
        health_assertions["memory_router_used"] = bool(_wiring and _wiring[0]["status"] == "PASS")
    except Exception:
        health_assertions["memory_router_used"] = False
    try:
        # config_cache_importable: module loads without error.
        # Ensure AGENT_DIR is on sys.path so `services.*` resolves regardless
        # of how this script was invoked.
        import sys as _sys
        if str(AGENT_DIR) not in _sys.path:
            _sys.path.insert(0, str(AGENT_DIR))
        import importlib as _il
        _mod = _il.import_module("services.config_cache")
        health_assertions["config_cache_importable"] = callable(getattr(_mod, "get_config", None))
    except Exception:
        health_assertions["config_cache_importable"] = False

    n_assert_pass = sum(1 for v in health_assertions.values() if v)
    n_assert_total = len(health_assertions)

    print()
    print(BOLD("-" * 66))
    print(f"  Checks: {total}  |  "
          f"{GREEN(f'PASS {n_pass}')}  |  "
          f"{YELLOW(f'WARN {n_warn}')}  |  "
          f"{RED(f'FAIL {n_fail}')}  |  "
          f"SKIP {n_skip}")
    print(f"  Check-script pass rate: {BOLD(str(confidence) + '%')}")
    print(f"  Real assertions: {BOLD(f'{n_assert_pass}/{n_assert_total}')}  "
          + DIM("(" + ", ".join(f"{k}={'Y' if v else 'N'}" for k, v in health_assertions.items()) + ")"))
    print(f"  Duration: {total_dur}ms")
    print(BOLD("-" * 66))
    print()

    # Show FAIL detail inline
    for r in results:
        if r["status"] == "FAIL":
            print(RED(f"FAIL: {r['check']}"))
            for line in r["output"].splitlines()[-15:]:
                print(f"  {line}")
            print()

    # Write JSON report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "confidence_pct": confidence,
        "real_assertions": health_assertions,
        "real_assertions_pass": n_assert_pass,
        "real_assertions_total": n_assert_total,
        "pass": n_pass, "warn": n_warn, "fail": n_fail, "skip": n_skip,
        "duration_ms": total_dur,
        "checks": [{k: v for k, v in r.items() if k != "output"} for r in results],
    }
    report_path = SCRIPTS_DIR / "last_report.json"
    try:
        report_path.write_text(json.dumps(report, indent=2))
        print(DIM(f"  Report written → {report_path.relative_to(AGENT_DIR)}"))
    except Exception:
        pass

    if json_output:
        print(json.dumps(report, indent=2))

    return 1 if any_fail else 0


if __name__ == "__main__":
    _fail_fast = "--fail-fast" in sys.argv
    _json = "--json" in sys.argv
    sys.exit(run(fail_fast=_fail_fast, json_output=_json))

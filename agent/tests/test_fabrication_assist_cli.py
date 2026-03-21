"""CLI end-to-end: module invocation, exit codes, --json, --dry-run, failure paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(argv: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-m", "fabrication_assist.assist", *argv],
        cwd=str(_REPO_ROOT),
        env=e,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_full_pipeline_markdown() -> None:
    p = _run_cli(["--session", str(_REPO_ROOT / "fabrication_assist" / ".assist_sessions" / "cli_e2e.json"), "CNC bracket"])
    # allow session path to be new
    assert p.returncode == 0, (p.stderr, p.stdout)
    assert "Assist summary" in p.stdout
    assert "|" in p.stdout
    assert not p.stderr.strip() or p.stderr.startswith("WARNING")


def test_cli_json_stdout() -> None:
    p = _run_cli(["--json", "--dry-run", "enclosure assembly"])
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert "intent" in data
    assert "variants" in data
    assert len(data["variants"]) == 3
    assert data.get("dry_run") is True


def test_cli_empty_input_exit_1() -> None:
    p = subprocess.run(
        [sys.executable, "-m", "fabrication_assist.assist"],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)},
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.returncode == 1


def test_cli_runner_subprocess_flag() -> None:
    sess = _REPO_ROOT / "fabrication_assist" / ".assist_sessions" / "cli_sub.json"
    p = _run_cli(["--runner", "subprocess", "--session", str(sess), "mill bracket"])
    assert p.returncode == 0, (p.stderr, p.stdout)
    assert "Assist summary" in p.stdout


def test_cli_kernel_fail_exit_3_json() -> None:
    p = _run_cli(
        ["--json", "--runner", "subprocess", "test"],
        env={"ECHO_KERNEL_FAIL": "1"},
    )
    assert p.returncode == 3, (p.stdout, p.stderr)
    err = json.loads(p.stdout)
    assert err.get("ok") is False


def test_cli_verbose_no_failure() -> None:
    p = _run_cli(["-v", "--dry-run", "hello"])
    assert p.returncode == 0
    # may log INFO to stderr
    assert "Dry run" in p.stdout or "dry" in p.stdout.lower()


def test_cli_corrupt_session_exit_5(tmp_path: Path) -> None:
    bad = tmp_path / "bad_sess.json"
    bad.write_text("{broken", encoding="utf-8")
    p = _run_cli(["--session", str(bad), "bracket"])
    assert p.returncode == 5, (p.stderr, p.stdout)

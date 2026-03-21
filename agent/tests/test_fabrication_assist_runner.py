"""Subprocess runner, failures, timeouts, and continue_on_runner_error."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fabrication_assist.assist.errors import RunnerError, SchemaValidationError
from fabrication_assist.assist.layla_lite import assist
from fabrication_assist.assist.runner import StubRunner, SubprocessJsonRunner


def test_subprocess_runner_assist_matches_stub_scores(tmp_path: Path) -> None:
    """Real subprocess echo_kernel: same deterministic formula as stub per variant id."""
    sp = tmp_path / "sess.json"
    stub_out = assist("CNC bracket", session_path=sp, runner=StubRunner())
    sp2 = tmp_path / "sess2.json"
    sub_out = assist("CNC bracket", session_path=sp2, runner=SubprocessJsonRunner(timeout_seconds=30.0))
    for a, b in zip(stub_out["results"], sub_out["results"], strict=True):
        assert a["variant_id"] == b["variant_id"]
        assert a["score"] == b["score"]
        assert a["metrics"] == b["metrics"]


def test_subprocess_runner_kernel_exit_fails() -> None:
    os.environ["ECHO_KERNEL_FAIL"] = "1"
    try:
        r = SubprocessJsonRunner(timeout_seconds=10.0)
        with pytest.raises(RunnerError) as ei:
            r.run_build({"id": "x", "label": "X"})
        assert "exited 2" in str(ei.value).lower() or "exited" in str(ei.value)
    finally:
        del os.environ["ECHO_KERNEL_FAIL"]


def test_subprocess_runner_bad_json_fails() -> None:
    os.environ["ECHO_KERNEL_BAD_JSON"] = "1"
    try:
        r = SubprocessJsonRunner(timeout_seconds=10.0)
        with pytest.raises(RunnerError) as ei:
            r.run_build({"id": "x", "label": "X"})
        assert "json" in str(ei.value).lower()
    finally:
        del os.environ["ECHO_KERNEL_BAD_JSON"]


def test_subprocess_runner_timeout() -> None:
    os.environ["ECHO_KERNEL_SLEEP"] = "3"
    try:
        r = SubprocessJsonRunner(timeout_seconds=0.15)
        with pytest.raises(RunnerError) as ei:
            r.run_build({"id": "slow", "label": "Slow"})
        assert "timeout" in str(ei.value).lower()
    finally:
        del os.environ["ECHO_KERNEL_SLEEP"]


def test_continue_on_runner_error_schema_invalid_kernel() -> None:
    class BadOutRunner:
        def run_build(self, config: dict) -> dict:
            return {"not": "valid"}

    out = assist(
        "CNC bracket",
        session_path=None,
        runner=BadOutRunner(),
        continue_on_runner_error=True,
    )
    assert len(out["results"]) == 3
    assert any(not r.get("feasible", True) for r in out["results"])
    assert out["errors"]


def test_assist_strict_schema_rejects_bad_runner_output() -> None:
    class BadOutRunner:
        def run_build(self, config: dict) -> dict:
            return {"variant_id": "a", "label": "A", "score": "nope", "metrics": {}}

    with pytest.raises(SchemaValidationError):
        assist("bracket", runner=BadOutRunner())

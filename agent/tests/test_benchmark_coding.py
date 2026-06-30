"""Tests for the coding benchmark harness (scripts/benchmark_coding.py, REQ-74).

Validates the harness deterministically (no model): code extraction, sandboxed
scoring of correct vs. wrong vs. infinite-loop solutions, and pass@1 aggregation.
"""
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import benchmark_coding as bench  # noqa: E402


def test_extract_code_from_fenced_block():
    text = "Sure!\n```python\ndef f():\n    return 1\n```\nDone."
    assert bench.extract_code(text, "f") == "def f():\n    return 1"


def test_extract_code_strips_leading_prose_without_fence():
    text = "Here is the function:\ndef f():\n    return 2"
    assert bench.extract_code(text, "f").startswith("def f():")


def test_run_one_passes_correct_solution(tmp_path):
    prob = next(p for p in bench.PROBLEMS if p["task_id"] == "sum_to_n")
    ok, detail = bench.run_one("def sum_to_n(n):\n    return n*(n+1)//2 if n>0 else 0", prob, tmp_path)
    assert ok is True and detail == "pass"


def test_run_one_fails_wrong_solution(tmp_path):
    prob = next(p for p in bench.PROBLEMS if p["task_id"] == "sum_to_n")
    ok, _ = bench.run_one("def sum_to_n(n):\n    return 0", prob, tmp_path)
    assert ok is False


def test_run_one_missing_entry_point(tmp_path):
    prob = next(p for p in bench.PROBLEMS if p["task_id"] == "is_palindrome")
    ok, detail = bench.run_one("def something_else():\n    return True", prob, tmp_path)
    assert ok is False and "entry point" in detail


def test_run_one_infinite_loop_times_out(tmp_path):
    prob = next(p for p in bench.PROBLEMS if p["task_id"] == "below_zero")
    ok, detail = bench.run_one("def below_zero(operations):\n    while True: pass", prob, tmp_path)
    assert ok is False and detail == "timeout"


def test_benchmark_self_test_solver_scores_perfect():
    with tempfile.TemporaryDirectory() as td:
        card = bench.benchmark(bench._self_test_solver, bench.PROBLEMS, Path(td))
    assert card["pass_at_1"] == 1.0
    assert card["passed"] == card["n"] == len(bench.PROBLEMS)


def test_benchmark_broken_solver_scores_below_one():
    def broken(prompt):
        return "```python\ndef wrong():\n    return None\n```", 5
    with tempfile.TemporaryDirectory() as td:
        card = bench.benchmark(broken, bench.PROBLEMS, Path(td))
    assert card["pass_at_1"] == 0.0
    assert card["passed"] == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

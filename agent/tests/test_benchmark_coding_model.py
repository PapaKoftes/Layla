"""
Live pass@1 regression for the coding harness (REQ-74) — the CI half of the eval harness.

The deterministic harness logic is covered by test_benchmark_coding.py (no model). This
test runs the *real* pass@1 against a GGUF and asserts a floor, so coding quality can't
silently regress. It is **opt-in** via the LAYLA_BENCH_MODEL env var so ordinary test
runs skip instantly (loading a model + generating 10 solutions costs minutes); CI points
it at a small model to enable the guard. Tune the floor with LAYLA_BENCH_FLOOR.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import benchmark_coding as bench  # noqa: E402

_MODEL = os.environ.get("LAYLA_BENCH_MODEL", "").strip()
_HAVE_MODEL = bool(_MODEL) and Path(_MODEL).exists()


@pytest.mark.skipif(
    not _HAVE_MODEL,
    reason="set LAYLA_BENCH_MODEL=/path/to/model.gguf to run the live pass@1 regression",
)
def test_coding_pass_at_1_meets_floor():
    floor = float(os.environ.get("LAYLA_BENCH_FLOOR", "0.5"))
    generate, close = bench._llama_generator(_MODEL)
    try:
        with tempfile.TemporaryDirectory(prefix="layla_bench_ci_") as td:
            card = bench.benchmark(generate, bench.PROBLEMS, Path(td))
    finally:
        try:
            close()
        except Exception:
            pass
    assert card["pass_at_1"] >= floor, (
        f"coding pass@1 {card['pass_at_1']:.2%} below floor {floor:.2%} "
        f"for {Path(_MODEL).name}: "
        + ", ".join(f"{r['task_id']}={'ok' if r['passed'] else r['detail']}" for r in card["results"])
    )


@pytest.mark.skipif(
    not _HAVE_MODEL,
    reason="set LAYLA_BENCH_MODEL=/path/to/model.gguf to run the live pass@1 regression",
)
def test_coding_hard_pass_at_1_meets_floor():
    """The discriminating HARD tier (DP/stacks/matrix/parsing) also guarded so quality
    can't silently regress on non-trivial problems. Tune with LAYLA_BENCH_HARD_FLOOR
    (default 0.5). The longer solutions need a larger token budget than the core set."""
    floor = float(os.environ.get("LAYLA_BENCH_HARD_FLOOR", "0.5"))
    generate, close = bench._llama_generator(_MODEL, max_tokens=640)
    try:
        with tempfile.TemporaryDirectory(prefix="layla_bench_ci_hard_") as td:
            card = bench.benchmark(generate, bench.PROBLEMS_HARD, Path(td))
    finally:
        try:
            close()
        except Exception:
            pass
    assert card["pass_at_1"] >= floor, (
        f"coding HARD pass@1 {card['pass_at_1']:.2%} below floor {floor:.2%} "
        f"for {Path(_MODEL).name}: "
        + ", ".join(f"{r['task_id']}={'ok' if r['passed'] else r['detail']}" for r in card["results"])
    )

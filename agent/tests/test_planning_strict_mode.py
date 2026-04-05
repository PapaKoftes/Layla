"""planning_strict_mode blocks mutating tools unless plan_approved."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_planning_strict_blocks_write_file_without_plan():
    import agent_loop as al

    cfg = {"planning_strict_mode": True}

    r = al._maybe_planning_strict_refusal(
        "write_file",
        cfg,
        {"plan_approved": False},
        allow_write=True,
        allow_run=False,
    )
    assert r is not None
    assert r.get("reason") == "planning_strict_mode"


def test_planning_strict_allows_when_plan_approved():
    import agent_loop as al

    cfg = {"planning_strict_mode": True}

    r = al._maybe_planning_strict_refusal(
        "write_file",
        cfg,
        {"plan_approved": True},
        allow_write=True,
        allow_run=False,
    )
    assert r is None


def test_planning_strict_allows_scan_repo_without_plan():
    import agent_loop as al

    cfg = {"planning_strict_mode": True}

    r = al._maybe_planning_strict_refusal(
        "scan_repo",
        cfg,
        {"plan_approved": False},
        allow_write=True,
        allow_run=False,
    )
    assert r is None


def test_planning_strict_off_allows_write():
    import agent_loop as al

    cfg = {"planning_strict_mode": False}

    r = al._maybe_planning_strict_refusal(
        "write_file",
        cfg,
        {"plan_approved": False},
        allow_write=True,
        allow_run=False,
    )
    assert r is None

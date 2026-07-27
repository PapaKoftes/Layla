"""Behavioral self-analysis for self-improvement proposals (PLAN item 23).

generate_proposals used to return three fixed canned strings. It now MINES the telemetry the
system already records and emits proposals that name a specific tool/effect WITH the numbers
behind it. These tests plant synthetic telemetry and prove the output references that planted
data — i.e. it analyses real signals rather than reciting constants.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _seed_tool_calls(tool_name: str, failures: int, successes: int, error_code: str) -> None:
    from layla.memory.db_connection import _conn

    with _conn() as db:
        for _ in range(failures):
            db.execute(
                "INSERT INTO tool_calls (run_id, tool_name, result_ok, error_code, duration_ms, created_at)"
                " VALUES (?,?,?,?,?,?)",
                ("r1", tool_name, 0, error_code, 5, _now_iso()),
            )
        for _ in range(successes):
            db.execute(
                "INSERT INTO tool_calls (run_id, tool_name, result_ok, error_code, duration_ms, created_at)"
                " VALUES (?,?,?,?,?,?)",
                ("r1", tool_name, 1, "", 5, _now_iso()),
            )
        db.commit()


def test_tool_failure_proposal_names_tool_with_evidence(isolated_db):
    """A planted failing tool must surface a proposal that names it and carries its exact count."""
    from services.infrastructure.self_improvement import generate_proposals

    _seed_tool_calls("read_file", failures=5, successes=1, error_code="not_found")

    out = generate_proposals()
    assert out["ok"] is True
    assert out["count_created"] >= 1

    tool_props = [p for p in out["created"] if p.get("signal") == "tool_failure"]
    assert tool_props, "expected a tool_failure proposal from the planted telemetry"
    prop = next(p for p in tool_props if p["subject"] == "read_file")

    # Evidence is real, not canned: the exact planted numbers are carried through.
    assert prop["evidence"]["failures"] == 5
    assert prop["evidence"]["calls"] == 6
    assert prop["evidence"]["top_error"] == "not_found"
    # The specific tool is named in the human-facing title + action.
    assert "read_file" in prop["title"]
    assert "5/6" in prop["title"]
    assert "read_file" in prop["action"]

    # And the old canned advice is gone.
    titles = " ".join(p["title"].lower() for p in out["created"])
    assert "enable output quality gate" not in titles

    # Evidence is durably persisted in the stored row's instructions payload.
    from services.infrastructure.self_improvement import list_proposals

    stored = list_proposals(status="pending")["proposals"]
    row = next(r for r in stored if "read_file" in (r.get("title") or ""))
    instr = json.loads(row["instructions"])
    assert instr["signal"] == "tool_failure"
    assert instr["subject"] == "read_file"
    assert instr["evidence"]["failures"] == 5


def test_liveness_zero_proposal_names_effect(isolated_db):
    """An effect stuck at 0 while others fire is a real, evidence-backed proposal."""
    from services.infrastructure.self_improvement import generate_proposals
    from services.observability import liveness

    # Baseline activity: one known effect fires, so the registry is demonstrably live.
    for _ in range(3):
        liveness.fire("turn_committed")
    # 'tool_executed' deliberately never fires — the codebase's signature defect.

    out = generate_proposals()
    live_props = [p for p in out["created"] if p.get("signal") == "liveness_zero"]
    assert live_props, "expected a liveness_zero proposal"

    prop = next(p for p in live_props if p["subject"] == "tool_executed")
    assert prop["evidence"]["count"] == 0
    assert "turn_committed" in prop["evidence"]["baseline_active_effects"]
    assert prop["evidence"]["baseline_active_count"] == 1
    assert "tool_executed" in prop["title"]
    assert "liveness.fire('tool_executed')" in prop["action"]


def test_empty_telemetry_returns_not_enough_data(isolated_db):
    """A fresh install with no telemetry must return an honest result, not fabricated proposals."""
    from services.infrastructure.self_improvement import generate_proposals, list_proposals

    out = generate_proposals()
    assert out["ok"] is True
    assert out["count_created"] == 0
    assert out["created"] == []
    assert out["reason"] == "not_enough_data"
    # Nothing was persisted.
    assert list_proposals()["proposals"] == []


def test_storage_and_approval_roundtrip(isolated_db):
    """Generation changed, but the existing storage/approval flow still round-trips."""
    from services.infrastructure.self_improvement import (
        approve_batch,
        generate_proposals,
        list_proposals,
    )

    _seed_tool_calls("run_shell", failures=4, successes=0, error_code="timeout")

    gen = generate_proposals()
    assert gen["count_created"] >= 1

    pending = list_proposals(status="pending")["proposals"]
    assert pending
    ids = [int(p["id"]) for p in pending]

    res = approve_batch(ids)
    assert res["ok"] is True

    approved = list_proposals(status="approved")["proposals"]
    approved_ids = {int(p["id"]) for p in approved}
    assert set(ids).issubset(approved_ids)


def test_caller_supplied_failures_still_produce_a_proposal(isolated_db):
    """recent_failures passed through the API is a real signal (keeps the legacy contract)."""
    from services.infrastructure.self_improvement import generate_proposals

    out = generate_proposals(recent_failures=["boom", "kaboom"])
    assert out["count_created"] >= 1
    rf = [p for p in out["created"] if p.get("signal") == "recent_failures"]
    assert rf
    assert rf[0]["evidence"]["count"] == 2

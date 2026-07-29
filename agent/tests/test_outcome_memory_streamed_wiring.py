"""Streamed-path outcome-reinforcement wiring.

reinforce_learning (of the learnings a run RETRIEVED and used), golden-example accumulation,
tool-success patterns and reflection all live in outcome_writer._save_outcome_memory, whose sole
caller is run_finalizer's `status == "finished"` block. A streamed turn is "stream_pending" at
that gate and returns early, so on the default streamed UI none of that reinforcement ran.

commit_turn is the turn boundary that runs on BOTH paths, so it now drives _save_outcome_memory on
a resolved-status copy for the streamed case, and skips (via the `outcome_memory_saved` flag) when
run_finalizer already ran it on the non-streamed path.

Teeth: delete the step-3b outcome-memory block in commit_turn and
test_streamed_turn_invokes_outcome_memory fails at the status/used_learning_ids assertions —
proving the seam wiring, not a tautology.
"""
from __future__ import annotations

import threading

import runtime_safety
import services.agent.turn_commit as tc
import services.infrastructure.outcome_writer as ow


def _quiet_cfg(monkeypatch, tmp_path):
    base = dict(runtime_safety.load_config() or {})
    base.update(
        {
            "operator_memory_llm_enabled": False,
            "identity_capture_enabled": False,
            "conversation_title_synthesis_enabled": False,
            "skill_acquisition_enabled": False,
            "emotional_presence_enabled": False,
        }
    )
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))  # never the operator DB


def _join(name: str) -> None:
    for t in threading.enumerate():
        if t.name == name:
            t.join(timeout=5)


def test_streamed_turn_invokes_outcome_memory(monkeypatch, tmp_path):
    """A streamed turn (status 'stream_pending' at run_finalizer) still reinforces its learnings:
    commit_turn resolves the status and drives _save_outcome_memory with the used_learning_ids."""
    _quiet_cfg(monkeypatch, tmp_path)

    seen: dict = {}

    def _spy(state):
        seen["status"] = state.get("status")
        seen["used"] = list(state.get("used_learning_ids") or [])

    monkeypatch.setattr(ow, "_save_outcome_memory", _spy)

    state = {
        "status": "stream_pending",  # orchestrator returned before the answer existed
        "steps": [
            {"action": "read_file", "args": {"path": "x"}, "result": {"ok": True, "path": "x"}}
        ],
        "used_learning_ids": [7, 9],
        "outcome_evaluation": {"success": True, "score": 0.9},
        "original_goal": "read the file",
    }
    tc.commit_turn(
        "conv-om", "read the file", "done",
        aspect_id="morrigan", status="finished", state=state,
    )
    _join("outcome-memory")

    assert seen.get("status") == "finished", "streamed turn must resolve status before reinforcing"
    assert seen.get("used") == [7, 9], "used_learning_ids must reach _save_outcome_memory"
    assert state.get("outcome_memory_saved") is True


def test_nonstreamed_turn_does_not_double_run(monkeypatch, tmp_path):
    """When run_finalizer already ran outcome memory (flag set), commit_turn must not re-run it."""
    _quiet_cfg(monkeypatch, tmp_path)

    calls: list = []
    monkeypatch.setattr(ow, "_save_outcome_memory", lambda state: calls.append(1))

    state = {
        "status": "finished",
        "steps": [],
        "outcome_evaluation": {"success": True, "score": 0.9},
        "outcome_memory_saved": True,  # run_finalizer already claimed it on the non-streamed path
    }
    tc.commit_turn(
        "conv-om2", "some substantive goal here", "done",
        aspect_id="morrigan", status="finished", state=state,
    )
    _join("outcome-memory")

    assert calls == [], "commit_turn must not re-run outcome memory when run_finalizer already did"

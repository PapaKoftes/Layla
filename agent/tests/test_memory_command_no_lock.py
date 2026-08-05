"""Stress-test finding (2026-08-05): a `remember:` /agent turn held the single LLM generation
serialize lock for the whole turn even though memory commands never generate — so a save waited
behind an in-flight multi-minute chat turn and 8 concurrent saves serialized (9/20 timed out).
Fix: agent_loop.autonomous_run detects memory commands BEFORE acquiring the lock. These tests lock
that in: a memory command must NOT take the generation lock; a normal turn still must."""
import sys
from pathlib import Path
from unittest.mock import patch

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import agent_loop  # noqa: E402


class _RecCM:
    """Context manager that records whether it was entered."""
    def __init__(self, flag):
        self.flag = flag
    def __enter__(self):
        self.flag["entered"] = True
        return self
    def __exit__(self, *a):
        return False


def _run(goal, mem_result):
    lock_flag = {"entered": False}
    impl_flag = {"called": False}

    def _fake_impl(*a, **k):
        impl_flag["called"] = True
        return {"status": "finished", "steps": []}

    with patch.object(agent_loop, "_autonomous_run_serialize_lock", lambda ws: _RecCM(lock_flag)), \
         patch.object(agent_loop, "schedule_slot", lambda **k: _RecCM({"x": False})), \
         patch.object(agent_loop, "_autonomous_run_impl", _fake_impl), \
         patch("services.infrastructure.pre_loop_setup.check_memory_command", return_value=mem_result):
        out = agent_loop.autonomous_run(goal, conversation_id="t-nolock")
    return out, lock_flag["entered"], impl_flag["called"]


def test_memory_command_does_not_take_the_generation_lock():
    sentinel = {"status": "finished", "steps": [{"action": "memory_command", "result": "Stored: x"}]}
    out, lock_entered, impl_called = _run("remember: tabs over spaces", sentinel)
    assert out is sentinel, "the memory-command state must be returned as-is"
    assert lock_entered is False, "a memory command must NOT acquire the generation serialize lock"
    assert impl_called is False, "a memory command must NOT enter the locked turn impl"


def test_normal_turn_still_takes_the_generation_lock():
    out, lock_entered, impl_called = _run("what is a hash map?", None)  # None → not a memory command
    assert lock_entered is True, "a normal turn must still serialize on the generation lock"
    assert impl_called is True, "a normal turn must run the locked turn impl"

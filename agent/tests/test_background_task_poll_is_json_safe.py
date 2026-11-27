"""Polling a finished background task returns JSON even though run state holds a set.

Live: GET /agent/tasks/{id} raised "Object of type set is not JSON serializable" (the state's
_recent_exact_calls) -> 500 on every poll, so a finished task could never be read back.
"""
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_finished_task_with_set_in_state_polls_as_json(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from services.infrastructure import agent_task_runner as atr

    tid = "t-json-safe-1"
    task = {"id": tid, "status": "done", "result": "done", "progress_events": [],
            "state": {"_recent_exact_calls": {"read_file:a", "list_dir:/"}, "steps": []}}
    with pytest_lock(atr):
        atr._TASKS[tid] = task
    try:
        with TestClient(main.app) as c:
            r = c.get(f"/agent/tasks/{tid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["task"]["status"] == "done"
        assert sorted(body["task"]["state"]["_recent_exact_calls"]) == ["list_dir:/", "read_file:a"]
        json.dumps(body)
    finally:
        atr._TASKS.pop(tid, None)


class pytest_lock:  # noqa: N801 — tiny context manager around the runner's task lock
    def __init__(self, atr):
        self._l = atr._TASKS_LOCK

    def __enter__(self):
        self._l.acquire()

    def __exit__(self, *a):
        self._l.release()

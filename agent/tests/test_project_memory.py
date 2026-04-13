"""Workspace project_memory.json service + scan_repo / update_project_memory tools."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_merge_patch_caps_files():
    from services import project_memory as pm

    base = pm.empty_document("/tmp/x")
    base["files"] = {f"f{i}": {"size": 1} for i in range(5)}
    patch = {"files": {"new": {"size": 2}}}
    out = pm.merge_patch(base, patch, max_files=3, max_list=50)
    assert len(out["files"]) == 3


def test_save_and_load_roundtrip(tmp_path):
    from services import project_memory as pm

    root = tmp_path / "ws"
    root.mkdir()
    doc = pm.empty_document(str(root.resolve()))
    doc["todos"] = ["a", "b"]
    ok, err = pm.save_project_memory(root, doc)
    assert ok and not err
    loaded = pm.load_project_memory(root)
    assert loaded and loaded.get("todos") == ["a", "b"]
    assert (root / ".layla" / "project_memory.json").is_file()


def test_scan_repo_dry_run_and_write(tmp_path):
    from layla.tools.registry import scan_repo, set_effective_sandbox

    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("hello", encoding="utf-8")
    set_effective_sandbox(str(tmp_path))
    try:
        r0 = scan_repo(workspace_root=str(root), dry_run=True)
        assert r0.get("ok") is True
        assert r0.get("dry_run") is True
        assert not (root / ".layla" / "project_memory.json").is_file()

        r1 = scan_repo(workspace_root=str(root), dry_run=False)
        assert r1.get("ok") is True
        assert (root / ".layla" / "project_memory.json").is_file()
        data = json.loads((root / ".layla" / "project_memory.json").read_text(encoding="utf-8"))
        assert "README.md" in (data.get("files") or {})
    finally:
        set_effective_sandbox(None)


def test_update_project_memory_merges_plan(tmp_path):
    from layla.tools.registry import scan_repo, set_effective_sandbox, update_project_memory

    root = tmp_path / "r2"
    root.mkdir()
    set_effective_sandbox(str(tmp_path))
    try:
        scan_repo(workspace_root=str(root), dry_run=False)
        u = update_project_memory(
            workspace_root=str(root),
            patch={"plan": {"goal": "ship", "status": "ready", "steps": ["one", "two"]}},
        )
        assert u.get("ok") is True
        data = json.loads((root / ".layla" / "project_memory.json").read_text(encoding="utf-8"))
        assert (data.get("plan") or {}).get("goal") == "ship"
    finally:
        set_effective_sandbox(None)


def test_continuous_background_respects_max_iterations(monkeypatch, tmp_path):
    import agent_loop
    import layla.memory.db as db_mod
    from layla.tools.registry import set_effective_sandbox
    from services import agent_task_runner as atr

    monkeypatch.setattr(db_mod, "update_background_task", lambda *a, **k: None)

    calls: list[int] = []

    def fake_run(*_a, **_k):
        calls.append(1)
        return {
            "status": "finished",
            "response": f"iter{len(calls)}",
            "steps": [{"kind": "x", "result": "ok"}],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
        }

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_run)

    set_effective_sandbox(str(tmp_path))
    try:
        tid = "test-cont-max"
        cancel_ev = threading.Event()
        with atr._TASKS_LOCK:
            atr._TASKS[tid] = {
                "task_id": tid,
                "status": "queued",
                "progress_events": [],
                "progress_json": "[]",
            }
        payload = {
            "goal": "g",
            "workspace_root": str(tmp_path),
            "allow_write": False,
            "allow_run": False,
            "aspect_id": "morrigan",
            "continuous": True,
            "max_iterations": 4,
            "iteration_delay_seconds": 0,
            "_cancel_event": cancel_ev,
            "_schedule_priority": 2,
        }
        atr._run_background_task(tid, payload)
        assert len(calls) == 4
        with atr._TASKS_LOCK:
            st = atr._TASKS.get(tid) or {}
        assert st.get("status") == "done"
        state = st.get("state") or {}
        assert state.get("continuous_iterations") == 4
    finally:
        with atr._TASKS_LOCK:
            atr._TASKS.pop("test-cont-max", None)
        set_effective_sandbox(None)


def test_continuous_background_stops_on_plan_done(monkeypatch, tmp_path):
    import agent_loop
    import layla.memory.db as db_mod
    from layla.tools.registry import set_effective_sandbox
    from services import agent_task_runner as atr
    from services import project_memory as pm

    monkeypatch.setattr(db_mod, "update_background_task", lambda *a, **k: None)

    calls: list[int] = []

    def fake_run(*_a, **_k):
        calls.append(1)
        return {
            "status": "finished",
            "response": "once",
            "steps": [],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
        }

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_run)

    root = tmp_path / "ws"
    root.mkdir()
    doc = pm.empty_document(str(root.resolve()))
    doc["plan"] = {**doc["plan"], "status": "done", "goal": "x"}
    pm.save_project_memory(root, doc)

    set_effective_sandbox(str(tmp_path))
    try:
        tid = "test-cont-plan"
        cancel_ev = threading.Event()
        with atr._TASKS_LOCK:
            atr._TASKS[tid] = {
                "task_id": tid,
                "status": "queued",
                "progress_events": [],
                "progress_json": "[]",
            }
        payload = {
            "goal": "g",
            "workspace_root": str(root),
            "allow_write": False,
            "allow_run": False,
            "aspect_id": "morrigan",
            "continuous": True,
            "max_iterations": 20,
            "iteration_delay_seconds": 0,
            "_cancel_event": cancel_ev,
            "_schedule_priority": 2,
        }
        atr._run_background_task(tid, payload)
        assert len(calls) == 1
        with atr._TASKS_LOCK:
            atr._TASKS.pop("test-cont-plan", None)
    finally:
        set_effective_sandbox(None)

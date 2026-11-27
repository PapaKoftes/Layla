"""The per-request workspace-awareness refresh never runs the model.

It ran LLM project discovery (a 400-token completion) after every /agent request and discarded the
result, holding the model lock so the operator's next turn waited (live: "project_discovery timed out").
"""
import sys
import threading
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_background_refresh_scans_and_indexes_but_runs_no_model(monkeypatch, tmp_path):
    import layla.tools.registry as reg
    import services.workspace.project_discovery as pd
    import services.workspace.workspace_index as wi
    from services.workspace import workspace_awareness as wa

    ran = {"discovery": 0, "scan": 0, "index": 0}
    monkeypatch.setattr(pd, "run_project_discovery", lambda: ran.__setitem__("discovery", ran["discovery"] + 1))
    monkeypatch.setattr(reg, "scan_repo", lambda **k: ran.__setitem__("scan", ran["scan"] + 1))
    monkeypatch.setattr(wi, "index_workspace", lambda root: ran.__setitem__("index", ran["index"] + 1))
    monkeypatch.setattr(wa, "_last_scheduled", {})

    class _SyncThread:
        def __init__(self, target=None, **k):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr(threading, "Thread", _SyncThread)
    wa.refresh_for_workspace(str(tmp_path), {"workspace_awareness_auto_enabled": True})

    assert ran["scan"] == 1 and ran["index"] == 1, f"PROBE BROKEN: the job did not run: {ran}"
    assert ran["discovery"] == 0, ran

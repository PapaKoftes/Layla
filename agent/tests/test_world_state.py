"""BL-241: world state model — unified snapshot with best-effort degradation."""
from __future__ import annotations

from services.workspace import world_state as ws


def test_snapshot_aggregates(monkeypatch):
    monkeypatch.setattr(ws, "_current_project", lambda: {
        "project_name": "Layla", "lifecycle_stage": "build", "goals": "ship",
        "progress": "80%", "blockers": "none", "domains": ["ai"],
    })
    monkeypatch.setattr(ws, "_projects", lambda: [{"name": "Layla", "workspace_root": "/w"}])
    monkeypatch.setattr(ws, "_repo_index", lambda: {"files": 10, "symbols": 200, "imports": 5, "calls": 30})
    monkeypatch.setattr(ws, "_hardware", lambda: {"cpu_logical": 8, "ram_gb": 32.0, "gpu_name": "RTX"})
    monkeypatch.setattr(ws, "_governor", lambda: "sprint")

    s = ws.snapshot()
    assert s["current_project"]["name"] == "Layla"
    assert s["projects"][0]["name"] == "Layla"
    assert s["repo_index"]["symbols"] == 200
    assert s["hardware"]["ram_gb"] == 32.0
    assert s["resource_mode"] == "sprint"


def test_source_failure_degrades_gracefully(monkeypatch):
    def _boom():
        raise RuntimeError("probe down")
    monkeypatch.setattr(ws, "_hardware", _boom)
    monkeypatch.setattr(ws, "_repo_index", _boom)
    monkeypatch.setattr(ws, "_current_project", lambda: {"project_name": "X"})
    monkeypatch.setattr(ws, "_projects", lambda: [])
    monkeypatch.setattr(ws, "_governor", lambda: "breathe")

    s = ws.snapshot()
    assert s["hardware"] == {}                               # degraded default
    assert s["repo_index"] == {"files": 0, "symbols": 0, "imports": 0, "calls": 0}
    assert s["current_project"]["name"] == "X"               # other sources still populate


def test_summary_is_readable(monkeypatch):
    monkeypatch.setattr(ws, "_current_project", lambda: {"project_name": "Layla", "lifecycle_stage": "build", "blockers": "none"})
    monkeypatch.setattr(ws, "_projects", lambda: [{"name": "a"}, {"name": "b"}])
    monkeypatch.setattr(ws, "_repo_index", lambda: {"files": 12, "symbols": 99})
    monkeypatch.setattr(ws, "_hardware", lambda: {"cpu_logical": 8, "ram_gb": 16.0})
    monkeypatch.setattr(ws, "_governor", lambda: "sprint")

    text = ws.summarize()
    assert "Project: Layla [build]" in text
    assert "2 known project(s)" in text
    assert "12 files" in text and "Mode: sprint" in text

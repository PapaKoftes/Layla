from pathlib import Path

from services import project_discovery_hooks as pdh


def test_workspace_memory_is_sparse_no_file(tmp_path: Path):
    assert pdh.workspace_memory_is_sparse(tmp_path) is True


def test_build_workspace_discovery_brief_disabled(tmp_path: Path):
    assert pdh.build_workspace_discovery_brief(str(tmp_path), {}) == ""
    assert pdh.build_workspace_discovery_brief(str(tmp_path), {"project_discovery_auto_inject": False}) == ""


def test_build_workspace_discovery_brief_outside_sandbox(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("layla.tools.registry.inside_sandbox", lambda p: False)
    assert pdh.build_workspace_discovery_brief(str(tmp_path), {"project_discovery_auto_inject": True}) == ""

"""Workspace-scoped default for auto_lint_test_fix_ruff_fix (Layla repo tree only)."""
from __future__ import annotations

from pathlib import Path

import runtime_safety as rs


def test_effective_ruff_fix_explicit_bool_wins():
    assert rs.effective_auto_lint_test_fix_ruff_fix({"auto_lint_test_fix_ruff_fix": False}, str(rs.REPO_ROOT)) is False
    assert rs.effective_auto_lint_test_fix_ruff_fix({"auto_lint_test_fix_ruff_fix": True}, "/nope") is True


def test_effective_ruff_fix_default_uses_repo_tree(tmp_path: Path, monkeypatch):
    """When key is absent, only workspaces under REPO_ROOT get automatic ruff --fix."""
    outside = tmp_path / "other"
    outside.mkdir()
    assert rs.workspace_under_layla_repository(str(outside)) is False
    assert rs.effective_auto_lint_test_fix_ruff_fix({}, str(outside)) is False
    # Agent package lives under REPO_ROOT; any subpath of repo should match
    assert rs.workspace_under_layla_repository(str(rs.AGENT_DIR)) is True
    assert rs.effective_auto_lint_test_fix_ruff_fix({}, str(rs.AGENT_DIR)) is True

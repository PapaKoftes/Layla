"""git_worktree_add / git_worktree_remove — sandbox + real git (when available)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _have_git() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_git_worktree_add_remove_roundtrip(tmp_path, monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"sandbox_root": str(tmp_path)})
    repo = tmp_path / "mainrepo"
    repo.mkdir()
    wt_path = tmp_path / "wt-side"
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.st"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    from layla.tools.registry import git_worktree_add, git_worktree_remove

    r = git_worktree_add(str(repo), str(wt_path))
    assert r.get("ok") is True
    assert Path(r.get("path", "")).is_dir()
    r2 = git_worktree_remove(str(repo), str(wt_path))
    assert r2.get("ok") is True

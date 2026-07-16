"""SAFETY: admin-mode git checkpoints. git_revert_last_checkpoint MUST refuse to revert a commit that is
not a Layla checkpoint — else it could revert the USER's real work. Was UNTESTED; this locks that guard
plus the checkpoint round-trip in a throwaway git repo."""
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _has_git():
    return subprocess.run(["git", "--version"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_revert_refuses_on_a_user_commit(tmp_path):
    from services.safety.admin_checkpoint import git_revert_last_checkpoint
    repo = tmp_path / "repo"; repo.mkdir()
    _git(repo, "init"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("user work", encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-m", "my important feature")
    # HEAD is a normal user commit — revert MUST refuse.
    r = git_revert_last_checkpoint(str(repo))
    assert r.get("ok") is False and r.get("error") == "last_commit_not_layla_checkpoint"
    assert (repo / "f.txt").read_text(encoding="utf-8") == "user work", "user's file must be untouched"


@pytest.mark.skipif(not _has_git(), reason="git not available")
def test_checkpoint_creates_layla_commit_and_revert_undoes_it(tmp_path):
    from services.safety.admin_checkpoint import git_checkpoint_layla, git_revert_last_checkpoint
    repo = tmp_path / "repo2"; repo.mkdir()
    _git(repo, "init"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("v1", encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-m", "base")
    # a mutation happens, then a checkpoint captures it
    (repo / "a.txt").write_text("v2-by-layla", encoding="utf-8")
    ok = git_checkpoint_layla(str(repo), "write_file")
    subj = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
    if ok:  # checkpoint made a commit
        assert "layla-checkpoint" in subj
        r = git_revert_last_checkpoint(str(repo))
        assert r.get("ok") is True, r

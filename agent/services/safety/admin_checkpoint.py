"""Optional git checkpoint before mutating tools when admin_mode is on."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("layla")


def git_checkpoint_layla(workspace: str, tool_name: str, detail: str = "") -> bool:
    """
    If ``workspace`` is inside a git repo, create a checkpoint commit (best effort).
    """
    ws = (workspace or "").strip()
    if not ws:
        return False
    root = Path(ws).expanduser().resolve()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return False
        top = Path(r.stdout.strip())
        msg = f"layla-checkpoint: before {tool_name}"
        if detail:
            msg += f" ({detail[:120]})"
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(top),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        c = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", msg],
            cwd=str(top),
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr).lower():
            logger.debug("admin_checkpoint: commit: %s", (c.stderr or c.stdout)[:200])
        return True
    except Exception as e:
        logger.debug("admin_checkpoint failed: %s", e)
        return False


def git_revert_last_checkpoint(workspace: str) -> dict:
    """
    If the latest commit message looks like a Layla admin checkpoint, run ``git revert HEAD --no-edit``.
    """
    ws = (workspace or "").strip()
    if not ws:
        return {"ok": False, "error": "workspace_required"}
    root = Path(ws).expanduser().resolve()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return {"ok": False, "error": "not_a_git_repo"}
        top = Path(r.stdout.strip())
        subj = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=str(top),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if subj.returncode != 0:
            return {"ok": False, "error": "git_log_failed"}
        line = (subj.stdout or "").strip().lower()
        if "layla-checkpoint" not in line:
            return {"ok": False, "error": "last_commit_not_layla_checkpoint", "subject": subj.stdout.strip()}
        rv = subprocess.run(
            ["git", "revert", "HEAD", "--no-edit"],
            cwd=str(top),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if rv.returncode != 0:
            return {
                "ok": False,
                "error": "revert_failed",
                "stderr": (rv.stderr or rv.stdout or "")[:2000],
            }
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

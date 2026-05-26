"""Git worktree helpers for isolated parallel execution (optional)."""
from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger("layla")


def create_worktree(repo_root: str, branch_name: str | None = None) -> Path:
    root = Path(str(repo_root).strip()).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"repo_root not a directory: {root}")
    br = (branch_name or f"layla-wt-{uuid.uuid4().hex[:10]}").strip()
    wt_dir = root.parent / ".layla_worktrees" / br.replace("/", "_")
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    if wt_dir.exists():
        raise FileExistsError(str(wt_dir))
    subprocess.run(
        ["git", "worktree", "add", str(wt_dir), "-b", br],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return wt_dir


def cleanup_worktree(worktree_path: str | Path) -> None:
    p = Path(str(worktree_path)).expanduser().resolve()
    if not p.exists():
        return
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(p)],
            cwd=str(p),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:
        logger.warning("worktree remove failed: %s", e)

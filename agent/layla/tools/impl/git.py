"""Tool implementations — domain: git."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def git_status(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "status"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": result.stdout or ""}

def git_diff(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "diff"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "")[:8000]}

def git_log(repo: str, n: int = 10) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "log", "--oneline", f"-{n}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "")[:4000]}

def git_branch(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "").strip()}

def git_add(repo: str, path: str = ".") -> dict:
    """Stage files for commit. path: file or '.' for all."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "add", path],
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": result.stdout or result.stderr or ""}

def git_commit(repo: str, message: str, add_all: bool = False) -> dict:
    """Commit staged changes. If add_all=True, stages everything first."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    if add_all:
        subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_push(repo: str, remote: str = "origin", branch: str = "") -> dict:
    """Push commits to remote. branch: empty = current branch."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    argv = ["git", "push", remote]
    if branch:
        argv.append(branch)
    result = subprocess.run(
        argv,
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_pull(repo: str, remote: str = "origin", branch: str = "") -> dict:
    """Pull from remote. branch: empty = current branch."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    argv = ["git", "pull", remote]
    if branch:
        argv.append(branch)
    result = subprocess.run(
        argv,
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_stash(repo: str, action: str = "list", message: str = "") -> dict:
    """Stash changes. action: list|push|pop|apply."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    if action == "list":
        argv = ["git", "stash", "list"]
    elif action == "push":
        argv = ["git", "stash", "push", "-m", message or "layla stash"]
    elif action in ("pop", "apply"):
        argv = ["git", "stash", action]
    else:
        return {"ok": False, "error": f"Unknown action: {action}. Use list|push|pop|apply"}
    result = subprocess.run(
        argv,
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_revert(repo: str, commit: str, no_commit: bool = False) -> dict:
    """Revert a commit. commit: hash or HEAD~1. no_commit=True leaves changes staged."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    argv = ["git", "revert", "--no-edit", commit]
    if no_commit:
        argv.append("--no-commit")
    result = subprocess.run(
        argv,
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_clone(url: str, dest: str, depth: int = 0) -> dict:
    """Clone a git repo. dest: path inside sandbox. depth: 0 = full clone."""
    dest_path = Path(dest)
    if not inside_sandbox(dest_path):
        return {"ok": False, "error": "Destination outside sandbox"}
    argv = ["git", "clone", url, str(dest_path)]
    if depth:
        argv.insert(2, f"--depth={depth}")
    result = subprocess.run(
        argv,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}

def git_worktree_add(repo: str, path: str, branch: str = "", new_branch: str = "") -> dict:
    """Add a git worktree at path (sandboxed). branch: existing ref to checkout; if empty, default branch tip. new_branch: if set, create and checkout new branch at path (optional start ref in branch)."""
    repo_path = Path(repo).resolve()
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Repo outside sandbox"}
    wt = Path(path).expanduser().resolve()
    if not inside_sandbox(wt):
        return {"ok": False, "error": "Worktree path outside sandbox"}
    try:
        wt.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    nb = (new_branch or "").strip()
    br = (branch or "").strip()
    if nb:
        argv = ["git", "-C", str(repo_path), "worktree", "add", "-b", nb, str(wt)]
        if br:
            argv.append(br)
    else:
        argv = ["git", "-C", str(repo_path), "worktree", "add", str(wt)]
        if br:
            argv.append(br)
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return {
        "ok": result.returncode == 0,
        "path": str(wt),
        "output": (result.stdout or result.stderr or "")[:4000],
    }

def git_worktree_remove(repo: str, path: str, force: bool = False) -> dict:
    """Remove a git worktree directory registration (path must match an existing worktree)."""
    repo_path = Path(repo).resolve()
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Repo outside sandbox"}
    wt = Path(path).expanduser().resolve()
    if not inside_sandbox(wt):
        return {"ok": False, "error": "Worktree path outside sandbox"}
    argv = ["git", "-C", str(repo_path), "worktree", "remove", str(wt)]
    if force:
        argv.append("--force")
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:4000]}

def git_blame(repo: str, file_path: str, line_start: int = 1, line_end: int = 0) -> dict:
    """Run git blame on a file. Returns per-line author, commit hash, date, content."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    cmd = ["git", "blame", "--line-porcelain"]
    if line_end > 0:
        cmd += [f"-L{line_start},{line_end}"]
    cmd.append(file_path)
    try:
        r = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()[:500]}
        lines, current = [], {}
        for line in r.stdout.splitlines():
            if line.startswith("\t"):
                current["content"] = line[1:]
                lines.append(current)
                current = {}
            elif " " in line:
                k, v = line.split(" ", 1)
                if k in ("author", "summary"):
                    current[k] = v
                elif k == "author-time":
                    import datetime as _dt
                    current["date"] = str(_dt.datetime.utcfromtimestamp(int(v)))[:10]
                elif len(k) == 40:
                    current["commit"] = k[:8]
        return {"ok": True, "file": file_path, "lines": lines[:200], "total_lines": len(lines)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


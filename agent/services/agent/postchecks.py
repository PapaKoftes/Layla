"""Post-write hook helpers extracted from agent_loop.py.

Functions
---------
_run_git_auto_commit   -- auto git-commit after write_file / apply_patch
_run_auto_lint_test_fix -- lint (+ optional test) after mutating tools
_edit_tool_lint_path    -- filesystem path hint for the lint hook
"""

import logging
from pathlib import Path

import runtime_safety
from layla.tools.registry import TOOLS

logger = logging.getLogger("layla")


def _run_git_auto_commit(tool_name: str, result: dict, path: str, workspace: str) -> None:
    """
    After write_file or apply_patch succeeds, optionally auto-commit.
    Config: git_auto_commit. Stores last commit for /undo.
    """
    try:
        cfg = runtime_safety.load_config()
        if not cfg.get("git_auto_commit", False):
            return
        if not result.get("ok") or not workspace:
            return
        repo = str(Path(workspace).expanduser().resolve())
        # Resolve path relative to repo for git add
        p = Path(path) if path else None
        if p and not p.is_absolute():
            add_path = str(p)
        elif p:
            try:
                add_path = str(p.relative_to(repo))
            except ValueError:
                add_path = "."
        else:
            add_path = "."
        add_res = TOOLS["git_add"]["fn"](repo=repo, path=add_path)
        if not add_res.get("ok"):
            logger.debug("git_auto_commit: git_add failed: %s", add_res.get("output"))
            return
        msg = "fix: apply changes from Layla"
        commit_res = TOOLS["git_commit"]["fn"](repo=repo, message=msg, add_all=False)
        if not commit_res.get("ok"):
            logger.debug("git_auto_commit: git_commit failed: %s", commit_res.get("output"))
            return
        # Get new commit hash
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            from shared_state import set_last_layla_commit
            set_last_layla_commit(repo, r.stdout.strip())
    except Exception as e:
        logger.debug("git_auto_commit failed: %s", e)


def _run_auto_lint_test_fix(state: dict, tool_name: str, result: dict, path: str, workspace: str) -> str | None:
    """
    Post-write hook: run code_lint (and optionally run_tests) on changed path.
    If issues found, return hint string to inject into goal for retry. Cap at 3 iterations.
    """
    try:
        cfg = runtime_safety.load_config()
        if not cfg.get("auto_lint_test_fix", False):
            return None
        iters = state.get("lint_test_fix_iterations", 0)
        if iters >= 3:
            return None
        if not path or not workspace:
            return None
        state["lint_test_fix_iterations"] = iters + 1
        lint_result = TOOLS["code_lint"]["fn"](path=path, fix=False)
        if not isinstance(lint_result, dict) or not lint_result.get("ok"):
            return None
        violations = lint_result.get("violations", 0) or len(lint_result.get("details", []))
        if violations > 0 and runtime_safety.effective_auto_lint_test_fix_ruff_fix(cfg, workspace):
            try:
                TOOLS["code_lint"]["fn"](path=path, fix=True)
            except Exception as e:
                logger.debug("auto_lint ruff --fix: %s", e)
            lint_result = TOOLS["code_lint"]["fn"](path=path, fix=False)
            if not isinstance(lint_result, dict) or not lint_result.get("ok"):
                return None
            violations = lint_result.get("violations", 0) or len(lint_result.get("details", []))
        if violations > 0:
            details = lint_result.get("details", [])[:5]
            lines = [f"- {d.get('file','')}:{d.get('line','')} {d.get('code','')}: {d.get('message','')}" for d in details if isinstance(d, dict)]
            hint = f"[Lint found {violations} violation(s). Fix these and retry:\n" + "\n".join(lines) + "]"
            return hint
        if cfg.get("auto_lint_test_fix_run_tests", False):
            test_result = TOOLS["run_tests"]["fn"](cwd=workspace, pattern="", extra_args="-x -q", timeout_s=60)
            if isinstance(test_result, dict) and not test_result.get("ok") and test_result.get("failed", 0) > 0:
                out = (test_result.get("output") or "")[:500]
                return f"[Tests failed. Fix and retry:\n{out}]"
    except Exception as e:
        logger.debug("auto_lint_test_fix failed: %s", e)
    return None


def _edit_tool_lint_path(intent: str, args: dict | None, workspace: str) -> str:
    """Filesystem path hint for auto_lint_test_fix after mutating tools."""
    ws = (workspace or "").strip()
    a = args if isinstance(args, dict) else {}
    if intent in ("code_format", "notebook_edit_cell"):
        return str(a.get("path") or "").strip() or ws
    if intent == "replace_in_file":
        return str(a.get("path") or "").strip()
    if intent in ("search_replace", "rename_symbol"):
        return ws
    return ""

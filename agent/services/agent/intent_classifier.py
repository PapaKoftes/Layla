"""Heuristic intent classification and goal-text extraction helpers.

Extracted from agent_loop.py to keep the main loop file focused on
orchestration.  All four public functions preserve their original
signatures so call-sites need only update their import path.
"""

import logging
import shlex

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

def classify_intent(goal: str) -> str:
    """Lightweight heuristic tool intent for tests and legacy call sites (no external module)."""
    g = (goal or "").strip().lower()
    if not g:
        return "reason"
    if "list checkpoints" in g:
        return "list_file_checkpoints"
    if "restore checkpoint" in g or g.startswith("revert file"):
        return "restore_file_checkpoint"
    if "import chats" in g and "backup" in g:
        return "ingest_chat_export_to_knowledge"
    if "search past learnings" in g:
        return "memory_elasticsearch_search"
    if "git status" in g:
        return "git_status"
    if "git diff" in g:
        return "git_diff"
    if "git log" in g:
        return "git_log"
    if "current branch" in g:
        return "git_branch"
    if "list dir" in g or "what files are in" in g:
        return "list_dir"
    if "grep for" in g or "search code for" in g:
        return "grep_code"
    if "create file" in g or "save file as" in g:
        return "write_file"
    if g.startswith("read file") or g.startswith("show file") or g.startswith("contents of"):
        return "read_file"
    if "explain" in g or "what do you think" in g:
        return "reason"
    return "reason"


# ---------------------------------------------------------------------------
# Goal-text extraction helpers
# ---------------------------------------------------------------------------

def _extract_path(goal: str) -> str:
    """Pull a file/dir path from the goal text (very simple heuristic)."""
    words = goal.split()
    for w in words:
        if (":" in w or "/" in w or "\\" in w) and not w.startswith("http"):
            return w.strip("\"',")
    return ""


def _extract_file_and_content(goal: str):
    if "with content" in goal:
        parts = goal.split("with content", 1)
        left = parts[0]
        content = parts[1].strip()
        words = left.split()
        for w in words:
            ww = w.strip("\"',")
            if not ww or ww.lower().startswith("http"):
                continue
            # Support Windows paths (C:\...), UNC (\\server\...), and POSIX absolute paths (/tmp/x).
            if ":" in ww or "\\" in ww or ww.startswith("/"):
                return ww, content
    return None, None


def _extract_shell_argv(goal: str):
    """Very simple: find a quoted command or treat the last part as the command."""
    try:
        # Try to find a quoted command block
        for delim in ('"', "'"):
            if delim in goal:
                inner = goal.split(delim)[1]
                return shlex.split(inner)
    except Exception as _exc:
        logger.debug("agent_loop:L2413: %s", _exc, exc_info=False)
    # Fallback: strip common preambles
    for prefix in ("run", "execute", "install", "please run", "please execute"):
        if goal.lower().startswith(prefix):
            remainder = goal[len(prefix):].strip()
            try:
                return shlex.split(remainder)
            except Exception as e:
                logger.debug("shlex.split fallback for shell argv: %s", e, exc_info=True)
                return remainder.split()
    return goal.split()

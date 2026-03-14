"""
Decision engine. LLM decision parsing, intent classification.
Used by agent_loop for tool vs reason routing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")


def classify_intent(goal: str) -> str:
    """Classify user goal into tool intent or 'reason'."""
    g = goal.lower()
    if any(kw in g for kw in ("create file", "write file", "save file", "create a file")):
        return "write_file"
    if any(kw in g for kw in ("read file", "open file", "show file", "content of", "contents of")):
        return "read_file"
    if any(kw in g for kw in ("list dir", "list files", "list folder", "ls ", "show files", "what files")):
        return "list_dir"
    if any(kw in g for kw in ("git status",)):
        return "git_status"
    if any(kw in g for kw in ("git diff",)):
        return "git_diff"
    if any(kw in g for kw in ("git log",)):
        return "git_log"
    if any(kw in g for kw in ("git branch", "current branch")):
        return "git_branch"
    if any(kw in g for kw in ("grep ", "search code", "find in code", "grep_code")):
        return "grep_code"
    if any(kw in g for kw in ("glob ", "find files", "glob files")):
        return "glob_files"
    if any(kw in g for kw in ("run python", "execute python", "run script", "run_python")):
        return "run_python"
    if any(kw in g for kw in ("apply patch", "patch file", "apply_patch")):
        return "apply_patch"
    if any(kw in g for kw in ("fetch url", "fetch http", "browse ", "scrape ", "look up http", "fetch_url", "http://", "https://")):
        return "fetch_url"
    if any(kw in g for kw in ("web search", "search the web", "google ", "duckduckgo", "ddg_search")):
        return "ddg_search"
    if any(kw in g for kw in ("wikipedia", "wiki ", "look up on wiki")):
        return "wiki_search"
    if any(kw in g for kw in ("search memories", "recall ", "remember ", "what did i", "search_memories")):
        return "search_memories"
    if any(kw in g for kw in ("run ", "execute ", "install ", "npm ", "pip ", "python ", "bash ", "cmd ")):
        return "shell"
    return "reason"

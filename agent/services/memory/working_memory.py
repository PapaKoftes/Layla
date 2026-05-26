# -*- coding: utf-8 -*-
"""
working_memory.py -- Lightweight cross-session working memory.

Stores the current active context: what project is in progress, recent
facts the user stated this session, blockers, and next actions. Persists
to .layla/working_memory.json. Survives server restarts.

Auto-injected into the system prompt at session start so Layla always
knows where things were left off, without needing to re-read the full
conversation history.

Keys in working memory:
    active_project   -- what we're currently working on
    next_action      -- the single most important next step
    blockers         -- list of active blockers/open questions
    recent_facts     -- facts user stated this session (max 20, FIFO)
    last_updated     -- ISO timestamp

Auto-pruning: recent_facts capped at 20 entries. Blockers cleared when
user marks them resolved ("fixed", "resolved", "done with X").
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_AGENT_DIR = Path(__file__).resolve().parent.parent
_WM_PATH = _AGENT_DIR / ".layla" / "working_memory.json"
_MAX_FACTS = 20
_MAX_BLOCKERS = 10

_wm_lock = threading.Lock()
_cache: dict | None = None


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if _WM_PATH.exists():
            _cache = json.loads(_WM_PATH.read_text(encoding="utf-8"))
            return _cache
    except Exception as e:
        logger.debug("working_memory load failed: %s", e)
    _cache = _empty()
    return _cache


def _save(wm: dict) -> None:
    global _cache
    try:
        _WM_PATH.parent.mkdir(parents=True, exist_ok=True)
        wm["last_updated"] = datetime.now(timezone.utc).isoformat()
        _WM_PATH.write_text(json.dumps(wm, indent=2, ensure_ascii=False), encoding="utf-8")
        _cache = wm
    except Exception as e:
        logger.debug("working_memory save failed: %s", e)


def _empty() -> dict:
    return {
        "active_project": "",
        "next_action": "",
        "blockers": [],
        "recent_facts": [],
        "last_updated": "",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_working_memory() -> dict:
    """Return the current working memory dict."""
    with _wm_lock:
        return dict(_load())


def add_to_working_memory(fact: str) -> None:
    """Add a fact to recent_facts (FIFO, max 20)."""
    fact = (fact or "").strip()
    if not fact or len(fact) < 4:
        return
    with _wm_lock:
        wm = _load()
        facts = wm.get("recent_facts") or []
        # Dedup: skip if already present
        if fact not in facts:
            facts.append(fact)
        # FIFO cap
        wm["recent_facts"] = facts[-_MAX_FACTS:]
        _save(wm)


def set_active_project(project: str) -> None:
    """Set the active project name/description."""
    with _wm_lock:
        wm = _load()
        wm["active_project"] = (project or "").strip()[:200]
        _save(wm)


def set_next_action(action: str) -> None:
    """Set the single most important next action."""
    with _wm_lock:
        wm = _load()
        wm["next_action"] = (action or "").strip()[:200]
        _save(wm)


def add_blocker(blocker: str) -> None:
    """Add a blocker/open question."""
    blocker = (blocker or "").strip()
    if not blocker:
        return
    with _wm_lock:
        wm = _load()
        blockers = wm.get("blockers") or []
        if blocker not in blockers:
            blockers.append(blocker)
        wm["blockers"] = blockers[-_MAX_BLOCKERS:]
        _save(wm)


def clear_blocker(text: str) -> int:
    """Remove blockers containing text. Returns count removed."""
    text = (text or "").strip().lower()
    if not text:
        return 0
    with _wm_lock:
        wm = _load()
        before = list(wm.get("blockers") or [])
        after = [b for b in before if text not in b.lower()]
        wm["blockers"] = after
        _save(wm)
        return len(before) - len(after)


def reset() -> None:
    """Clear all working memory (fresh session)."""
    global _cache
    with _wm_lock:
        _save(_empty())
        _cache = None


def format_for_prompt() -> str:
    """
    Format working memory as a compact string for system prompt injection.
    Returns empty string if nothing meaningful is stored.
    """
    wm = get_working_memory()
    parts = []

    proj = (wm.get("active_project") or "").strip()
    if proj:
        parts.append(f"Active project: {proj}")

    nxt = (wm.get("next_action") or "").strip()
    if nxt:
        parts.append(f"Next action: {nxt}")

    blockers = [b for b in (wm.get("blockers") or []) if b]
    if blockers:
        parts.append("Blockers: " + "; ".join(blockers[:3]))

    facts = [f for f in (wm.get("recent_facts") or []) if f]
    if facts:
        # Only inject the most recent 5 facts to avoid bloating the prompt
        fact_lines = "\n".join(f"  - {f[:100]}" for f in facts[-5:])
        parts.append(f"Recent context:\n{fact_lines}")

    if not parts:
        return ""

    last = (wm.get("last_updated") or "").strip()
    header = f"[Working memory — last updated {last[:10]}]" if last else "[Working memory]"
    return header + "\n" + "\n".join(parts)


def auto_extract_from_message(message: str) -> None:
    """
    Lightweight heuristic extraction: detect project references and
    next-action statements from a user message and update working memory.
    Does NOT call the LLM -- pure pattern matching, best-effort.
    """
    msg = (message or "").strip()
    if not msg or len(msg) < 10:
        return

    import re
    # Detect "working on X" / "building X" / "fixing X" as active project
    proj_match = re.search(
        r"\b(?:working on|building|developing|fixing|refactoring|implementing)\s+(.{5,60}?)(?:[.,!?]|$)",
        msg, re.IGNORECASE,
    )
    if proj_match:
        candidate = proj_match.group(1).strip()
        if len(candidate) >= 5:
            set_active_project(candidate)

    # Detect "need to X" / "next step is X" as next action
    action_match = re.search(
        r"\b(?:need to|going to|next step|next is|will|should)\s+(.{5,80}?)(?:[.,!?]|$)",
        msg, re.IGNORECASE,
    )
    if action_match:
        candidate = action_match.group(1).strip()
        if len(candidate) >= 5:
            set_next_action(candidate)

    # Detect "blocked by X" / "stuck on X"
    blocker_match = re.search(
        r"\b(?:blocked by|stuck on|can't figure out|problem with|issue with)\s+(.{5,80}?)(?:[.,!?]|$)",
        msg, re.IGNORECASE,
    )
    if blocker_match:
        add_blocker(blocker_match.group(1).strip())

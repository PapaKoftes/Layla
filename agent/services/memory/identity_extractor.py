"""Deterministic, high-precision capture of durable facts the operator states about themselves.

Durable identity (name, timezone, pronouns, editor, OS, role) previously landed in
`user_identity` ONLY when the model chose to call update_user_identity_tool — unreliable, so
the "About you" memory panel stayed near-empty. This is a tiny, high-precision post-turn
extractor: it fires only on explicit self-statements ("call me X", "my timezone is Y") — never
on ambiguous phrasing ("I'm tired") — writes the fact, and returns a short receipt in Layla's
voice so the UI can show a "memory updated" chip. Flag-gated (identity_capture_enabled).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("layla")

# (compiled pattern, identity key, value transform). Anchored + specific to avoid false capture.
_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\b(?:my name is|call me)\s+([A-Z][a-zA-Z'-]{1,30})\b"), "name", "title"),
    (re.compile(r"\bmy pronouns are\s+([a-z]+(?:/[a-z]+){1,2})\b", re.I), "pronouns", "lower"),
    (re.compile(r"\bmy timezone is\s+([A-Za-z][\w+/-]{1,20})\b", re.I), "timezone", "as-is"),
    (re.compile(r"\bi(?:'?m| am) (?:in|based in)\s+(UTC[+-]?\d{0,2}|[A-Z]{3,4}T)\b"), "timezone", "as-is"),
    (re.compile(r"\bi use\s+(vs ?code|vscode|neovim|nvim|vim|emacs|pycharm|sublime|cursor|intellij|zed)\b", re.I), "editor", "editor"),
    (re.compile(r"\bi(?:'?m| am) on\s+(windows|macos|mac ?os|mac|linux|ubuntu|arch|fedora|debian|wsl)\b", re.I), "os", "title"),
    (re.compile(r"\b(?:i work as|i(?:'?m| am) a)\s+((?:senior |junior |lead |staff )?[a-z]+ (?:engineer|developer|designer|scientist|researcher|architect|manager))\b", re.I), "role", "lower"),
]

_EDITOR_CANON = {"vscode": "VS Code", "vs code": "VS Code", "nvim": "Neovim", "neovim": "Neovim",
                 "vim": "Vim", "emacs": "Emacs", "pycharm": "PyCharm", "sublime": "Sublime Text",
                 "cursor": "Cursor", "intellij": "IntelliJ", "zed": "Zed"}


def _apply(kind: str, raw: str) -> str:
    v = raw.strip()
    if kind == "title":
        return v[:1].upper() + v[1:]
    if kind == "lower":
        return v.lower()
    if kind == "editor":
        return _EDITOR_CANON.get(v.lower(), v)
    return v


def extract_identity_facts(user_message: str) -> list[tuple[str, str]]:
    """Return [(key, value)] of high-precision durable facts stated in the message. No writes."""
    msg = (user_message or "").strip()
    if not msg or len(msg) > 2000:
        return []
    found: dict[str, str] = {}
    for pat, key, kind in _RULES:
        if key in found:
            continue
        m = pat.search(msg)
        if m:
            val = _apply(kind, m.group(1))
            if val:
                found[key] = val[:120]
    return list(found.items())


def capture_identity_from_turn(user_message: str) -> str:
    """Persist any durable facts stated this turn; return a one-line receipt ('' if none)."""
    facts = extract_identity_facts(user_message)
    if not facts:
        return ""
    try:
        from layla.memory.db import get_all_user_identity, set_user_identity
        existing = get_all_user_identity() or {}
    except Exception as exc:
        logger.debug("identity capture read failed: %s", exc)
        return ""
    saved: list[str] = []
    for key, val in facts:
        try:
            if str(existing.get(key) or "").strip().lower() == val.strip().lower():
                continue  # already known — no redundant write/receipt
            set_user_identity(key, val)
            saved.append(f"{key.replace('_', ' ')}: {val}")
        except Exception as exc:
            logger.debug("identity capture write failed for %s: %s", key, exc)
    if not saved:
        return ""
    return "Filed that under what I know about you — " + "; ".join(saved) + "."

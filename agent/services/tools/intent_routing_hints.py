"""
Goal-based tool routing: prompt hints for the decision LLM + arg extraction when the model omits args.
"""

from __future__ import annotations

import re
from typing import Any

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.I,
)
_EXPORT_PATH_RE = re.compile(r"[\w./\\~-]+\.(?:json|jsonl)\b", re.I)

_QUERY_PREFIXES = (
    "search past learnings",
    "keyword search learnings",
    "elasticsearch search",
    "search learnings in elasticsearch",
    "memory elasticsearch search",
    "full-text search learnings",
    "search my learnings",
)


def tool_routing_prompt_hints(goal: str) -> str:
    """Short lines appended to the decision prompt so the model picks the right tool."""
    if not goal or not goal.strip():
        return ""
    g = goal.lower()
    lines: list[str] = []
    if any(
        x in g
        for x in (
            "restore checkpoint",
            "restore file",
            "revert file",
            "rollback file",
            "undo file",
            "undo the write",
            "revert my changes",
        )
    ):
        lines.append(
            "Undo file writes: list_file_checkpoints (optional path_filter), then restore_file_checkpoint(checkpoint_id=<uuid from list>)."
        )
    if any(
        x in g
        for x in (
            "import chat",
            "import chats",
            "chat export",
            "chat log",
            "ingest chat",
            "import logs",
            "import conversation",
            "import my messages",
        )
    ):
        lines.append(
            "Import chat backups: ingest_chat_export_to_knowledge(export_path=<json/jsonl under workspace>, label optional). "
            "If Elasticsearch is off, search_memories still works for semantic recall."
        )
    if any(x in g for x in ("search past learnings", "keyword search learnings", "elasticsearch", "es search")) or (
        "full-text" in g and "learning" in g
    ):
        lines.append(
            "Keyword search over mirrored learnings: memory_elasticsearch_search(query=...). "
            "If Elasticsearch is disabled, use search_memories instead."
        )
    if any(x in g for x in ("list checkpoint", "show checkpoint", "file checkpoint")):
        lines.append("List snapshots: list_file_checkpoints(path_filter optional).")
    if not lines:
        return ""
    return "Operator routing hints:\n- " + "\n- ".join(lines) + "\n\n"


def fill_tool_args_from_goal(
    intent: str,
    goal: str,
    workspace: str,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Best-effort args when classify_intent matched but the model did not pass structured args."""
    out: dict[str, Any] = dict(existing or {})
    text = (goal or "").strip()
    low = text.lower()

    if intent == "restore_file_checkpoint":
        cid = str(out.get("checkpoint_id") or "").strip()
        if not cid:
            m = _UUID_RE.search(text)
            if m:
                out["checkpoint_id"] = m.group(0)

    if intent == "ingest_chat_export_to_knowledge":
        ep = str(out.get("export_path") or "").strip()
        if not ep:
            m = _EXPORT_PATH_RE.search(text.replace("\\", "/"))
            if m:
                out["export_path"] = m.group(0).replace("\\", "/")

    if intent == "memory_elasticsearch_search":
        q = str(out.get("query") or "").strip()
        if not q:
            stripped = text
            for prefix in _QUERY_PREFIXES:
                if prefix in low:
                    idx = low.index(prefix) + len(prefix)
                    stripped = text[idx:].lstrip(" \t:-–—,.;")
                    break
            out["query"] = (stripped or text)[:2000]

    if intent == "list_file_checkpoints":
        if not str(out.get("path_filter") or "").strip():
            for pat in (
                r"`([^`]+\.(?:py|ts|tsx|js|json|jsonl|md|txt))`",
                r'"([^"]+\.(?:py|ts|tsx|js|json|jsonl|md|txt))"',
                r"'([^']+\.(?:py|ts|tsx|js|json|jsonl|md|txt))'",
            ):
                m = re.search(pat, text)
                if m:
                    out["path_filter"] = m.group(1)
                    break

    return out

from __future__ import annotations

from typing import Any


def add_entry(
    entry_type: str,
    content: str,
    tags: str | list[str] = "",
    project_id: str = "",
    aspect_id: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    from layla.memory.db import add_journal_entry

    return add_journal_entry(
        entry_type,
        content,
        tags=tags,
        project_id=project_id,
        aspect_id=aspect_id,
        conversation_id=conversation_id,
    )


def list_entries(limit: int = 50, day: str = "") -> dict[str, Any]:
    from layla.memory.db import list_journal_entries

    return {"ok": True, "entries": list_journal_entries(limit=limit, day=day)}


def auto_session_recap(conversation_id: str) -> dict[str, Any]:
    cid = (conversation_id or "").strip()
    if not cid:
        return {"ok": True, "enabled": False, "error": "missing_conversation_id"}

    try:
        from layla.memory.db import get_conversation_messages

        msgs = get_conversation_messages(cid, limit=200) or []
    except Exception:
        msgs = []

    if not msgs:
        return {"ok": True, "enabled": True, "conversation_id": cid, "changed": False, "reason": "no_messages"}

    # Deterministic, low-risk recap: extract a compact trace from the last user+assistant turns.
    # We avoid LLM calls here to keep this safe and always-available.
    last = msgs[-40:] if len(msgs) > 40 else msgs

    user_lines: list[str] = []
    assistant_lines: list[str] = []
    for m in last:
        try:
            role = str(m.get("role") or "").strip().lower()
            content = str(m.get("content") or "").strip()
        except Exception:
            continue
        if not content:
            continue
        if role == "user":
            user_lines.append(content.replace("\r", "").replace("\n", " ").strip())
        elif role == "assistant":
            assistant_lines.append(content.replace("\r", "").replace("\n", " ").strip())

    def _take(sentences: list[str], n: int) -> list[str]:
        out: list[str] = []
        for s in sentences:
            ss = (s or "").strip()
            if not ss:
                continue
            if len(ss) > 220:
                ss = ss[:217].rstrip() + "..."
            out.append(ss)
            if len(out) >= n:
                break
        return out

    user_take = _take(user_lines[::-1], 6)[::-1]
    assistant_take = _take(assistant_lines[::-1], 4)[::-1]

    recap_parts: list[str] = []
    recap_parts.append("## Session recap")
    recap_parts.append("")
    if user_take:
        recap_parts.append("### Operator highlights")
        recap_parts.extend([f"- {x}" for x in user_take])
        recap_parts.append("")
    if assistant_take:
        recap_parts.append("### Assistant highlights")
        recap_parts.extend([f"- {x}" for x in assistant_take])
        recap_parts.append("")

    recap = "\n".join(recap_parts).strip() + "\n"

    try:
        from layla.memory.db import add_journal_entry

        add_journal_entry(
            entry_type="recap",
            content=recap,
            tags=["auto", "session_recap"],
            conversation_id=cid,
        )
        return {"ok": True, "enabled": True, "conversation_id": cid, "changed": True}
    except Exception as e:
        return {"ok": False, "enabled": True, "conversation_id": cid, "error": str(e)[:240]}


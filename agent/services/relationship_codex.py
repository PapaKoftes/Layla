"""
Optional operator-local relationship codex (`.layla/relationship_codex.json`).

Not injected into prompts by default — use when a task references people/entities.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

RELATIVE = Path(".layla") / "relationship_codex.json"


def codex_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / RELATIVE


def load_codex(workspace_root: str | Path) -> dict[str, Any]:
    root = Path(str(workspace_root)).expanduser().resolve()
    p = codex_path(root)
    if not p.is_file():
        return {"entities": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {"entities": {}}
    except Exception as e:
        logger.warning("relationship_codex load failed: %s", e)
        return {"entities": {}}


def save_codex(workspace_root: str | Path, data: dict[str, Any]) -> tuple[bool, str]:
    root = Path(str(workspace_root)).expanduser().resolve()
    dest = codex_path(root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, str(e)
    data = dict(data)
    data.setdefault("entities", {})
    raw = json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    if len(raw) > 2_000_000:
        return False, "relationship_codex too large"
    try:
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(dest.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.replace(tmp, str(dest))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        return False, str(e)
    return True, ""


def upsert_entity(workspace_root: str | Path, name: str, patch: dict[str, Any]) -> dict[str, Any]:
    key = (name or "").strip().lower()
    if not key:
        return {"ok": False, "error": "name required"}
    base = load_codex(workspace_root)
    entities = base.setdefault("entities", {})
    if not isinstance(entities, dict):
        entities = {}
        base["entities"] = entities
    cur = entities.get(key) if isinstance(entities.get(key), dict) else {}
    merged = {**cur, **patch}
    merged.setdefault("traits", [])
    merged.setdefault("history", [])
    entities[key] = merged
    ok, err = save_codex(workspace_root, base)
    if not ok:
        return {"ok": False, "error": err or "save_failed"}
    return {"ok": True, "entity": merged}


def codex_has_entities(data: dict[str, Any]) -> bool:
    """True if codex has at least one entity (for decision/initiative hooks)."""
    if not isinstance(data, dict):
        return False
    ent = data.get("entities")
    return isinstance(ent, dict) and len(ent) > 0


def suggest_codex_updates(
    workspace_root: str | Path,
    goal_or_context: str = "",
    recent_actions: str = "",
) -> dict[str, Any]:
    """
    Read-only suggestions for the operator — does **not** write the codex.
    Heuristic: names in text not yet in entities; preference-style phrases.
    """
    root = Path(str(workspace_root)).expanduser().resolve()
    data = load_codex(root)
    entities = data.get("entities") if isinstance(data.get("entities"), dict) else {}
    keys_lower = {str(k).lower() for k in entities}
    text = f"{goal_or_context or ''}\n{recent_actions or ''}".lower()
    suggestions: list[str] = []

    # Simple token scan for capitalized words / quoted strings as potential names (skip common words)
    skip = frozenset(
        {"the", "a", "an", "and", "or", "to", "for", "with", "from", "this", "that", "layla", "user", "file", "code"}
    )
    for raw in goal_or_context.replace(",", " ").split():
        w = raw.strip("\"'").strip()
        if len(w) < 2 or w.lower() in skip:
            continue
        if w[0].isupper() and w.lower() not in keys_lower:
            suggestions.append(f"Consider adding an entity for “{w}” if they matter for ongoing context.")

    if any(k in text for k in ("prefer", "always", "never do", "i like", "i hate")):
        suggestions.append(
            "Stable preferences appeared in context — consider capturing under an entity’s traits/notes in the codex."
        )

    if not suggestions and not keys_lower:
        suggestions.append(
            "Codex is empty — add key people or teams under `entities` when relationships affect how you work."
        )

    return {
        "ok": True,
        "read_only": True,
        "suggestions": suggestions[:12],
        "note": "Apply manually via Library → Workspace → Codex or approved writes; this tool does not save.",
    }


def format_codex_prompt_digest(data: dict[str, Any], max_chars: int = 1200) -> str:
    """Short text for optional system-head injection (operator-maintained notes)."""
    if not isinstance(data, dict):
        return ""
    entities = data.get("entities")
    if not isinstance(entities, dict) or not entities:
        return ""
    budget = max(200, min(int(max_chars), 4000))
    lines: list[str] = []
    used = 0
    for key in sorted(entities.keys())[:24]:
        ent = entities.get(key)
        if not isinstance(ent, dict):
            continue
        traits = ent.get("traits") if isinstance(ent.get("traits"), list) else []
        trait_s = ", ".join(str(t) for t in traits[:6] if t)
        notes = str(ent.get("notes") or ent.get("summary") or "")[:180].strip()
        hist = ent.get("history") if isinstance(ent.get("history"), list) else []
        hist_s = ""
        if hist:
            last = hist[-1]
            if isinstance(last, str):
                hist_s = last[:120]
            elif isinstance(last, dict):
                hist_s = str(last.get("note") or last.get("text") or last)[:120]
        parts = [f"- {key}"]
        if trait_s:
            parts.append(f"traits: {trait_s}")
        if notes:
            parts.append(notes)
        if hist_s:
            parts.append(f"last: {hist_s}")
        line = " — ".join(parts)
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines).strip()

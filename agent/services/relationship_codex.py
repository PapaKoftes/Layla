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

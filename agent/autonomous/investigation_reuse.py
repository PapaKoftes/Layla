"""Optional persistence of high-confidence investigation summaries (lightweight, not full wiki)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def maybe_append_investigation_reuse(
    *,
    cfg: dict[str, Any],
    workspace_root: str,
    goal: str,
    summary: str,
    findings: list[dict[str, Any]],
    confidence: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """
    When enabled and confidence is high, append one JSON line under workspace `.layla/investigation_reuse.jsonl`.
    """
    if str(confidence or "").strip().lower() != "high":
        return None
    if not bool((cfg or {}).get("investigation_reuse_store_enabled")):
        return None
    root = (workspace_root or "").strip()
    if not root:
        return {"skipped": True, "reason": "no_workspace_root"}
    base = Path(root).expanduser()
    try:
        layla = base / ".layla"
        layla.mkdir(parents=True, exist_ok=True)
        path = layla / "investigation_reuse.jsonl"
        record = {
            "ts": time.time(),
            "run_id": run_id or str(uuid.uuid4()),
            "goal": (goal or "")[:4000],
            "summary": (summary or "")[:12000],
            "findings": findings[:50],
            "confidence": confidence,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return {"ok": True, "path": str(path)}
    except OSError as e:
        return {"ok": False, "error": str(e)[:500]}

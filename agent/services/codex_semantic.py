"""
Optional semantic-style ranking for relationship codex proposals (no auto-write).

When codex_semantic_enabled and Chroma/embedder are available, may use vector similarity;
otherwise falls back to token overlap against proposal text.
"""
from __future__ import annotations

import re
from typing import Any

from services.relationship_codex import load_codex


def _tokenize(text: str) -> set[str]:
    return {w for w in re.split(r"\W+", (text or "").lower()) if len(w) > 2}


def rank_codex_proposals(workspace_root: str, query: str, cfg: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    if not bool(cfg.get("codex_semantic_enabled", False)):
        return []
    if not (query or "").strip():
        return []
    data = load_codex(workspace_root)
    proposals = data.get("proposals") if isinstance(data.get("proposals"), list) else []
    if not proposals:
        return []
    qset = _tokenize(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        blob = " ".join(str(p.get(k) or "") for k in ("summary", "text", "entity", "note", "title"))
        pset = _tokenize(blob)
        overlap = len(qset & pset) if qset else 0
        scored.append((float(overlap), dict(p)))
    scored.sort(key=lambda x: -x[0])
    out = [p for s, p in scored[:limit] if s > 0]
    if out:
        return out
    # weak fallback: recent proposals
    return [dict(p) for p in proposals[-limit:] if isinstance(p, dict)]

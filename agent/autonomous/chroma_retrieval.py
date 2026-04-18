"""Read-only Chroma learnings prefetch for Tier-0 autonomous (no tools, no writes)."""

from __future__ import annotations

from typing import Any

from layla.memory.vector_store import query_learnings_best_similarity


def try_chroma_retrieval(goal: str, workspace_root: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """
    Match goal against embedded learnings. Returns prefetch payload for aggregate_prefetch_hit or None.

    workspace_root is unused but kept for API symmetry with try_reuse_retrieval / try_wiki_retrieval.
    """
    _ = workspace_root  # Tier-0 learnings are global Chroma store, not workspace-scoped
    if not (goal or "").strip():
        return None
    if not bool((cfg or {}).get("autonomous_chroma_enabled", True)):
        return None
    if not bool((cfg or {}).get("use_chroma", True)):
        return None
    try:
        thresh = float((cfg or {}).get("autonomous_chroma_match_threshold") or 0.75)
    except (TypeError, ValueError):
        thresh = 0.75
    try:
        top_k = int((cfg or {}).get("autonomous_chroma_top_k") or 3)
    except (TypeError, ValueError):
        top_k = 3
    top_k = max(1, min(20, top_k))

    best = query_learnings_best_similarity((goal or "").strip(), top_k=top_k)
    if best is None:
        return None
    sim, meta = best
    if sim < thresh:
        return None

    content = ""
    if isinstance(meta, dict):
        content = str(meta.get("content") or "").strip()
    excerpt = content.replace("\n", " ").strip()[:4000]
    findings: list[dict[str, Any]] = []
    if excerpt:
        findings.append({"insight": excerpt[:900], "evidence": []})
    else:
        findings.append({"insight": "(embedding hit with empty content metadata)", "evidence": []})

    emb_id = ""
    if isinstance(meta, dict):
        emb_id = str(meta.get("embedding_id") or "")[:128]

    return {
        "summary": excerpt or "Matched prior learning (Chroma).",
        "findings": findings[:40],
        "confidence": "medium",
        "reasoning": "",
        "embedding_id": emb_id,
        "match_score": round(float(sim), 4),
    }

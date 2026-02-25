"""
Lightweight memory distillation: detect similar learnings/outcomes,
merge into summarized experience, prevent memory bloat.
Run periodically after outcome memory write.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger("layla")

# Similarity threshold: word-set overlap ratio (0 = none, 1 = identical)
_DISTILL_SIMILARITY_THRESHOLD = 0.35
_MAX_DISTILLED_CONTENT = 400


def _normalize_for_similarity(text: str) -> set:
    """Lowercase, alphanumeric tokens."""
    if not text or not isinstance(text, str):
        return set()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower().strip())
    return set(w for w in cleaned.split() if len(w) > 1)


def _similarity(a: set, b: set) -> float:
    """Jaccard-like: |intersection| / |union|."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _group_similar(learnings: list[dict]) -> list[list[dict]]:
    """Group learnings by content similarity. Each group has 2+ items to merge."""
    if len(learnings) < 2:
        return []
    # Precompute normalized sets
    items = []
    for L in learnings:
        c = (L.get("content") or "").strip()
        items.append({"dict": L, "content": c, "words": _normalize_for_similarity(c)})
    used = set()
    groups = []
    for i, x in enumerate(items):
        if i in used:
            continue
        group = [x["dict"]]
        used.add(i)
        for j, y in enumerate(items):
            if j <= i or j in used:
                continue
            if _similarity(x["words"], y["words"]) >= _DISTILL_SIMILARITY_THRESHOLD:
                group.append(y["dict"])
                used.add(j)
        if len(group) >= 2:
            groups.append(group)
    return groups


def _summarize_group(group: list[dict]) -> str:
    """One short summary for a group of similar learnings."""
    parts = []
    for L in group:
        c = (L.get("content") or "").strip()
        if c:
            # First sentence or first 120 chars
            first = c.split(".")[0].strip() + "." if "." in c else c[:120]
            if first and first not in parts:
                parts.append(first[:120])
    if not parts:
        return "Merged experience (no content)."
    summary = " ".join(parts[:3])
    if len(summary) > _MAX_DISTILLED_CONTENT:
        summary = summary[:_MAX_DISTILLED_CONTENT - 3] + "..."
    if len(group) > 1:
        summary += f" [merged from {len(group)} similar]"
    return summary


def memory_distill(learnings: list[dict]) -> dict:
    """
    Detect similar learnings, merge into summarized experience, update DB.
    learnings: list of dicts with keys id, content, type, created_at (e.g. get_recent_learnings).
    Returns: {"merged_groups": N, "removed": M, "added": K}.
    """
    from jinx.memory.db import delete_learnings_by_id, save_learning

    if not learnings or len(learnings) < 2:
        return {"merged_groups": 0, "removed": 0, "added": 0}

    groups = _group_similar(learnings)
    if not groups:
        return {"merged_groups": 0, "removed": 0, "added": 0}

    removed = 0
    added = 0
    for group in groups:
        ids_to_remove = [L["id"] for L in group if L.get("id")]
        summary = _summarize_group(group)
        try:
            delete_learnings_by_id(ids_to_remove)
            removed += len(ids_to_remove)
            save_learning(content=summary, kind="distilled")
            added += 1
        except Exception as e:
            logger.debug("distill merge failed: %s", e)
    return {"merged_groups": len(groups), "removed": removed, "added": added}


def run_distill_after_outcome(n: int = 50) -> dict:
    """
    Call after outcome memory write: load recent learnings and run distillation.
    Returns result of memory_distill (or zeros if skipped).
    """
    from jinx.memory.db import get_recent_learnings

    learnings = get_recent_learnings(n=n)
    return memory_distill(learnings)

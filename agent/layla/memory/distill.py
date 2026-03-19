"""
Lightweight memory distillation: detect similar learnings/outcomes,
merge into summarized experience, prevent memory bloat.
Run periodically after outcome memory write.
"""
import logging
import re

logger = logging.getLogger("layla")

# Similarity threshold: word-set overlap ratio (0 = none, 1 = identical)
_DISTILL_SIMILARITY_THRESHOLD = 0.35


def score_learning_content(content: str) -> float:
    """Heuristic 0..1 for optional quality gate (length, token count, junk patterns)."""
    if not content or not isinstance(content, str):
        return 0.0
    c = content.strip()
    if len(c) < 12:
        return 0.2
    if len(c) > 800:
        score = 0.85
    elif len(c) > 80:
        score = 0.7
    else:
        score = 0.45
    low = c.lower()
    junk = ("i don't know", "as an ai", "cannot assist", "sorry,")
    if any(j in low for j in junk):
        score *= 0.5
    words = len(c.split())
    if words < 4:
        score *= 0.7
    return min(1.0, max(0.0, score))


def passes_learning_quality_gate(content: str) -> tuple[bool, float]:
    """When learning_quality_gate_enabled, reject low-score content before DB insert."""
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        if not cfg.get("learning_quality_gate_enabled", False):
            return True, 1.0
        min_s = float(cfg.get("learning_quality_min_score", 0.35))
    except Exception:
        return True, 1.0
    s = score_learning_content(content)
    return s >= min_s, s
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


def _merge_groups(groups: list[list[dict]]) -> dict:
    """Merge pre-computed groups into distilled learnings. Returns {merged_groups, removed, added}."""
    from layla.memory.db import delete_learnings_by_id, save_learning

    if not groups:
        return {"merged_groups": 0, "removed": 0, "added": 0}
    removed = 0
    added = 0
    for group in groups:
        ids_to_remove = [L["id"] for L in group if L.get("id")]
        # Collect old embedding IDs so we can remove them from ChromaDB
        old_embedding_ids = [L["embedding_id"] for L in group if L.get("embedding_id")]
        summary = _summarize_group(group)
        try:
            delete_learnings_by_id(ids_to_remove)
            removed += len(ids_to_remove)
            # Remove old vectors and add fresh one for the merged summary
            embedding_id = ""
            try:
                from layla.memory.vector_store import add_vector, delete_vectors_by_ids, embed
                if old_embedding_ids:
                    delete_vectors_by_ids(old_embedding_ids)
                vec = embed(summary)
                embedding_id = add_vector(vec, {"content": summary, "type": "distilled"})
            except Exception as ve:
                logger.debug("distill vector update failed: %s", ve)
            save_learning(content=summary, kind="distilled", embedding_id=embedding_id)
            added += 1
        except Exception as e:
            logger.debug("distill merge failed: %s", e)
    return {"merged_groups": len(groups), "removed": removed, "added": added}


def memory_distill(learnings: list[dict]) -> dict:
    """
    Detect similar learnings, merge into summarized experience, update DB.
    learnings: list of dicts with keys id, content, type, created_at (e.g. get_recent_learnings).
    Returns: {"merged_groups": N, "removed": M, "added": K}.
    """
    if not learnings or len(learnings) < 2:
        return {"merged_groups": 0, "removed": 0, "added": 0}
    groups = _group_similar(learnings)
    return _merge_groups(groups)


def memory_distill_semantic(learnings: list[dict], threshold: float = 0.75) -> dict:
    """
    Optional: cluster learnings by sentence embedding similarity, then merge.
    Falls back to memory_distill (Jaccard) if embeddings unavailable.
    """
    if not learnings or len(learnings) < 2:
        return {"merged_groups": 0, "removed": 0, "added": 0}
    try:
        import numpy as np

        from layla.memory.vector_store import embed
        valid = [(i, L) for i, L in enumerate(learnings) if (L.get("content") or "").strip()]
        if len(valid) < 2:
            return memory_distill(learnings)
        subset = [v[1] for v in valid]
        vecs = [embed((L.get("content") or "").strip()[:500]) for L in subset]
        if len(vecs) < 2:
            return memory_distill(learnings)
        try:
            from sklearn.cluster import AgglomerativeClustering
            X = np.array(vecs, dtype=np.float32)
            n_clusters = max(1, min(len(vecs) - 1, len(vecs) // 2))
            clustering = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine", linkage="average")
            labels = clustering.fit_predict(X)
            groups = []
            for lid in set(labels):
                idxs = [i for i, lbl in enumerate(labels) if lbl == lid]
                if len(idxs) >= 2:
                    groups.append([subset[i] for i in idxs])
            if not groups:
                return memory_distill(learnings)
            return _merge_groups(groups)
        except ImportError:
            return memory_distill(learnings)
    except Exception:
        return memory_distill(learnings)


def distill_rules(learnings: list[dict], max_rules: int = 5) -> list[str]:
    """
    Generate distilled rules from learnings clusters.
    Returns list of rule strings like "Prefer X when Y".
    """
    if not learnings or len(learnings) < 2:
        return []
    groups = _group_similar(learnings)
    rules = []
    for group in groups[:max_rules]:
        summary = _summarize_group(group)
        if summary and "Merged" not in summary:
            rule = f"When: {summary[:150]}"
            if len(summary) > 150:
                rule += "..."
            rules.append(rule)
    return rules[:max_rules]


def run_distill_after_outcome(n: int = 50, use_semantic: bool = False) -> dict:
    """
    Call after outcome memory write: load recent learnings and run distillation.
    use_semantic: if True, try embedding-based clustering (requires sentence-transformers).
    Returns result of memory_distill (or zeros if skipped).
    """
    from layla.memory.db import get_recent_learnings

    learnings = get_recent_learnings(n=n)
    if use_semantic:
        return memory_distill_semantic(learnings)
    return memory_distill(learnings)

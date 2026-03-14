"""
Conversation style profiling. Tracks patterns in user interactions:
tone, preferred response style, frequent topics.
Uses embeddings + clustering to derive profiles. Updates db.style_profile.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger("layla")


def _extract_tone_hints(text: str) -> list[str]:
    """Heuristic tone detection from text patterns."""
    hints = []
    t = (text or "").lower().strip()
    if not t:
        return hints
    if any(w in t for w in ("thanks", "thank you", "appreciate", "great", "perfect", "awesome")):
        hints.append("appreciative")
    if any(w in t for w in ("urgent", "asap", "quick", "hurry", "immediately")):
        hints.append("urgent")
    if any(w in t for w in ("?", "how do", "what is", "why does", "explain")):
        hints.append("inquisitive")
    if any(w in t for w in ("please", "could you", "would you", "can you")):
        hints.append("polite")
    if any(w in t for w in ("fix", "broken", "error", "bug", "doesn't work")):
        hints.append("problem-solving")
    if len(t) < 50 and t.count(" ") < 5:
        hints.append("brief")
    if len(t) > 200:
        hints.append("detailed")
    return hints


def _extract_topic_keywords(text: str, min_len: int = 4) -> list[str]:
    """Extract likely topic words (simple heuristic: longer words, exclude common stopwords)."""
    stop = {"this", "that", "with", "from", "have", "been", "were", "what", "when", "where",
            "which", "would", "could", "should", "about", "into", "some", "more", "very",
            "just", "only", "also", "then", "than", "them", "they", "their", "there"}
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9]{2,}\b", (text or "").lower())
    return [w for w in words if w not in stop and len(w) >= min_len][:30]


def update_profile_from_interactions(interactions: list[dict]) -> None:
    """
    Analyze interactions and update style_profile in db.
    interactions: list of {role, content} or {user_event, ...}
    """
    if not interactions:
        return
    try:
        from layla.memory.db import migrate, set_style_profile
        migrate()
    except Exception as e:
        logger.debug("style_profile db: %s", e)
        return

    all_text = []
    tones: list[str] = []
    topics: Counter[str] = Counter()

    for item in interactions:
        content = item.get("content") or item.get("user_event") or ""
        if not content or len(content.strip()) < 5:
            continue
        all_text.append(content.strip())
        tones.extend(_extract_tone_hints(content))
        topics.update(_extract_topic_keywords(content))

    if not all_text:
        return

    # Preferred response style: infer from user patterns
    response_style_parts = []
    tone_counts = Counter(tones)
    if tone_counts:
        top_tones = [t for t, _ in tone_counts.most_common(3)]
        response_style_parts.append(f"User tone patterns: {', '.join(top_tones)}")
    if len(all_text) > 0:
        avg_len = sum(len(t) for t in all_text) / len(all_text)
        if avg_len < 80:
            response_style_parts.append("User tends brief; match conciseness.")
        elif avg_len > 300:
            response_style_parts.append("User provides detail; thorough responses appreciated.")

    # Frequent topics
    top_topics = [t for t, _ in topics.most_common(8) if t]
    topic_snapshot = ", ".join(top_topics) if top_topics else "general"

    try:
        if response_style_parts:
            set_style_profile("response_style", "\n".join(response_style_parts))
        set_style_profile("topics", f"Frequent topics: {topic_snapshot}")
    except Exception as e:
        logger.debug("style_profile update: %s", e)


def get_profile_summary() -> dict[str, Any]:
    """Return a summary of current style profile for injection."""
    result: dict[str, Any] = {"tone": "", "response_style": "", "topics": ""}
    try:
        from layla.memory.db import get_style_profile, migrate
        migrate()
        for key in ("response_style", "topics"):
            row = get_style_profile(key)
            if row and (row.get("profile_snapshot") or "").strip():
                result[key] = (row.get("profile_snapshot") or "").strip()[:400]
    except Exception:
        pass
    return result


def cluster_topics_with_embeddings(texts: list[str], k: int = 5) -> list[str]:
    """
    Use embeddings + simple clustering to find recurring topic clusters.
    Returns representative topic labels (first few words of centroid-like samples).
    """
    if not texts or len(texts) < 2:
        return _extract_topic_keywords(texts[0] if texts else "")[:k]
    try:
        import numpy as np

        from layla.memory.vector_store import embed
        vecs = [embed(t[:500]) for t in texts[:20]]
        if len(vecs) < 2:
            return _extract_topic_keywords(texts[0])[:k]
        arr = np.array([v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs])
        # Simple k-means style: pick k diverse samples by max-min distance
        chosen = [0]
        for _ in range(min(k - 1, len(arr) - 1)):
            best_idx = max(
                range(len(arr)),
                key=lambda i: min(np.linalg.norm(arr[i] - arr[j]) for j in chosen) if i not in chosen else -1,
            )
            chosen.append(best_idx)
        return _extract_topic_keywords(" ".join(texts[i] for i in chosen))[:k]
    except Exception:
        return _extract_topic_keywords(" ".join(texts))[:k]

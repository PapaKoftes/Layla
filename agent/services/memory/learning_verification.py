"""Memory/learning verification pipeline (BL-192).

Stored learnings already decay by age and get pruned below a confidence floor, and the
spaced-repetition queue schedules re-review. What was missing is a *consistency* check:
catching two learnings that make **contradictory** claims about the same thing, and a
single pass that ties decay + prune + contradiction-flagging + due-for-review together
into one report. Contradiction detection is a cheap, model-free heuristic (shared subject
terms + a polarity flip), so the pipeline runs anywhere; an optional LLM adjudication can
layer on top when a model is available.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla")

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9']+")
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was",
    "will", "have", "has", "not", "but", "can", "all", "any", "when", "then", "than", "user",
    "learning", "correction", "prefers", "prefer", "always", "never", "should", "would",
}
_NEG = {"not", "never", "no", "don't", "dont", "doesn't", "doesnt", "isn't", "isnt", "avoid",
        "without", "stop", "hate", "dislikes", "dislike"}
_POS = {"always", "prefer", "prefers", "like", "likes", "love", "loves", "want", "wants", "use"}


def _content_tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "") if w.lower() not in _STOP and len(w) > 2}


def _polarity(text: str) -> int:
    """+1 affirmative, -1 negative, 0 neutral. Negation dominates ("does not want" → -1)."""
    toks = {w.lower() for w in _WORD.findall(text or "")}
    if toks & _NEG:
        return -1
    if toks & _POS:
        return 1
    return 0


def find_contradictions(learnings: list[dict], *, min_overlap: int = 3) -> list[dict]:
    """Candidate contradictory pairs: same subject terms, opposite polarity."""
    prepared = []
    for lg in learnings:
        content = str(lg.get("content") or "")
        prepared.append((lg, _content_tokens(content), _polarity(content)))
    out: list[dict] = []
    for i in range(len(prepared)):
        for j in range(i + 1, len(prepared)):
            (a, ta, pa), (b, tb, pb) = prepared[i], prepared[j]
            shared = ta & tb
            if len(shared) >= min_overlap and pa != 0 and pb != 0 and pa != pb:
                out.append({
                    "a_id": a.get("id"), "b_id": b.get("id"),
                    "a": str(a.get("content"))[:200], "b": str(b.get("content"))[:200],
                    "shared_terms": sorted(shared)[:8],
                })
    return out


def run_verification_pass(
    *, sample: int = 200, prune_threshold: float = 0.08, prune: bool = True,
) -> dict[str, Any]:
    """One consistency pass over recent learnings — decay-aware, prune, flag contradictions."""
    from layla.memory.learnings import get_learnings_due_for_review, get_recent_learnings

    learnings = get_recent_learnings(n=sample) or []
    # decay is already applied to `adjusted_confidence` on read; count the weakened ones
    decayed = sum(
        1 for lg in learnings
        if lg.get("adjusted_confidence") is not None
        and float(lg["adjusted_confidence"]) < float(lg.get("confidence") or 0.5) - 1e-9
    )
    contradictions = find_contradictions(learnings, min_overlap=2)

    pruned = 0
    if prune:
        try:
            from services.memory.memory_consolidation import prune_low_confidence_learnings
            pruned = prune_low_confidence_learnings(threshold=prune_threshold)
        except Exception as e:  # noqa: BLE001
            logger.debug("verification prune skipped: %s", e)

    try:
        due = len(get_learnings_due_for_review(limit=100) or [])
    except Exception:
        due = 0

    return {
        "reviewed": len(learnings),
        "decayed": decayed,
        "pruned": pruned,
        "due_for_review": due,
        "contradictions": contradictions,
        "contradiction_count": len(contradictions),
    }

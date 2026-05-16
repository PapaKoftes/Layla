# -*- coding: utf-8 -*-
"""
context_attribution.py — Attribute response content to source context.

After each LLM response, scores which context snippets (memories, workspace
chunks, learnings) contributed most to the response. Enables "based on: [source]"
tooltips in the UI.

Strategy:
  1. Segment the response into sentences.
  2. For each sentence, compute word-overlap similarity against each context source.
  3. Return top attributions sorted by contribution score.
  4. Optionally persist attributions alongside the response in tool_calls table.

Config keys:
    context_attribution_enabled   bool  (default true)
    attribution_min_score         float (default 0.15)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("layla")


@dataclass
class Attribution:
    """A single attribution linking response content to a source."""
    source_id: str          # e.g., "learning:42", "workspace:src/main.py", "memory:episodic"
    source_label: str       # Human-readable label
    source_snippet: str     # First ~200 chars of the source content
    score: float            # 0.0–1.0 contribution score
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class AttributionResult:
    """Full attribution analysis for one response."""
    response_snippet: str   # First ~200 chars of the response
    attributions: list[Attribution] = field(default_factory=list)
    total_sources_checked: int = 0
    coverage: float = 0.0   # Fraction of response sentences with attributions


def _word_set(text: str) -> set[str]:
    """Extract lowercase word set (3+ chars) from text."""
    return set(re.findall(r"\b[a-z]{3,}\b", text.lower()))


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-like segments."""
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [s.strip() for s in parts if s and s.strip() and len(s.strip()) > 10]


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two word sets."""
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _compute_overlap_score(
    response_words: set[str],
    source_words: set[str],
) -> tuple[float, list[str]]:
    """
    Compute word-overlap score between response and source.

    Returns (score, matched_terms).
    Score is weighted: exact term matches count more than common words.
    """
    if not response_words or not source_words:
        return 0.0, []

    # Common English stopwords to de-weight
    _stopwords = {
        "the", "and", "for", "that", "this", "with", "from", "are", "was",
        "were", "been", "have", "has", "had", "not", "but", "can", "will",
        "would", "should", "could", "also", "more", "than", "into", "when",
        "which", "about", "their", "there", "these", "those", "then",
    }

    matched = response_words & source_words
    non_stop_matched = matched - _stopwords
    all_non_stop = (response_words | source_words) - _stopwords

    if not all_non_stop:
        return 0.0, list(matched)[:10]

    # Weighted: non-stopword matches count 2x
    score = (len(non_stop_matched) * 2 + len(matched & _stopwords)) / (len(all_non_stop) * 2 + len(_stopwords & (response_words | source_words)))
    return min(1.0, score), sorted(non_stop_matched)[:10]


def attribute_response(
    response_text: str,
    context_sources: list[dict[str, str]],
    *,
    min_score: float = 0.15,
    top_k: int = 5,
    cfg: dict | None = None,
) -> AttributionResult:
    """
    Attribute a response to its contributing context sources.

    Args:
        response_text: The LLM response text.
        context_sources: List of dicts with keys:
            - "id": Source identifier (e.g., "learning:42")
            - "label": Human-readable label
            - "content": Source content text
        min_score: Minimum score to include attribution.
        top_k: Maximum attributions to return.
        cfg: Optional config dict.

    Returns:
        AttributionResult with scored attributions.
    """
    cfg = cfg or {}
    if not cfg.get("context_attribution_enabled", True):
        return AttributionResult(response_snippet=response_text[:200])

    min_score = float(cfg.get("attribution_min_score", min_score))

    if not response_text or not context_sources:
        return AttributionResult(
            response_snippet=(response_text or "")[:200],
            total_sources_checked=len(context_sources or []),
        )

    # Build response word set
    response_words = _word_set(response_text)
    response_sentences = _split_sentences(response_text)

    attributions: list[Attribution] = []

    for source in context_sources:
        src_id = source.get("id", "unknown")
        src_label = source.get("label", src_id)
        src_content = source.get("content", "")
        if not src_content:
            continue

        source_words = _word_set(src_content)
        score, matched = _compute_overlap_score(response_words, source_words)

        if score >= min_score:
            attributions.append(Attribution(
                source_id=src_id,
                source_label=src_label,
                source_snippet=src_content[:200],
                score=round(score, 3),
                matched_terms=matched,
            ))

    # Sort by score descending
    attributions.sort(key=lambda a: -a.score)
    attributions = attributions[:top_k]

    # Calculate coverage: fraction of response sentences with at least one attribution
    coverage = 0.0
    if response_sentences and attributions:
        covered = 0
        for sent in response_sentences:
            sent_words = _word_set(sent)
            for attr in attributions:
                attr_words = _word_set(attr.source_snippet)
                if _jaccard_similarity(sent_words, attr_words) > 0.1:
                    covered += 1
                    break
        coverage = covered / len(response_sentences)

    return AttributionResult(
        response_snippet=response_text[:200],
        attributions=attributions,
        total_sources_checked=len(context_sources),
        coverage=round(coverage, 2),
    )


def persist_attributions(
    run_id: str,
    attributions: AttributionResult,
) -> None:
    """Save attributions to the tool_calls table for later UI display."""
    if not attributions.attributions:
        return
    try:
        import json

        from layla.memory.db_connection import _conn
        data = json.dumps([
            {
                "source_id": a.source_id,
                "label": a.source_label,
                "score": a.score,
                "terms": a.matched_terms[:5],
            }
            for a in attributions.attributions
        ])
        with _conn() as db:
            db.execute(
                "INSERT OR REPLACE INTO tool_calls (id, run_id, tool_name, args_hash, result_ok, duration_ms) "
                "VALUES (?, ?, 'context_attribution', ?, 1, 0)",
                (f"attr_{run_id}", run_id, data),
            )
    except Exception as exc:
        logger.debug("persist_attributions failed: %s", exc)

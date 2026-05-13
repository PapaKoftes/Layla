"""
chunker.py -- Semantic text chunking with sentence-aware splitting.

Splits text into overlapping chunks sized by approximate token count,
breaking on sentence boundaries to preserve meaning.
"""
from __future__ import annotations

import re

# Sentence boundary pattern: split after . ! ? or double-newline
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: word count * 1.3."""
    if not text:
        return 0
    return int(len(text.split()) * 1.3)


def chunk_text(
    text: str,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[str]:
    """
    Split *text* into overlapping chunks, sentence-aware.

    Each chunk targets *max_tokens* approximate tokens. Overlap is drawn
    from the tail of the previous chunk so retrieval sees context across
    boundaries.  Single sentences that exceed *max_tokens* are kept whole
    rather than mid-word split.
    """
    if not text or not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        s_tokens = estimate_tokens(sentence)

        if current and (current_tokens + s_tokens) > max_tokens:
            # Flush current chunk
            chunks.append(" ".join(current))
            # Build overlap from tail of current chunk
            current, current_tokens = _build_overlap(current, overlap_tokens)

        current.append(sentence)
        current_tokens += s_tokens

    # Flush remaining
    if current:
        chunks.append(" ".join(current))

    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-like segments."""
    parts = _SENTENCE_RE.split(text)
    return [s.strip() for s in parts if s and s.strip()]


def _build_overlap(
    sentences: list[str],
    overlap_tokens: int,
) -> tuple[list[str], int]:
    """Return (overlap_sentences, overlap_token_count) from the tail of *sentences*."""
    overlap: list[str] = []
    tokens = 0
    for sentence in reversed(sentences):
        s_tokens = estimate_tokens(sentence)
        if tokens + s_tokens > overlap_tokens and overlap:
            break
        overlap.insert(0, sentence)
        tokens += s_tokens
    return overlap, tokens

"""
Accurate token counting for context budgeting and prompt assembly.
Uses tiktoken (cl100k_base) when available; fallback to ~4 chars/token heuristic.
"""
from __future__ import annotations

_enc = None


def _get_encoding():
    """Lazy-load tiktoken encoding. Returns None if unavailable."""
    global _enc
    if _enc is not None:
        return _enc
    try:
        import tiktoken
        _enc = tiktoken.get_encoding("cl100k_base")
        return _enc
    except Exception:
        _enc = False  # Mark as unavailable
        return None


def count_tokens(text: str) -> int:
    """
    Count tokens in text. Uses tiktoken (cl100k_base) when available.
    Fallback: ~4 chars per token (typical for English/code).
    """
    enc = _get_encoding()
    if enc:  # Truthy when tiktoken loaded; False when unavailable
        return len(enc.encode(text))
    return max(1, len(text) // 4)


def count_tokens_messages(messages: list[dict]) -> int:
    """Total token count for a list of {role, content} dicts. Adds ~4 per message overhead."""
    total = 0
    for m in messages:
        c = (m.get("content") or "")
        total += count_tokens(c) + 4
    return total


def token_count_available() -> bool:
    """True if tiktoken is available for accurate counting."""
    return bool(_get_encoding())

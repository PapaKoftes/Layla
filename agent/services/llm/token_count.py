"""
Accurate token counting for context budgeting and prompt assembly.

For non-ASCII text a RESIDENT model's own tokenizer is preferred: the shipped model is Qwen2.5
(vocab 151,936), and tiktoken's cl100k_base (100,277) over-counts non-Latin scripts badly — measured
+10% Spanish, +41% Russian, +72% Japanese, +100% Chinese. Budgeting with the over-count silently
over-truncates a CJK/RTL user's context against a shipped 11-language UI (O-7). The loaded llama.cpp
model tokenizes exactly and for free at inference time. ASCII text (English/code, 0% divergence) stays
on tiktoken to keep the hot path cheap; tiktoken is also the fallback whenever no model is resident.
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


def _resident_model_token_count(text: str) -> int | None:
    """Exact token count using the RESIDENT model's own tokenizer, or None if unavailable.

    NEVER triggers a model load — this is the budgeting hot path, so it only uses a model that is
    already in memory. tokenize() is a vocab-level, read-only operation (it does not touch the KV
    cache), so it is safe to call alongside generation. Any failure returns None so the caller falls
    back to tiktoken.
    """
    try:
        from services.llm import llm_gateway
        model = llm_gateway.get_resident_model()
        if model is None:
            return None
        toks = model.tokenize(text.encode("utf-8", "ignore"), add_bos=False, special=False)
        return len(toks)
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """
    Count tokens in text. For non-ASCII text, prefers the resident model's exact tokenizer (Qwen2.5)
    to avoid tiktoken's large non-Latin over-count; otherwise uses tiktoken (cl100k_base).
    Fallback: ~4 chars per token (typical for English/code).
    """
    if text and not text.isascii():
        exact = _resident_model_token_count(text)
        if exact is not None:
            return exact
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

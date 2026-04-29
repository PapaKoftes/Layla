"""
prompt_compressor.py — Intelligent prompt & context compression.

Integrates multiple compression strategies in a tiered pipeline:

TIER 1 — LLMLingua (Microsoft, https://github.com/microsoft/LLMLingua)
  Iterative token-level pruning using a small LM (Phi-2 or LLaMA) to score each
  token's perplexity contribution. Achieves 5-20x compression with <5% quality
  loss on most tasks. Requires: pip install llmlingua

TIER 2 — LongLLMLingua
  Question-aware compression for retrieval-augmented contexts. Ranks retrieved
  chunks by their relevance to the query before compressing. Same package.

TIER 3 — Heuristic sentence-scoring (always available, zero dependencies)
  Scores sentences by: keyword density, position (first/last sentences score
  higher), redundancy detection (cosine sim approximated by word overlap),
  and semantic density (info per character). Fast and dependency-free.

TIER 4 — Truncation fallback
  Hard-trim to token budget with sentence-boundary awareness.

Config keys in config.json:
    prompt_compression_enabled    bool   (default true for tier-3+)
    prompt_compression_tier       int    1|2|3|4 (default: highest available tier)
    prompt_compression_ratio      float  Target compression: 0.1–0.9 (default 0.5)
    prompt_compression_model      str    LLMLingua model ID (default "microsoft/phi-2")
    prompt_compression_device     str    "cpu"|"cuda" (default auto)

Usage:
    from services.prompt_compressor import compress, compress_rag_context

    # Compress a long system context
    result = compress(long_text, target_ratio=0.4, question="What is X?")
    print(result["compressed"])  # Compressed text
    print(result["ratio"])       # Actual achieved ratio

    # Compress retrieved RAG documents around a query
    docs = ["doc 1 text...", "doc 2 text..."]
    result = compress_rag_context(docs, query="What is X?", token_budget=500)
    print(result["compressed"])
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_lingua_cache: dict[str, Any] = {}  # model_id → loaded LLMLingua instance


# ── Config ────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        import json
        p = Path(__file__).resolve().parent.parent / "config.json"
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _compression_enabled() -> bool:
    return bool(_cfg().get("prompt_compression_enabled", True))


def _target_ratio() -> float:
    return float(_cfg().get("prompt_compression_ratio", 0.5))


def _lingua_model() -> str:
    return _cfg().get("prompt_compression_model", "microsoft/phi-2")


def _lingua_device() -> str:
    d = _cfg().get("prompt_compression_device", "auto")
    if d == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return d


# ── Tier detection ────────────────────────────────────────────────────────────

def _llmlingua_available() -> bool:
    try:
        import llmlingua  # noqa: F401
        return True
    except ImportError:
        return False


def get_available_tier() -> int:
    """Return the best available compression tier (1=best, 4=fallback)."""
    if _llmlingua_available():
        return 1  # LLMLingua + LongLLMLingua both in same package
    return 3  # Heuristic always available


def get_info() -> dict:
    """Return compression capability info."""
    return {
        "enabled": _compression_enabled(),
        "llmlingua_installed": _llmlingua_available(),
        "available_tier": get_available_tier(),
        "target_ratio": _target_ratio(),
        "lingua_model": _lingua_model(),
        "device": _lingua_device(),
    }


# ── Tier 1 & 2: LLMLingua ─────────────────────────────────────────────────────

def _load_lingua(model_id: str) -> Any:
    """Lazy-load LLMLingua compressor, cached."""
    if model_id in _lingua_cache:
        return _lingua_cache[model_id]
    from llmlingua import PromptCompressor
    device = _lingua_device()
    logger.info("prompt_compressor: loading LLMLingua model '%s' on %s...", model_id, device)
    compressor = PromptCompressor(
        model_name=model_id,
        use_llmlingua2=True,  # Use LLMLingua-2 (faster, better quality)
        device_map=device,
    )
    _lingua_cache[model_id] = compressor
    logger.info("prompt_compressor: LLMLingua ready")
    return compressor


def _compress_with_lingua(
    text: str,
    question: str = "",
    target_ratio: float = 0.5,
    context_budget: int | None = None,
) -> dict:
    """
    Compress using LLMLingua. Returns {"compressed": str, "ratio": float, "method": "llmlingua"}.
    """
    model_id = _lingua_model()
    try:
        compressor = _load_lingua(model_id)
        kwargs: dict = {
            "compression_rate": 1.0 - target_ratio,  # LLMLingua uses "how much to remove"
            "force_tokens": ["\n", ".", "!", "?"],  # Always keep sentence boundaries
            "drop_consecutive": True,
        }
        if question:
            kwargs["question"] = question
        if context_budget:
            kwargs["token_budget"] = context_budget

        result = compressor.compress_prompt(text, **kwargs)
        compressed = result.get("compressed_prompt", text)
        orig_len = max(1, len(text))
        new_len = len(compressed)
        ratio = new_len / orig_len
        logger.debug("prompt_compressor: LLMLingua %.0f%% → %.0f%% (ratio %.2f)",
                     100, ratio * 100, ratio)
        return {"compressed": compressed, "ratio": ratio, "method": "llmlingua"}
    except Exception as exc:
        logger.warning("prompt_compressor: LLMLingua failed (%s), falling back to heuristic", exc)
        return _compress_heuristic(text, target_ratio=target_ratio)


def _compress_rag_with_lingua(
    context_list: list[str],
    question: str,
    token_budget: int = 500,
    target_ratio: float = 0.5,
) -> dict:
    """
    LongLLMLingua: question-aware compression across multiple retrieved documents.
    """
    model_id = _lingua_model()
    try:
        # Try LongLLMLingua first (better for multi-doc RAG)
        from llmlingua import PromptCompressor
        compressor = _load_lingua(model_id)

        result = compressor.compress_prompt(
            context_list,
            instruction="Answer the question based on the given documents.",
            question=question,
            target_token=token_budget,
            iterative_size=200,
            dynamic_context_compression_ratio=0.4,
            reorder_context="sort",  # Sort by relevance to question
            condition_compare=True,
        )
        compressed = result.get("compressed_prompt", "\n\n".join(context_list))
        total_orig = sum(len(c) for c in context_list)
        ratio = len(compressed) / max(1, total_orig)
        return {
            "compressed": compressed,
            "ratio": ratio,
            "method": "longllmlingua",
            "docs_in": len(context_list),
        }
    except Exception as exc:
        logger.warning("prompt_compressor: LongLLMLingua failed (%s), heuristic fallback", exc)
        merged = "\n\n---\n\n".join(context_list)
        return _compress_heuristic(merged, target_ratio=target_ratio)


# ── Tier 3: Heuristic sentence scoring ────────────────────────────────────────

def _sentence_split(text: str) -> list[str]:
    """Split text into sentences preserving newlines as hard breaks."""
    lines = text.splitlines()
    sentences: list[str] = []
    _end_re = re.compile(r'(?<=[.!?])\s+')
    for line in lines:
        if not line.strip():
            sentences.append("")
            continue
        parts = _end_re.split(line.strip())
        sentences.extend(parts)
    return [s for s in sentences if s]


def _word_set(text: str) -> set[str]:
    return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))


def _tf_idf_score(sentence: str, corpus_words: Counter, n_docs: int) -> float:
    """Approximate TF-IDF sentence score."""
    words = _word_set(sentence)
    if not words:
        return 0.0
    score = 0.0
    for w in words:
        tf = sentence.lower().count(w) / max(1, len(sentence.split()))
        idf = math.log(n_docs / max(1, corpus_words[w]))
        score += tf * idf
    return score / len(words)


def _redundancy_penalty(sentence: str, kept: list[str]) -> float:
    """Return overlap ratio (0–1) with already-kept sentences (word Jaccard)."""
    if not kept:
        return 0.0
    s_words = _word_set(sentence)
    if not s_words:
        return 0.0
    max_overlap = 0.0
    for other in kept[-5:]:  # compare against last 5 kept sentences
        o_words = _word_set(other)
        if not o_words:
            continue
        inter = len(s_words & o_words)
        union = len(s_words | o_words)
        overlap = inter / union if union else 0.0
        max_overlap = max(max_overlap, overlap)
    return max_overlap


def _compress_heuristic(text: str, target_ratio: float = 0.5, question: str = "") -> dict:
    """
    Heuristic compression:
    1. Score sentences by TF-IDF density + position bonus.
    2. Penalise redundancy against already-selected sentences.
    3. Keep top-scoring sentences until target character budget met.
    4. Preserve order in output.
    """
    sentences = _sentence_split(text)
    if not sentences:
        return {"compressed": text, "ratio": 1.0, "method": "heuristic_trivial"}

    target_len = max(100, int(len(text) * target_ratio))

    # Build corpus word frequency for IDF
    corpus_words: Counter = Counter()
    for s in sentences:
        for w in _word_set(s):
            corpus_words[w] += 1
    n = len(sentences)

    # Question keywords boost
    q_words = _word_set(question) if question else set()

    # Score each sentence
    scores: list[float] = []
    for i, sent in enumerate(sentences):
        if not sent.strip():
            scores.append(-1.0)
            continue

        # Base TF-IDF score
        base = _tf_idf_score(sent, corpus_words, n)

        # Position bonus: first 10% and last 10% of sentences score +0.3
        pos_ratio = i / max(1, n - 1)
        pos_bonus = 0.3 if (pos_ratio < 0.1 or pos_ratio > 0.9) else 0.0

        # Question relevance bonus
        q_bonus = 0.0
        if q_words:
            s_words = _word_set(sent)
            q_bonus = len(s_words & q_words) / max(1, len(q_words)) * 0.5

        # Length penalty (avoid very short fragments)
        len_penalty = 0.0 if len(sent) > 20 else 0.2

        scores.append(base + pos_bonus + q_bonus - len_penalty)

    # Greedy selection: pick by score, skip redundant
    order = sorted(range(n), key=lambda i: scores[i], reverse=True)
    selected: set[int] = set()
    kept_texts: list[str] = []
    current_len = 0

    for idx in order:
        sent = sentences[idx]
        if not sent.strip():
            continue
        if current_len >= target_len:
            break
        # Redundancy check
        redundancy = _redundancy_penalty(sent, kept_texts)
        if redundancy > 0.65:  # skip if >65% overlap with already selected
            continue
        selected.add(idx)
        kept_texts.append(sent)
        current_len += len(sent) + 1

    # Reconstruct in original order
    result_sentences = [sentences[i] for i in sorted(selected)]
    compressed = " ".join(s for s in result_sentences if s.strip())

    ratio = len(compressed) / max(1, len(text))
    return {"compressed": compressed, "ratio": ratio, "method": "heuristic"}


# ── Tier 4: Truncation ────────────────────────────────────────────────────────

def _truncate_to_budget(text: str, char_budget: int) -> dict:
    """Sentence-aware truncation to character budget."""
    if len(text) <= char_budget:
        return {"compressed": text, "ratio": 1.0, "method": "passthrough"}
    # Find last sentence boundary within budget
    truncated = text[:char_budget]
    for punct in (".  ", ". ", ".\n", "!\n", "?\n"):
        idx = truncated.rfind(punct)
        if idx > char_budget * 0.6:
            truncated = truncated[:idx + 1]
            break
    ratio = len(truncated) / max(1, len(text))
    return {"compressed": truncated + " [...]", "ratio": ratio, "method": "truncation"}


# ── Public API ────────────────────────────────────────────────────────────────

def compress(
    text: str,
    *,
    target_ratio: float | None = None,
    question: str = "",
    token_budget: int | None = None,
    force_heuristic: bool = False,
) -> dict:
    """
    Compress text to target_ratio of original length.

    Args:
        text:           Text to compress.
        target_ratio:   Desired output/input length ratio (0.1–0.9). Default from config.
        question:       Optional question to guide compression (keeps relevant tokens).
        token_budget:   Hard token budget for output (overrides target_ratio if set).
        force_heuristic: Skip LLMLingua even if installed (for fast paths).

    Returns:
        {
            "compressed": str,
            "ratio": float,        # actual achieved ratio
            "original_len": int,
            "compressed_len": int,
            "method": str,         # "llmlingua" | "heuristic" | "truncation" | "passthrough"
        }
    """
    if not text or not text.strip():
        return {"compressed": "", "ratio": 1.0, "original_len": 0, "compressed_len": 0, "method": "passthrough"}

    if token_budget is not None:
        # Convert token budget to char budget (~4 chars/token)
        char_budget = token_budget * 4
        if len(text) <= char_budget:
            return {"compressed": text, "ratio": 1.0, "original_len": len(text),
                    "compressed_len": len(text), "method": "passthrough"}
        target_ratio = char_budget / len(text)

    ratio = target_ratio if target_ratio is not None else _target_ratio()
    ratio = max(0.05, min(0.95, ratio))

    # Skip compression if text is short enough
    if len(text) < 200:
        return {"compressed": text, "ratio": 1.0, "original_len": len(text),
                "compressed_len": len(text), "method": "passthrough"}

    if not force_heuristic and _llmlingua_available():
        result = _compress_with_lingua(text, question=question, target_ratio=ratio)
    else:
        result = _compress_heuristic(text, target_ratio=ratio, question=question)

    result["original_len"] = len(text)
    result["compressed_len"] = len(result.get("compressed", ""))
    return result


def compress_rag_context(
    documents: list[str],
    query: str,
    *,
    token_budget: int = 1000,
    target_ratio: float | None = None,
) -> dict:
    """
    Compress a list of retrieved RAG documents for inclusion in a prompt.
    Keeps content most relevant to the query; removes redundant/low-info chunks.

    Args:
        documents:    List of retrieved document strings.
        query:        The user's question/task guiding compression.
        token_budget: Max tokens for output (default 1000).
        target_ratio: Alternative to token_budget.

    Returns:
        {
            "compressed": str,       # Ready-to-include context string
            "ratio": float,
            "method": str,
            "docs_in": int,
            "docs_out": int,         # Approx doc count in compressed output
        }
    """
    if not documents:
        return {"compressed": "", "ratio": 1.0, "method": "passthrough", "docs_in": 0, "docs_out": 0}

    if _llmlingua_available() and len(documents) > 1:
        result = _compress_rag_with_lingua(documents, query, token_budget=token_budget,
                                           target_ratio=target_ratio or _target_ratio())
    else:
        merged = "\n\n---\n\n".join(documents)
        if target_ratio:
            result = compress(merged, target_ratio=target_ratio, question=query)
        else:
            result = compress(merged, token_budget=token_budget, question=query)
        result["docs_in"] = len(documents)

    result.setdefault("docs_in", len(documents))
    result.setdefault("docs_out", result["docs_in"])
    return result


def compress_conversation_history(
    messages: list[dict],
    *,
    keep_recent: int = 4,
    token_budget: int = 2000,
) -> list[dict]:
    """
    Compress older conversation turns while keeping recent ones intact.

    Args:
        messages:    List of {"role": "user"|"assistant", "content": "..."} dicts.
        keep_recent: Number of most-recent messages to preserve uncompressed.
        token_budget: Total token budget for older messages.

    Returns:
        Compressed messages list (same structure, some content shortened).
    """
    if len(messages) <= keep_recent:
        return messages

    old = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    # Compress older messages
    compressed_old: list[dict] = []
    for msg in old:
        content = msg.get("content", "")
        if len(content) > 500:  # Only compress longer messages
            result = compress(
                content,
                target_ratio=0.4,
                token_budget=token_budget // max(1, len(old)),
            )
            compressed_old.append({**msg, "content": result["compressed"]})
        else:
            compressed_old.append(msg)

    return compressed_old + recent

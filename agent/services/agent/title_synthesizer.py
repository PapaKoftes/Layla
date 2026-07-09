"""Synthesize a short conversation title from the first exchange (ChatGPT/Claude-style).

The rail used to show a raw 40-char slice of message #1 (the operator's "timestamp bs"
complaint). This produces a crisp ~3-6 word topic title. Runs ASYNC after the first exchange
so it never taxes the turn (the local first-token floor is ~14s); on failure or when disabled,
the caller keeps the instant extractive title from conversations._auto_name_conversation.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("layla")

_MAX_TITLE_LEN = 60


def _clean_title(raw: str) -> str:
    """Strip the model's scaffolding (quotes, 'Title:', aspect tags, trailing punctuation)."""
    t = (raw or "").strip()
    if not t:
        return ""
    t = t.splitlines()[0].strip()                      # first line only
    t = re.sub(r"^(title|topic)\s*[:\-]\s*", "", t, flags=re.IGNORECASE).strip()
    t = t.strip("\"'`“”‘’ ")                            # surrounding quotes
    t = re.sub(r"\[[^\]]*\]", "", t).strip()            # any bracketed marker
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(" .,:;-—!?")
    if len(t) > _MAX_TITLE_LEN:
        t = t[:_MAX_TITLE_LEN].rsplit(" ", 1)[0].rstrip(" .,:;-—")
    # reject junk (empty, pure punctuation, or an echoed instruction)
    if not t or not re.search(r"[A-Za-z0-9]", t):
        return ""
    if re.search(r"\b(as an ai|i cannot|i can't|sure[,!]|here (is|are)|okay|user:|assistant:)\b", t, re.IGNORECASE):
        return ""
    return t[:1].upper() + t[1:]


def synthesize_conversation_title(user_msg: str, assistant_msg: str = "") -> str:
    """LLM-synthesized ~3-6 word title. Returns '' on any failure (caller keeps extractive)."""
    u = (user_msg or "").strip()
    a = (assistant_msg or "").strip()
    if not u and not a:
        return ""
    try:
        from services.llm.llm_gateway import run_completion
        prompt = (
            "Give a short 3-6 word title naming the TOPIC of this chat. "
            "No quotes, no trailing punctuation, no 'Title:' prefix. Just the title.\n\n"
            f"User: {u[:600]}\n"
            + (f"Assistant: {assistant_msg.strip()[:400]}\n" if assistant_msg.strip() else "")
            + "Title:"
        )
        # stream=True yields TOKEN STRINGS (what the rest of the codebase consumes). stream=False
        # returns an OpenAI-style dict {"id","object","choices",...}; ''.join()-ing that iterates
        # the dict KEYS → "idobjectchoices…" → the "IDObject" title bug. Always stream + join text.
        parts = []
        for tok in run_completion(prompt, max_tokens=16, temperature=0.3, stream=True, stop=["\n"]):
            if isinstance(tok, str):
                parts.append(tok)
            if sum(len(p) for p in parts) > 120:
                break
        return _clean_title("".join(parts))
    except Exception as exc:  # pragma: no cover - defensive; caller falls back
        logger.debug("title synthesis failed: %s", exc)
        return ""

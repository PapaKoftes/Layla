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
    # Reasoning-model <think>/<reasoning> traces leak into the title call too. Strip paired blocks
    # BEFORE the first-line cut (which would otherwise keep only "<think>"), plus a dangling opener
    # (stop=['\n'] cuts the title completion right after "<think>").
    t = re.sub(r"<(think|thinking|reasoning|scratchpad|reflection)\b[^>]*>.*?</\1\s*>", "", t, flags=re.IGNORECASE | re.DOTALL).strip()
    t = re.sub(r"<(?:think|thinking|reasoning|scratchpad|reflection)\b[^>]*>.*\Z", "", t, flags=re.IGNORECASE | re.DOTALL).strip()
    t = t.splitlines()[0].strip() if t else ""         # first line only
    t = re.sub(r"^(title|topic)\s*[:\-]\s*", "", t, flags=re.IGNORECASE).strip()
    t = t.strip("\"'`“”‘’ ")                            # surrounding quotes
    t = re.sub(r"\[[^\]]*\]", "", t).strip()            # any bracketed marker
    # A leaked leading aspect/persona label ("⚔ Morrigan: …", "Morrigan: …", "Layla: …") — the
    # title model echoes the speaker tag just like the reply model does. Strip an optional leading
    # sigil + optional name + colon/dash so the rail shows the topic, not the tag.
    # Reuse the robust backend leading-label stripper so the title path covers the SAME forms as the
    # reply path — markdown-wrapped ("**Morrigan:**", "## Morrigan", "> Morrigan:"), composite
    # ("Layla ⚔ Morrigan:"), sigil and dash — instead of a weaker hand-rolled regex that missed them.
    try:
        from services.agent.response_builder import _strip_leading_speaker_label as _sls
        t = _sls(t).strip()
    except Exception:
        t = re.sub(
            r"^\s*[⚔✦◎⚡⌖⊛]?\s*(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\s*[:\-–—]\s*",
            "", t, flags=re.IGNORECASE,
        ).strip()
    t = t.lstrip("⚔✦◎⚡⌖⊛ ").strip()                     # a bare leading sigil with no name
    # A bare role label ("Assistant:", "User:", "Human:") the title model echoes from the prompt
    # frame ("User: …\nAssistant: …\nTitle:"). It is NOT an aspect name, so _strip_leading_speaker_label
    # (name-gated) leaves it — strip it here so the rail shows the topic, not "Assistant: <topic>".
    t = re.sub(r"^\s*(?:assistant|user|human|system)\s*:\s*", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip(" .,:;-—!?")
    # A completion that is ONLY a bare aspect name — the 16-token title model echoed the speaker tag
    # ("Morrigan:" / "⚔ Morrigan:") with no topic after it. _strip_leading_speaker_label deliberately
    # does NOT nuke a label-only string (its "never nuke the whole reply" guard is right for REPLIES,
    # wrong for TITLES), so it survived to here as "Morrigan". Collapse it to "" so the caller keeps
    # the extractive title instead of showing the aspect name in the rail.
    if t and re.fullmatch(r"(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)", t, re.IGNORECASE):
        return ""
    if len(t) > _MAX_TITLE_LEN:
        t = t[:_MAX_TITLE_LEN].rsplit(" ", 1)[0].rstrip(" .,:;-—")
    # reject junk (empty, pure punctuation, or an echoed instruction)
    if not t or not re.search(r"[A-Za-z0-9]", t):
        return ""
    # Echoed-instruction / affirmation junk. Split from a single \b-wrapped alternation: a trailing
    # \b never matched the alternatives that END in punctuation ("assistant:", "user:", "sure!") —
    # a ':'/'!' → space transition is not a word boundary — so those forms silently leaked as titles.
    if re.search(r"\b(?:as an ai|i cannot|i can't|here (?:is|are)|okay)\b", t, re.IGNORECASE):
        return ""
    if re.match(r"^\s*(?:sure\s*[!,.]|user\s*:|assistant\s*:)", t, re.IGNORECASE):
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

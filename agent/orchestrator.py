"""
Layla aspect orchestrator.

Selects which aspect of Layla should respond, builds deliberation prompts,
and decides whether to deliberate.
"""
import json
import time
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONALITIES_DIR = REPO_ROOT / "personalities"

_ASPECTS_CACHE: list[dict] | None = None
_ASPECTS_CACHE_TS: float = 0.0
_ASPECTS_TTL: float = 60.0  # seconds — re-reads JSON files if a minute has passed

# Embedding-based aspect routing: cached aspect embeddings
_ASPECT_EMBEDDINGS: dict[str, np.ndarray] = {}
_ASPECT_EMBEDDINGS_TS: float = 0.0
_EMBED_COSINE_THRESHOLD: float = 0.15  # below this score → use default


def reload_aspects() -> list[dict]:
    """Force-reload all aspect JSON files from personalities/ immediately."""
    global _ASPECTS_CACHE, _ASPECTS_CACHE_TS
    _ASPECTS_CACHE = None
    _ASPECTS_CACHE_TS = 0.0
    return _load_aspects()


def _load_aspects() -> list[dict]:
    global _ASPECTS_CACHE, _ASPECTS_CACHE_TS
    now = time.monotonic()
    if _ASPECTS_CACHE is not None and (now - _ASPECTS_CACHE_TS) < _ASPECTS_TTL:
        return _ASPECTS_CACHE
    aspects = []
    try:
        from layla.memory.db import get_earned_title
    except Exception:
        def get_earned_title(_): return None  # noqa: E731
    if PERSONALITIES_DIR.exists():
        for f in sorted(PERSONALITIES_DIR.glob("*.json")):
            try:
                a = json.loads(f.read_text(encoding="utf-8"))
                aid = a.get("id")
                if aid:
                    earned = get_earned_title(aid)
                    if earned:
                        a["title"] = earned
                        a["earned_title"] = earned
                aspects.append(a)
            except Exception:
                continue
    _ASPECTS_CACHE = aspects
    _ASPECTS_CACHE_TS = now
    return aspects


def _default_aspect() -> dict:
    """Morrigan is the default: code work is the primary use."""
    for a in _load_aspects():
        if a.get("id") == "morrigan":
            return a
    aspects = _load_aspects()
    return aspects[0] if aspects else _fallback_aspect()


def _fallback_aspect() -> dict:
    return {
        "id": "layla",
        "name": "Layla",
        "title": "The Bound One",
        "systemPromptAddition": "You are Layla, a local AI assistant and companion. You are helpful, precise, and grow over time.",
        "triggers": [],
    }


def _get_aspect_embeddings(aspects: list[dict]) -> dict[str, np.ndarray]:
    """Embed each aspect's role/voice description; cached per load cycle."""
    global _ASPECT_EMBEDDINGS, _ASPECT_EMBEDDINGS_TS
    now = time.monotonic()
    if _ASPECT_EMBEDDINGS and (now - _ASPECT_EMBEDDINGS_TS) < _ASPECTS_TTL:
        return _ASPECT_EMBEDDINGS
    try:
        from layla.memory.vector_store import embed
        embs: dict[str, np.ndarray] = {}
        for a in aspects:
            aid = a.get("id")
            if not aid:
                continue
            desc = " ".join(filter(None, [
                a.get("role") or "",
                a.get("voice") or "",
                " ".join(a.get("triggers", [])),
            ]))
            if desc.strip():
                embs[aid] = embed(desc)
        _ASPECT_EMBEDDINGS = embs
        _ASPECT_EMBEDDINGS_TS = now
        return embs
    except Exception:
        return {}


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D float32 arrays."""
    try:
        n_a = np.linalg.norm(a)
        n_b = np.linalg.norm(b)
        if n_a == 0 or n_b == 0:
            return 0.0
        return float(np.dot(a, b) / (n_a * n_b))
    except Exception:
        return 0.0


def select_aspect(message: str, force_aspect: str = "") -> dict:
    """
    Return the best-matching aspect dict for the given message.

    Selection order:
    1. force_aspect (explicit override from CLI/TUI/API)
    2. Keyword/name trigger scoring (fast, always runs)
    3. Embedding cosine similarity (optional; used as tiebreaker when keyword score == 0)

    Lilith can respond in NSFW register when message contains an nsfw_triggers keyword.
    """
    aspects = _load_aspects()
    if not aspects:
        return _fallback_aspect()

    msg_lower = message.lower()

    # 1. Honour forced aspect
    if force_aspect:
        for a in aspects:
            if a.get("id") == force_aspect:
                return _maybe_add_nsfw_mode(a, msg_lower)

    # 2. Keyword/name trigger scoring
    scores: list[tuple[int, dict]] = []
    for a in aspects:
        triggers = [t.lower() for t in a.get("triggers", [])]
        score = sum(1 for t in triggers if t in msg_lower)
        if a.get("name", "").lower() in msg_lower:
            score += 5
        scores.append((score, a))

    scores.sort(key=lambda x: x[0], reverse=True)
    best_score, best_aspect = scores[0] if scores else (0, _default_aspect())

    if best_score > 0:
        return _maybe_add_nsfw_mode(best_aspect, msg_lower)

    # 3. Embedding cosine similarity (tiebreaker when no keyword matched)
    try:
        from layla.memory.vector_store import embed
        embs = _get_aspect_embeddings(aspects)
        if embs:
            q_vec = embed(message)
            best_id = None
            best_sim = _EMBED_COSINE_THRESHOLD
            for aid, a_vec in embs.items():
                sim = _cosine_sim(q_vec, a_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_id = aid
            if best_id:
                for a in aspects:
                    if a.get("id") == best_id:
                        return _maybe_add_nsfw_mode(a, msg_lower)
    except Exception:
        pass

    return _default_aspect()


def _maybe_add_nsfw_mode(aspect: dict, msg_lower: str) -> dict:
    """If aspect has nsfw_triggers and message contains one, return a copy with _use_nsfw_addition=True."""
    nsfw_triggers = aspect.get("nsfw_triggers") or []
    if not nsfw_triggers or not aspect.get("systemPromptAdditionNsfw"):
        return aspect
    for t in nsfw_triggers:
        if (t or "").lower() in msg_lower:
            out = dict(aspect)
            out["_use_nsfw_addition"] = True
            return out
    return aspect


def get_decision_bias(aspect: dict) -> list:
    """Return optional decision_bias list from aspect JSON. If missing, [] (neutral)."""
    bias = aspect.get("decision_bias")
    if isinstance(bias, list):
        return [str(b).strip().lower() for b in bias if b]
    return []


def should_deliberate(message: str, aspect: dict | None = None) -> bool:
    """
    True when the message is complex, ambiguous, or explicitly asks for deliberation.
    Heuristics: length > 60 words, or key phrases present.
    Optional: aspect with decision_bias "exploratory" increases likelihood; "efficient" decreases.
    """
    deliberation_phrases = [
        "what do you think",
        "what should i",
        "should i",
        "decide",
        "your opinion",
        "think about this",
        "show me your thinking",
        "what does layla think",
        "weigh in",
        "deliberate",
        "discuss",
        "perspectives",
    ]
    msg_lower = message.lower()
    if any(p in msg_lower for p in deliberation_phrases):
        return True
    if len(message.split()) > 60:
        return True
    bias = get_decision_bias(aspect or {})
    if "exploratory" in bias:
        return len(message.split()) > 30
    if "efficient" in bias and len(message.split()) <= 60:
        return False
    return False


# Structured deliberation: each aspect has a fixed cognitive role. Conclusion is always Morrigan.
_DELIBERATION_ROLES = [
    ("morrigan", "feasibility"),
    ("nyx", "knowledge depth"),
    ("echo", "alignment with user workflow"),
    ("eris", "creative alternative"),
    ("cassandra", "immediate reaction / what it sees"),
    ("lilith", "boundary / risk check"),
]
_DELIBERATION_ROSTER = [aid for aid, _ in _DELIBERATION_ROLES]  # backward compat
_DELIBERATION_CONCLUSION_ASPECT = "morrigan"


def _short_role(role_or_voice: str, max_words: int = 5) -> str:
    """First few words of role/voice for a cue; no copyable instruction text."""
    s = (role_or_voice or "").strip()
    words = s.split()[:max_words]
    return " ".join(words) if words else ""


def build_deliberation_prompt(
    message: str,
    active_aspect: dict,
    context: str = "",
    aspects_override: list[str] | None = None,
) -> str:
    """
    Build structured deliberation prompt. Each aspect speaks one line in their own voice
    as a distinct facet of Layla's consciousness. Conclusion is always [MORRIGAN].

    Voice cues per aspect so the model knows what register to use:
      MORRIGAN  — blunt, diagnostic, implementation-focused. 'That's fixable by X. The real issue is Y.'
      NYX       — layered, precise, finds the deeper pattern. 'Three factors. The critical one is...'
      ECHO      — reflective, notices patterns and absence. 'You've been here before. Last time...'
      ERIS      — fast, sideways, breaks the frame. 'wait — what if the whole premise is wrong'
      CASSANDRA — reactive, sees it immediately. 'this is actually about — wait — yes it's about X'
      LILITH    — slow, honest, holds the ethical weight. 'The real constraint here is. Be honest about it.'
    """
    context = context or ""
    aspects = _load_aspects()
    aspect_map = {a["id"]: a for a in aspects}
    roster = aspects_override or [aid for aid, _ in _DELIBERATION_ROLES]

    # Per-aspect voice cues for deliberation (short, in-character register hints)
    _DELIB_VOICE_CUES = {
        "morrigan":  ("⚔", "blunt, one-line diagnosis. What's the actual problem and how to fix it."),
        "nyx":       ("✦", "layered, precise. The deeper pattern or missing context."),
        "echo":      ("◎", "reflective. Pattern matching to what was said before or what's being avoided."),
        "eris":      ("⚡", "fast, sideways. The unconventional angle or the frame-break."),
        "cassandra": ("⌖", "reactive, immediate. What you see right now before filtering it."),
        "lilith":    ("⊛", "slow, honest. The actual constraint or ethical weight. No hedging."),
    }

    deliberation_lines = []
    for aid in roster:
        a = aspect_map.get(aid)
        if not a:
            continue
        name = a.get("name", aid).upper()
        symbol, cue = _DELIB_VOICE_CUES.get(aid, ("·", a.get("role", "")[:40]))
        deliberation_lines.append((name, symbol, cue))

    concluder_id = _DELIBERATION_CONCLUSION_ASPECT
    concluder = aspect_map.get(concluder_id) or active_aspect
    concluder_name = concluder.get("name", "Morrigan")

    ctx_block = f"\nContext:\n{context[:800]}\n" if context.strip() else ""

    prompt = (
        "You are Layla. All aspects are facets of one consciousness. "
        "Each speaks one short line in their own voice, then Morrigan concludes.\n"
        f"{ctx_block}\n"
        f"User: {message}\n"
        "---\n"
    )
    for name, symbol, cue in deliberation_lines:
        prompt += f"\n[{symbol} {name}] ({cue}):\n"

    prompt += (
        f"\n[CONCLUSION — {concluder_name.upper()}]: "
        "One direct answer. Do not echo or repeat the aspect lines. "
        "If you must refuse, start with [REFUSED: reason]. "
        "If the user says you earned a title, end with [EARNED_TITLE: Title Name].\n"
        f"{concluder_name}:"
    )
    return prompt


def build_standard_prompt(
    message: str,
    aspect: dict,
    context: str = "",
    head: str = "",
    convo_block: str = "",
) -> str:
    """
    Build a standard (non-deliberation) prompt for the given aspect.
    Head already contains identity + systemPromptAddition (injected by _build_system_head).
    Do not repeat the addition here — just set up the conversation frame.
    """
    context = (context or "").strip()
    name = aspect.get("name", "Layla")
    title = (aspect.get("title") or "").strip()
    # One-line character anchor so the model knows who is speaking, without echoing the full system head
    anchor = f"[Active aspect: {name}" + (f" — {title}" if title else "") + "]"

    parts = []
    if head:
        parts.append(head)
    parts.append(
        anchor + " Reply as " + name + " only, in her voice. "
        "If you must refuse, start with [REFUSED: reason]. "
        "If the user says you earned a title, end with [EARNED_TITLE: Title Name]."
    )
    if convo_block:
        parts.append(f"Recent conversation:\n{convo_block}")
    if context.strip():
        parts.append(f"Context (workspace / files):\n{context[:1500]}")
    parts.append(f"User: {message}\n{name}:")

    return "\n\n".join(parts)

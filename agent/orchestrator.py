"""
Layla aspect orchestrator.

Selects which aspect of Layla should respond, builds deliberation prompts,
and decides whether to deliberate.
"""
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONALITIES_DIR = REPO_ROOT / "personalities"

_ASPECTS_CACHE: list[dict] | None = None
_ASPECTS_CACHE_TS: float = 0.0
_ASPECTS_TTL: float = 60.0  # seconds — re-reads JSON files if a minute has passed


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
        from jinx.memory.db import get_earned_title
    except Exception:
        get_earned_title = lambda _: None
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


def select_aspect(message: str, force_aspect: str = "") -> dict:
    """
    Return the best-matching aspect dict for the given message.

    force_aspect: if provided, load that aspect by id directly.
    Lilith can respond in NSFW register when message contains an nsfw_triggers keyword (e.g. intimate, nsfw).
    """
    aspects = _load_aspects()
    if not aspects:
        return _fallback_aspect()

    msg_lower = message.lower()

    # Honour forced aspect (e.g. from /aspect command in TUI/CLI)
    if force_aspect:
        for a in aspects:
            if a.get("id") == force_aspect:
                return _maybe_add_nsfw_mode(a, msg_lower)

    # Score each aspect by trigger matches
    scores: list[tuple[int, dict]] = []
    for a in aspects:
        triggers = [t.lower() for t in a.get("triggers", [])]
        score = sum(1 for t in triggers if t in msg_lower)
        # Exact name match is worth extra
        if a.get("name", "").lower() in msg_lower:
            score += 5
        scores.append((score, a))

    scores.sort(key=lambda x: x[0], reverse=True)

    # If best score > 0, use it; otherwise default
    best_score, best_aspect = scores[0] if scores else (0, _default_aspect())
    if best_score == 0:
        return _default_aspect()
    return _maybe_add_nsfw_mode(best_aspect, msg_lower)


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
    Build structured decision reasoning: [MORRIGAN] feasibility, [NYX] knowledge depth,
    [ECHO] alignment with user workflow, [ERIS] creative alternative, [LILITH] boundary/risk.
    Conclusion remains [MORRIGAN].
    """
    context = context or ""
    aspects = _load_aspects()
    aspect_map = {a["id"]: a for a in aspects}
    roster = aspects_override or [aid for aid, _ in _DELIBERATION_ROLES]
    role_by_id = {aid: label for aid, label in _DELIBERATION_ROLES}

    deliberation_lines = []
    for aid in roster:
        a = aspect_map.get(aid)
        if not a:
            continue
        name = a.get("name", aid).upper()
        role_label = role_by_id.get(aid) or (a.get("role") or "")[:30]
        deliberation_lines.append(f"[{name}] {role_label}:")

    concluder_id = _DELIBERATION_CONCLUSION_ASPECT
    concluder = aspect_map.get(concluder_id) or active_aspect
    concluder_name = concluder.get("name", "Morrigan")

    ctx_block = f"\nContext:\n{context[:800]}\n" if context.strip() else ""

    prompt = (
        "You are Layla. Each aspect contributes one short line; then you answer as Morrigan.\n"
        f"{ctx_block}\n"
        "---\n"
    )
    for line in deliberation_lines:
        prompt += f"\n{line}\n"

    prompt += (
        "\n[CONCLUSION — MORRIGAN]: Give one direct answer to the user. Do not repeat the aspect lines above.\n"
        "If you must refuse, start with [REFUSED: reason]. "
        "If the user says you earned a title, end with [EARNED_TITLE: Title Name].\n"
        f"User: {message}\n"
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
    Head already contains identity + this aspect's systemPromptAddition; do not repeat it
    to avoid the model echoing instructions.
    """
    context = (context or "").strip()
    name = aspect.get("name", "Layla")

    parts = []
    if head:
        parts.append(head)
    parts.append(
        "Reply as " + name + " only. "
        "If you must refuse, start with [REFUSED: reason]. "
        "If the user says you earned a title, end with [EARNED_TITLE: Title Name]."
    )
    if convo_block:
        parts.append(f"Recent conversation:\n{convo_block}")
    if context.strip():
        parts.append(f"Context (workspace / files):\n{context[:1500]}")
    parts.append(f"User: {message}\n{name}:")

    return "\n\n".join(parts)

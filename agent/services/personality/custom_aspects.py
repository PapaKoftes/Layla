"""Custom (user-created) aspects — REQ-79 / BL-092.

Additive layer over the 6 built-in aspects: a custom aspect is a NAMED persona that inherits
behaviour/voice/model from a `base_aspect` (one of the 6) and overrides its name, sigil (symbol),
tagline, accent colour, and a prompt hint. Persisted as `user_identity` keys `custom_aspect_<id>`
→ JSON, so there is no new table/migration and nothing about the 6 built-ins changes. Resolution
(`character_creator.load_aspect_profile` / `all_aspect_ids`) is what layers these in.

BL-301b — CUSTOM ASPECTS ARE FIRST-CLASS. They used to be resolvable from exactly one place: the
create-overlay's "talk as this" button. Everything else — the sidebar aspect bar, `@mention`,
`/aspects/{id}`, the OpenAI-compat model list — read `orchestrator._load_aspects()`, which was
built only from `personalities/*.json`, so a persona you had just created resolved NOWHERE by
name. `_load_aspects()` now merges these rows into that same roster, `aspect_roster()` is the
ordered list the UI renders, and `resolve_aspect_ref()` is the shared name→id resolver.

THE COLLISION RULE IS THE ORDER: the 6 built-ins are always first and every resolver takes the
first match, so a custom aspect can shadow neither a built-in id (rejected at creation AND dropped
at merge) nor a built-in display name.
"""
from __future__ import annotations

import json
import re
from typing import Any

_PREFIX = "custom_aspect_"
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_FIELDS = ("name", "title", "symbol", "tagline", "color_primary", "prompt_hint")

# Control characters (including the newlines that would break a one-line bar label or smuggle a
# fake `## SYSTEM` header into a prompt) are stripped from every free-text field.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"\s+")


def _clean(value: Any, limit: int) -> str:
    """Single-line, control-character-free, length-capped text."""
    s = _CTRL_RE.sub(" ", str(value or ""))
    return _WS_RE.sub(" ", s).strip()[:limit]


def _all_uid() -> dict[str, str]:
    try:
        from layla.memory.db import get_all_user_identity
        return get_all_user_identity() or {}
    except Exception:
        return {}


def list_custom_aspects() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k, v in _all_uid().items():
        if not k.startswith(_PREFIX):
            continue
        try:
            d = json.loads(v)
            if isinstance(d, dict) and d.get("id"):
                out.append(d)
        except Exception:
            continue
    return sorted(out, key=lambda d: d.get("name", d["id"]))


def custom_aspect_ids() -> list[str]:
    return [d["id"] for d in list_custom_aspects()]


def get_custom_aspect(aspect_id: str) -> dict[str, Any] | None:
    v = _all_uid().get(_PREFIX + str(aspect_id or "").strip().lower())
    if not v:
        return None
    try:
        d = json.loads(v)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def save_custom_aspect(spec: dict[str, Any]) -> dict[str, Any]:
    """Create/update a custom aspect. Rejects invalid ids and built-in collisions."""
    from services.personality.character_creator import ALL_ASPECTS

    spec = spec or {}
    aid = str(spec.get("id") or "").strip().lower()
    if not _ID_RE.match(aid):
        return {"ok": False, "error": "id must be lowercase, start with a letter, [a-z0-9_], 2-32 chars"}
    if aid in ALL_ASPECTS:
        return {"ok": False, "error": f"'{aid}' is a built-in aspect — pick another id"}
    base = str(spec.get("base_aspect") or "morrigan").strip().lower()
    if base not in ALL_ASPECTS:
        return {"ok": False, "error": f"base_aspect must be one of {list(ALL_ASPECTS)}"}
    # An all-whitespace / all-control-character name is not a name. Falling back to the id keeps
    # the aspect addressable in the bar and by @mention instead of rendering as a blank chip.
    # The 2-char floor matters beyond cosmetics: `select_aspect` scores +5 when an aspect's NAME
    # appears anywhere in the message, so a one-letter name would hijack routing on almost every
    # turn. The id (min 2 chars) is the fallback.
    name = _clean(spec.get("name"), 60)
    if len(name) < 2:
        name = aid.replace("_", " ").title()
    symbol = _clean(spec.get("symbol"), 8) or "✦"
    rec: dict[str, Any] = {
        "id": aid,
        "name": name,
        "title": _clean(spec.get("title"), 60),
        "symbol": symbol,
        "tagline": _clean(spec.get("tagline"), 200),
        "color_primary": _clean(spec.get("color_primary"), 32),
        # prompt_hint is a free-form multi-line instruction; keep its newlines, drop the other
        # control characters.
        "prompt_hint": _CTRL_RE.sub(lambda m: "\n" if m.group(0) == "\n" else " ",
                                    str(spec.get("prompt_hint") or "")).strip()[:2000],
        "base_aspect": base,
        "custom": True,
    }
    try:
        from layla.memory.db import set_user_identity
        set_user_identity(_PREFIX + aid, json.dumps(rec, ensure_ascii=False))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _invalidate_reply_name_cache()  # so the reply-cleaner strips this new name immediately
    _invalidate_aspect_roster()     # so the bar / @mention / forced-aspect resolve it NOW
    return {"ok": True, "aspect": rec}


def _invalidate_reply_name_cache() -> None:
    """Tell the reply-cleaner to re-read the custom-aspect display names (leading-label strip)."""
    try:
        from services.agent.response_builder import reset_custom_aspect_name_cache
        reset_custom_aspect_name_cache()
    except Exception:
        pass


def _invalidate_aspect_roster() -> None:
    """Drop the orchestrator's aspect cache so a create/delete is visible immediately.

    `orchestrator._load_aspects()` caches for 60s and is the roster the aspect bar, @mention
    resolution and the forced-aspect path all read. Without this, a just-created custom aspect
    stayed unresolvable for up to a minute — the exact "I made it and nothing knows about it"
    symptom this feature is meant to remove.
    """
    try:
        import orchestrator
        orchestrator.invalidate_aspects_cache()
    except Exception:
        pass


def delete_custom_aspect(aspect_id: str) -> bool:
    # delete_user_identity lives in user_profile (db.py doesn't re-export it).
    try:
        from layla.memory.user_profile import delete_user_identity
        ok = bool(delete_user_identity(_PREFIX + str(aspect_id or "").strip().lower()))
        _invalidate_reply_name_cache()
        _invalidate_aspect_roster()
        return ok
    except Exception:
        return False


# ── Roster resolution (the aspect bar + @mention share this) ─────────────────

def aspect_roster() -> list[dict[str, Any]]:
    """The full aspect roster the UI renders: the 6 built-ins FIRST, then custom aspects.

    One list, one order, one collision rule — so the bar, the @mention dropdown and the backend
    all agree on what a name means. Built-ins are emitted in canonical `ALL_ASPECTS` order (which
    is the order the sidebar shows them in); `_load_aspects()` returns them in filename order,
    which is not the same thing and must not leak into a user-visible list.
    """
    try:
        from services.personality.character_creator import ALL_ASPECTS
    except Exception:
        ALL_ASPECTS = ()  # noqa: N806
    try:
        import orchestrator
        loaded = orchestrator._load_aspects() or []
    except Exception:
        return []

    def _row(a: dict[str, Any]) -> dict[str, Any]:
        aid = str(a.get("id") or "").strip().lower()
        return {
            "id": aid,
            "name": str(a.get("name") or aid.title()),
            "symbol": str(a.get("symbol") or ""),
            "tagline": str(a.get("tagline") or ""),
            "custom": bool(a.get("custom")),
            "base_aspect": a.get("base_aspect"),
        }

    by_id: dict[str, dict[str, Any]] = {}
    customs: list[dict[str, Any]] = []
    for a in loaded:
        aid = str(a.get("id") or "").strip().lower()
        if not aid:
            continue
        if a.get("custom"):
            if aid not in ALL_ASPECTS:
                customs.append(_row(a))
        else:
            by_id.setdefault(aid, _row(a))

    rows = [by_id.pop(aid) for aid in ALL_ASPECTS if aid in by_id]
    rows.extend(by_id.values())   # any built-in not in ALL_ASPECTS still shows, just after
    rows.extend(customs)
    return rows


def resolve_aspect_ref(ref: str) -> str | None:
    """Resolve an @mention / aspect-bar reference (an id OR a display name) to an aspect id.

    ORDER IS THE COLLISION RULE. `aspect_roster()` puts the 6 built-ins first and we scan ids
    before names, so a custom aspect that happens to be *named* "Morrigan" resolves to itself only
    by its own id — `@morrigan` still reaches the built-in. Returns None for an unknown reference
    so a genuine typo is still reported as a miss rather than silently routed somewhere.
    """
    s = _clean(ref, 64).lstrip("@").strip().lower()
    if not s:
        return None
    roster = aspect_roster()
    for row in roster:
        if row["id"] == s:
            return row["id"]
    for row in roster:
        if str(row.get("name") or "").strip().lower() == s:
            return row["id"]
    return None


def apply_overrides(defaults: dict[str, Any], cust: dict[str, Any]) -> dict[str, Any]:
    """Layer a custom aspect's overrides onto its base_aspect defaults (in place)."""
    for k in _FIELDS:
        if cust.get(k):
            defaults[k] = cust[k]
    defaults["base_aspect"] = cust.get("base_aspect")
    defaults["custom"] = True
    return defaults

"""Custom (user-created) aspects — REQ-79 / BL-092.

Additive layer over the 6 built-in aspects: a custom aspect is a NAMED persona that inherits
behaviour/voice/model from a `base_aspect` (one of the 6) and overrides its name, sigil (symbol),
tagline, accent colour, and a prompt hint. Persisted as `user_identity` keys `custom_aspect_<id>`
→ JSON, so there is no new table/migration and nothing about the 6 built-ins changes. Resolution
(`character_creator.load_aspect_profile` / `all_aspect_ids`) is what layers these in.
"""
from __future__ import annotations

import json
import re
from typing import Any

_PREFIX = "custom_aspect_"
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_FIELDS = ("name", "title", "symbol", "tagline", "color_primary", "prompt_hint")


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
    rec: dict[str, Any] = {
        "id": aid,
        "name": (str(spec.get("name") or "").strip() or aid.title())[:60],
        "title": str(spec.get("title") or "").strip()[:60],
        "symbol": (str(spec.get("symbol") or "").strip() or "✦")[:8],
        "tagline": str(spec.get("tagline") or "").strip()[:200],
        "color_primary": str(spec.get("color_primary") or "").strip()[:32],
        "prompt_hint": str(spec.get("prompt_hint") or "").strip()[:2000],
        "base_aspect": base,
        "custom": True,
    }
    try:
        from layla.memory.db import set_user_identity
        set_user_identity(_PREFIX + aid, json.dumps(rec, ensure_ascii=False))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _invalidate_reply_name_cache()  # so the reply-cleaner strips this new name immediately
    return {"ok": True, "aspect": rec}


def _invalidate_reply_name_cache() -> None:
    """Tell the reply-cleaner to re-read the custom-aspect display names (leading-label strip)."""
    try:
        from services.agent.response_builder import reset_custom_aspect_name_cache
        reset_custom_aspect_name_cache()
    except Exception:
        pass


def delete_custom_aspect(aspect_id: str) -> bool:
    # delete_user_identity lives in user_profile (db.py doesn't re-export it).
    try:
        from layla.memory.user_profile import delete_user_identity
        ok = bool(delete_user_identity(_PREFIX + str(aspect_id or "").strip().lower()))
        _invalidate_reply_name_cache()
        return ok
    except Exception:
        return False


def apply_overrides(defaults: dict[str, Any], cust: dict[str, Any]) -> dict[str, Any]:
    """Layer a custom aspect's overrides onto its base_aspect defaults (in place)."""
    for k in _FIELDS:
        if cust.get(k):
            defaults[k] = cust[k]
    defaults["base_aspect"] = cust.get("base_aspect")
    defaults["custom"] = True
    return defaults

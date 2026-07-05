"""Multilingual response locale (BL-160) — Layla converses natively in any language.

Distinct from the language *tutor* (which teaches) and from German *mode* (a full immersion
tutor): this is the flagship companion simply *speaking the user's language*. A single
`response_language` setting injects a small system block telling Layla to reply in that
language while keeping her persona and every capability identical. Reuses the tutor's
language registry, so the set of supported languages stays single-sourced.
"""
from __future__ import annotations

from typing import Any

# a few common languages beyond the tutor set, so the companion isn't limited to teachable ones
_EXTRA = {
    "english": {"name": "English", "native": "English"},
    "dutch": {"name": "Dutch", "native": "Nederlands"},
    "japanese": {"name": "Japanese", "native": "日本語"},
    "arabic": {"name": "Arabic", "native": "العربية"},
    "mandarin": {"name": "Mandarin Chinese", "native": "中文"},
}


def _registry() -> dict[str, dict[str, Any]]:
    reg: dict[str, dict[str, Any]] = dict(_EXTRA)
    try:
        from services.infrastructure.language_tutor import LANGUAGES
        for k, v in LANGUAGES.items():
            reg[k] = {"name": v.get("name", k.title()), "native": v.get("native", v.get("name", k.title()))}
    except Exception:
        pass
    return reg


def supported_languages() -> list[dict[str, str]]:
    return [{"code": k, "name": v["name"], "native": v["native"]} for k, v in sorted(_registry().items())]


def normalize_language(language: str) -> str:
    """Accept a code, English name, or native name → canonical key, or '' for default."""
    q = (language or "").strip().lower()
    if not q or q in {"auto", "default", "english"}:
        return "" if q != "english" else "english"
    reg = _registry()
    if q in reg:
        return q
    for k, v in reg.items():
        if q in (v["name"].lower(), v["native"].lower()):
            return k
    return ""


def build_language_block(language: str) -> str:
    """A system-prompt block instructing Layla to converse in `language`. '' → no block."""
    key = normalize_language(language)
    if not key:
        return ""
    v = _registry()[key]
    native = v["native"]
    name = v["name"]
    return (
        f"## Language\n"
        f"The user prefers to converse in **{name}** ({native}). Respond in {native} by default — "
        f"naturally and fluently, as a native speaker would. Keep your persona, tone, and every "
        f"capability exactly the same; only the language changes. If the user writes to you in another "
        f"language or explicitly asks you to switch, follow their lead."
    )


def response_language_from_config(cfg: dict | None) -> str:
    if not isinstance(cfg, dict):
        return ""
    return str(cfg.get("response_language") or "").strip()

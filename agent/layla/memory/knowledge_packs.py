"""Knowledge-pack resolution (v1.7.5).

Turns the operator's ``knowledge_preset`` / ``knowledge_packs`` config into the concrete set
of enabled pack ids, and maps a knowledge file path to its pack. Pure + dependency-light
(reads knowledge/packs/presets.json; takes cfg as an argument) so low-level callers like
``runtime_safety.load_knowledge_docs`` can use it without an import cycle.

Design: docs/design/KNOWLEDGE_PRESETS.md. Default (nothing configured) = ALL packs enabled,
so behavior is unchanged until an operator opts into a preset.
"""
from __future__ import annotations

import json
from pathlib import Path

_PACKS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "knowledge" / "packs"

# Fallback presets if presets.json is missing (kept in sync with build_knowledge_registry.py).
_DEFAULT_PRESETS = {
    "companion": ["core"],
    "maker": ["core", "fabrication", "embedded", "engineering"],
    "engineer": ["core", "engineering", "reasoning"],
    "researcher": ["core", "research", "reasoning", "psychology"],
    "everything": ["core", "engineering", "fabrication", "embedded", "research",
                   "reasoning", "psychology", "ethics", "creative"],
}


def _load_presets() -> dict[str, list[str]]:
    try:
        p = _PACKS_DIR / "presets.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)}
    except Exception:
        pass
    return _DEFAULT_PRESETS


def resolve_enabled_packs(cfg: dict) -> set[str] | None:
    """Return the set of enabled pack ids, or ``None`` meaning "all packs" (the default).

    ``knowledge_packs`` (an explicit list) wins over ``knowledge_preset`` (a named bundle).
    ``core`` is always implicitly included. Unknown/empty config → None (all packs on).
    """
    try:
        packs = cfg.get("knowledge_packs")
        if isinstance(packs, list) and packs:
            return {str(p).strip().lower() for p in packs if str(p).strip()} | {"core"}
        preset = str(cfg.get("knowledge_preset") or "").strip().lower()
        if preset and preset not in ("", "all", "everything"):
            mapping = _load_presets()
            if preset in mapping:
                return {str(p).strip().lower() for p in mapping[preset]} | {"core"}
    except Exception:
        pass
    return None  # all packs (or loose docs) enabled


def pack_of(path: str | Path) -> str | None:
    """Return the pack id for a knowledge file under knowledge/packs/<id>/, else None.

    None means the file is a loose knowledge/ doc (not in a pack) — always kept, so an
    operator's own dropped-in files are never filtered out by preset selection.
    """
    try:
        parts = Path(path).resolve().parts
        if "packs" in parts:
            i = parts.index("packs")
            if i + 1 < len(parts):
                return parts[i + 1].lower()
    except Exception:
        pass
    return None


def is_doc_enabled(path: str | Path, enabled: set[str] | None) -> bool:
    """True if a knowledge file should be active given the enabled-pack set.

    ``enabled is None`` → everything on. Loose docs (pack_of == None) are always on.
    """
    if enabled is None:
        return True
    pk = pack_of(path)
    return pk is None or pk in enabled

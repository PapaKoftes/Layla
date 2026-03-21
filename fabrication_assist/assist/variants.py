"""Heuristic variant proposals from intent + optional domain YAML (no LLM on main)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

log = logging.getLogger("fabrication_assist.variants")


def _try_load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        log.warning("PyYAML not installed; skipping %s", path)
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("cannot read YAML %s: %s", path, e)
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        log.warning("invalid YAML skipped %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def load_knowledge_dir(directory: Path | None = None) -> dict[str, Any]:
    """Merge *.example.yaml (and *.yaml) from knowledge dir into one dict (shallow merge per file)."""
    d = directory or _KNOWLEDGE_DIR
    merged: dict[str, Any] = {}
    if not d.is_dir():
        return merged
    for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
        chunk = _try_load_yaml(p)
        for k, v in chunk.items():
            merged[k] = v
    return merged


def propose_variants(intent: dict[str, Any], knowledge: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Emit 2–3 variant dicts (connection / tolerance / material keys) from parsed intent.
    Uses optional knowledge blocks: materials, connection_hints, machining_rules.
    """
    k = knowledge or {}
    strategies = intent.get("strategies") or ["balanced"]
    if not isinstance(strategies, list):
        strategies = [strategies]

    materials = k.get("materials") or {}
    hints = k.get("connection_hints") or {}
    machining = k.get("machining_rules") or {}

    mat_keys = list(materials.keys()) if isinstance(materials, dict) else []
    conn_keys = list(hints.keys()) if isinstance(hints, dict) else []
    mach_keys = list(machining.keys()) if isinstance(machining, dict) else []

    variants: list[dict[str, Any]] = []

    # Variant 1: assembly-first
    variants.append(
        {
            "id": "v1_assembly",
            "label": "Assembly simplicity",
            "goal": intent.get("goal", "explore"),
            "strategy": "assembly_simplicity",
            "material": mat_keys[0] if mat_keys else "unspecified",
            "connection": conn_keys[0] if conn_keys else "unspecified",
            "tolerance_class": "standard",
            "machining_priority": mach_keys[0] if mach_keys else "general",
        }
    )

    # Variant 2: material efficiency
    variants.append(
        {
            "id": "v2_material",
            "label": "Material efficiency",
            "goal": intent.get("goal", "explore"),
            "strategy": "material_efficiency",
            "material": mat_keys[1] if len(mat_keys) > 1 else (mat_keys[0] if mat_keys else "unspecified"),
            "connection": conn_keys[1] if len(conn_keys) > 1 else (conn_keys[0] if conn_keys else "unspecified"),
            "tolerance_class": "loose",
            "machining_priority": mach_keys[1] if len(mach_keys) > 1 else (mach_keys[0] if mach_keys else "general"),
        }
    )

    # Variant 3: machining / precision tilt (or duplicate if user asked precision)
    if "precision" in strategies or "tight_tolerance" in strategies:
        tol = "tight"
    else:
        tol = "mixed"
    variants.append(
        {
            "id": "v3_machining",
            "label": "Machining / precision",
            "goal": intent.get("goal", "explore"),
            "strategy": "machining_time" if "speed" not in strategies else "fast_turn",
            "material": mat_keys[-1] if mat_keys else "unspecified",
            "connection": conn_keys[-1] if conn_keys else "unspecified",
            "tolerance_class": tol,
            "machining_priority": mach_keys[-1] if mach_keys else "general",
        }
    )

    # If user emphasized one strategy, reorder so matching variant is first
    primary = strategies[0] if strategies else ""
    for i, v in enumerate(variants):
        if primary and str(v.get("strategy", "")).startswith(str(primary).split("_")[0]):
            variants = [variants[i]] + [x for j, x in enumerate(variants) if j != i]
            break

    return variants[:3]

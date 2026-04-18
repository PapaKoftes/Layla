"""
Model selector for Layla installer.
Uses model_catalog.json and hardware info to recommend the best compatible model.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "models" / "model_catalog.json"

_RAM_HEADROOM = 0.9


def load_catalog() -> list[dict[str, Any]]:
    """Load model catalog from JSON."""
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        return data.get("models", [])
    except Exception:
        return []


def validate_catalog_entries(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Keep only entries usable for download/recommendation.
    Requires a fetch source (url or repo_id) and ram_required (or vram-only GPU rows).
    """
    out: list[dict[str, Any]] = []
    for m in raw:
        url = m.get("download_url") or m.get("url")
        repo_id = m.get("repo_id")
        if not url and not repo_id:
            logger.warning("[catalog] skip %r: no download_url/url or repo_id", m.get("name"))
            continue
        if m.get("ram_required") is None and m.get("vram_required") is None:
            logger.warning("[catalog] skip %r: missing ram_required/vram_required", m.get("name"))
            continue
        out.append(m)
    return out


def recommend_model(
    hardware_info: dict[str, Any],
    *,
    category_preference: str | None = None,
    interactive: bool = False,
) -> dict[str, Any] | None:
    """
    Recommend the best compatible model for the given hardware.

    Uses a safety margin: only models with mem requirement <= available * 0.9 (RAM or VRAM).

    Args:
        hardware_info: Output from detect_hardware() / hardware_probe.probe_hardware()
        category_preference: When set (e.g. \"general\", \"coding\"), prefer catalog entries
            with matching \"category\"; interactive mode falls back to the full catalog if empty.
        interactive: If True and no row fits the margin, fall back to smallest models in catalog.

    Returns:
        Best matching catalog entry, or None if no compatible model (non-interactive strict path).
    """
    raw = load_catalog()
    catalog = validate_catalog_entries(raw)
    if not catalog:
        logger.error("[catalog] No valid catalog entries after filtering (check model_catalog.json).")
        return None

    if category_preference:
        want = category_preference.strip().lower()
        filtered = [m for m in catalog if (m.get("category") or "").strip().lower() == want]
        if filtered:
            catalog = filtered
        elif interactive:
            logger.info("[catalog] category %r empty; falling back to full catalog (interactive)", want)
        else:
            return None

    ram_gb = float(hardware_info.get("ram_gb") or 0.0)
    vram_gb = float(hardware_info.get("vram_gb") or 0.0)
    accel = str(hardware_info.get("acceleration_backend") or "none").lower()
    gpu_name = str(hardware_info.get("gpu_name") or "").strip().lower()

    # Prefer VRAM sizing when a GPU is present (CUDA/ROCm/Metal or reported VRAM / GPU name).
    has_gpu = (
        accel not in ("none", "")
        or vram_gb > 0
        or (gpu_name and gpu_name not in ("none", "unknown", ""))
    )
    if has_gpu and vram_gb > 0:
        mem_key = "vram_required"
        effective_mem = vram_gb
    elif has_gpu:
        # GPU detected but VRAM unknown — size against RAM, same key family as CPU path.
        mem_key = "ram_required"
        effective_mem = ram_gb
    else:
        mem_key = "ram_required"
        effective_mem = ram_gb

    avail = effective_mem if effective_mem > 0 else ram_gb
    avail = max(avail, 1.0)
    mem_budget = max(avail * _RAM_HEADROOM, 0.5)

    compatible = [m for m in catalog if float(m.get(mem_key, 999) or 999) <= mem_budget]

    if not compatible:
        if interactive:
            compatible = sorted(catalog, key=lambda m: float(m.get(mem_key, 0) or 0))
            logger.warning(
                "[catalog] no model within %.0f%% headroom; using smallest entries (interactive)",
                _RAM_HEADROOM * 100,
            )
        else:
            return None

    # Sort: smallest memory requirement first (fits-first), then jinx, then Q4 in name
    def sort_key(m: dict[str, Any]) -> tuple:
        nm = (m.get("name") or "").lower()
        mem_req = float(m.get(mem_key, 0) or 0)
        jinx = 0 if m.get("family") == "jinx" else 1
        q4_boost = 0 if "q4" in nm else 1
        return (mem_req, jinx, q4_boost, nm)

    compatible.sort(key=sort_key)
    return compatible[0] if compatible else None

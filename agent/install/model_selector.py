"""
Model selector for Layla installer.
Uses model_catalog.json and hardware info to recommend the best compatible model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "models" / "model_catalog.json"


def load_catalog() -> list[dict[str, Any]]:
    """Load model catalog from JSON."""
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        return data.get("models", [])
    except Exception:
        return []


def recommend_model(hardware_info: dict[str, Any]) -> dict[str, Any] | None:
    """
    Recommend the best compatible model for the given hardware.

    Args:
        hardware_info: Output from hardware_probe.probe_hardware()

    Returns:
        Best matching catalog entry, or None if no compatible model.
    """
    catalog = load_catalog()
    if not catalog:
        return None

    ram_gb = hardware_info.get("ram_gb", 0.0)
    vram_gb = hardware_info.get("vram_gb", 0.0)
    accel = hardware_info.get("acceleration_backend", "none")

    # Effective memory: use VRAM if GPU, else RAM
    if accel != "none":
        effective_mem = vram_gb
        mem_key = "vram_required"
    else:
        effective_mem = ram_gb
        mem_key = "ram_required"

    # Filter compatible models (memory requirement <= available)
    # When effective_mem is 0 (e.g. Metal), use ram_gb as fallback
    avail = effective_mem if effective_mem > 0 else ram_gb
    avail = max(avail, 1.0)  # Assume at least 1GB
    compatible = [m for m in catalog if m.get(mem_key, 999) <= (avail or 999)]

    # If nothing fits: allow models up to 1.5x avail (tight fit for low-end PCs)
    if not compatible:
        slack = avail * 1.5
        compatible = [m for m in catalog if m.get(mem_key, 999) <= slack]

    # Last resort: pick smallest model regardless
    if not compatible:
        compatible = sorted(catalog, key=lambda m: m.get(mem_key, 0))

    # Prefer: jinx family first (Layla's default), then uncensored, then largest that fits
    def score(m: dict) -> tuple:
        jinx = 0 if m.get("family") == "jinx" else 1
        uncensored = 1 if m.get("uncensored") else 0
        mem_req = m.get(mem_key, 0)
        return (jinx, -uncensored, -mem_req)

    compatible.sort(key=score)
    return compatible[0] if compatible else None

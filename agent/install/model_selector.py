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


# ---------------------------------------------------------------------------
# Domain "kit" recommendation (hardware + domain + priority aware)
# ---------------------------------------------------------------------------
# Measured wisdom (4-core / 16GB / no-GPU box): a 7B-Q4 runs ~4-5 tok/s on CPU,
# memory-bandwidth-bound — so a 14B would be ~2 tok/s (unusable for interactive
# coding). On CPU-only, "best experience" is the best model that stays RESPONSIVE,
# not the biggest that fits. Above this size, CPU latency hurts UX badly.
_CPU_USABLE_MAX_B = 9.0      # billion params; ceiling for a good CPU-only experience
_BALANCED_TARGET_B = 7.0     # the CPU sweet spot for coding quality vs. speed

# domain -> catalog category
_DOMAIN_CATEGORY = {
    "coding": "coding", "code": "coding",
    "general": "general", "chat": "general",
    "reasoning": "reasoning", "math": "reasoning",
    "creative": "creative", "writing": "creative", "roleplay": "creative",
}


def load_catalog_full() -> dict[str, Any]:
    """Load the entire catalog document (models + _recommended_aspects + tiers)."""
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _params_b(m: dict[str, Any]) -> float:
    """Parse a model's parameter count in billions from its 'size' field ('7B', '360M')."""
    s = str(m.get("size") or "").strip().upper()
    try:
        if s.endswith("M"):
            return float(s[:-1]) / 1000.0
        if s.endswith("B"):
            return float(s[:-1])
    except ValueError:
        pass
    return 999.0


def _aspect_for_family(family: str, recommended: dict[str, Any]) -> str | None:
    """Map a model family to its best-affinity aspect (the domain personality)."""
    if not family:
        return None
    aspects = recommended.get(family.lower())
    if isinstance(aspects, list) and aspects:
        return str(aspects[0])
    return None


def recommend_kit(
    hardware_info: dict[str, Any],
    *,
    domain: str = "coding",
    prefer: str = "balanced",
) -> dict[str, Any] | None:
    """Recommend a complete domain *kit* for the detected hardware.

    Unlike :func:`recommend_model` (smallest-fits-first, safety-biased), this picks the
    best model for an *experience*: it respects a CPU usability ceiling, honors a
    quality/speed priority, pairs a speculative-draft model when it will help, and maps
    the domain to its affinity aspect (personality).

    Args:
        hardware_info: output of ``hardware_probe.probe_hardware()``.
        domain: e.g. ``"coding"`` (mapped to a catalog category).
        prefer: ``"quality"`` | ``"balanced"`` | ``"speed"``. On CPU-only, "quality" is
            still capped at the usable model size — a model too slow to use is not "best".

    Returns:
        ``{primary, draft, aspect, settings, rationale}`` or ``None`` if nothing fits.
    """
    doc = load_catalog_full()
    catalog = validate_catalog_entries(doc.get("models", []))
    recommended_aspects = doc.get("_recommended_aspects", {}) or {}
    if not catalog:
        return None

    category = _DOMAIN_CATEGORY.get(domain.strip().lower(), domain.strip().lower())
    in_domain = [m for m in catalog if (m.get("category") or "").lower() == category]
    pool = in_domain or catalog  # fall back to whole catalog if the domain is empty

    # --- hardware sizing (mirrors recommend_model) ---
    ram_gb = float(hardware_info.get("ram_gb") or 0.0)
    vram_gb = float(hardware_info.get("vram_gb") or 0.0)
    accel = str(hardware_info.get("acceleration_backend") or "none").lower()
    gpu_name = str(hardware_info.get("gpu_name") or "").strip().lower()
    has_gpu = accel not in ("none", "") or vram_gb > 0 or (gpu_name and gpu_name not in ("none", "unknown", ""))

    if has_gpu and vram_gb > 0:
        mem_key, avail = "vram_required", vram_gb
    else:
        mem_key, avail = "ram_required", ram_gb
    avail = max(avail, 1.0)
    budget = max(avail * _RAM_HEADROOM, 0.5)

    fits = [m for m in pool if float(m.get(mem_key, 999) or 999) <= budget]
    if not fits:
        # degrade gracefully to the smallest thing in the pool
        fits = sorted(pool, key=lambda m: _params_b(m))[:1]
        if not fits:
            return None

    # On CPU-only, exclude models too large to stay responsive (unless nothing smaller fits).
    usable = fits
    if not has_gpu:
        small_enough = [m for m in fits if _params_b(m) <= _CPU_USABLE_MAX_B]
        if small_enough:
            usable = small_enough

    pref = prefer.strip().lower()
    if pref == "speed":
        usable.sort(key=lambda m: (_params_b(m), (m.get("name") or "")))
    elif pref == "quality":
        usable.sort(key=lambda m: (-_params_b(m), (m.get("name") or "")))
    else:  # balanced: closest to the CPU sweet spot, ties → larger
        usable.sort(key=lambda m: (abs(_params_b(m) - _BALANCED_TARGET_B), -_params_b(m)))

    primary = usable[0]
    fam = (primary.get("family") or "").lower()

    # Speculative draft: a tiny SAME-FAMILY model accelerates a >=7B primary on CPU while
    # preserving its outputs. Cross-family drafts are unsafe (different tokenizer), so skip.
    draft = None
    if not has_gpu and _params_b(primary) >= 6.0 and pref != "speed":
        candidates = [m for m in catalog
                      if (m.get("family") or "").lower() == fam and _params_b(m) <= 1.5
                      and m.get("name") != primary.get("name")]
        candidates.sort(key=lambda m: _params_b(m))
        draft = candidates[0] if candidates else None

    n_gpu_layers = -1 if has_gpu else 0  # offload all if GPU, else pure CPU
    settings = {
        "n_gpu_layers": n_gpu_layers,
        "n_threads": int(hardware_info.get("physical_cores") or 4),
        "n_ctx": 8192 if _params_b(primary) <= 8 else 4096,
        "speculative_draft": (draft or {}).get("filename") if draft else None,
    }

    speed_note = ("GPU-accelerated" if has_gpu
                  else f"CPU-only (~{'5' if _params_b(primary) <= 8 else '2'} tok/s expected on this tier)")
    rationale = (
        f"domain={category}, prefer={pref}, {speed_note}. "
        f"Chose {primary.get('name')} ({primary.get('size')}) as the best "
        f"{'responsive' if not has_gpu else 'capable'} fit within {budget:.0f}GB."
        + (f" Paired draft {draft.get('name')} for ~1.5-2x speculative speedup." if draft else "")
    )

    return {
        "primary": primary,
        "draft": draft,
        "aspect": _aspect_for_family(fam, recommended_aspects),
        "settings": settings,
        "rationale": rationale,
    }

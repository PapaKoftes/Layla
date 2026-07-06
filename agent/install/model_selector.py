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


def _parse_size_b(size: str) -> float:
    """'7B'/'1.1B'/'20B' -> billions of params (for a quality proxy)."""
    try:
        return float(str(size or "0").upper().replace("B", "").strip())
    except Exception:
        return 0.0


def models_for_picker(
    ram_gb: float, vram_gb: float = 0.0, *, uncensored_first: bool = True,
) -> dict[str, Any]:
    """Full model catalog shaped for an install-time picker.

    Every entry is annotated with `viable` (fits this box's RAM/VRAM within headroom) and
    the list is ordered so the user sees the best choices first. With `uncensored_first`
    (the default — the operator wants a jailbroken model that answers everything), models
    with `uncensored: true` sort ahead of restricted ones; within that, viable-and-bigger
    (higher quality) first. `recommended` marks the best *uncensored, viable* pick — the
    largest that fits, so answers are as correct as possible while staying unrestricted.
    """
    budget = max(1.0, float(ram_gb or 0) ) * _RAM_HEADROOM
    vbudget = max(0.0, float(vram_gb or 0)) * _RAM_HEADROOM
    out: list[dict[str, Any]] = []
    for m in load_catalog():
        ram_req = float(m.get("ram_required", 999) or 999)
        vram_req = float(m.get("vram_required", 0) or 0)
        viable = ram_req <= budget or (vram_req > 0 and vram_req <= vbudget)
        out.append({
            "name": m.get("name", ""),
            "family": m.get("family", ""),
            "category": m.get("category", "general"),
            "size": m.get("size", ""),
            "size_b": _parse_size_b(m.get("size", "")),
            "quant": m.get("quant", ""),
            "ram_required": ram_req,
            "vram_required": vram_req,
            "uncensored": bool(m.get("uncensored", False)),
            "repo_id": m.get("repo_id", ""),
            "filename": m.get("filename", ""),
            "download_url": m.get("download_url", ""),
            "desc": m.get("desc", ""),
            "viable": viable,
        })

    def _sort_key(e: dict) -> tuple:
        unc = 0 if (uncensored_first and e["uncensored"]) else 1
        via = 0 if e["viable"] else 1
        # among viable, prefer bigger (better quality); among non-viable, prefer smaller.
        quality = -e["size_b"] if e["viable"] else e["size_b"]
        return (unc, via, quality, e["category"], e["name"])

    out.sort(key=_sort_key)

    # Recommended pick: the best *companion-suitable* uncensored model that fits AND stays
    # usable. Prefer general/creative/fast categories (a coder/reasoning model makes a poor
    # everyday companion), and — with no GPU — cap size to what's responsive on CPU while
    # still favouring the largest within that cap (quality). Falls back gracefully.
    _companion_cats = {"general", "creative", "fast"}
    _cpu_cap_b = _CPU_USABLE_MAX_B if not vbudget else 999.0
    _cands = [
        e for e in out
        if e["viable"] and e["uncensored"] and e["category"] in _companion_cats
        and (e["size_b"] <= _cpu_cap_b or e["size_b"] == 0)
    ]
    _cands.sort(key=lambda e: -e["size_b"])  # biggest usable = best quality
    recommended = (
        _cands[0]["filename"] if _cands
        else next((e["filename"] for e in out if e["viable"] and e["uncensored"]), None)
        or next((e["filename"] for e in out if e["viable"]), None)
    )
    for e in out:
        e["recommended"] = e["filename"] == recommended

    categories = sorted({e["category"] for e in out})

    # Hardware note (#24): warn honestly when the box is tight for the recommended pick,
    # so the installer doesn't silently ship a model that will thrash / trip the governor.
    note = ""
    rec_entry = next((e for e in out if e["recommended"]), None)
    any_unc_viable = any(e["viable"] and e["uncensored"] for e in out)
    if not vbudget:  # CPU-only box
        if not any_unc_viable:
            smallest_unc = min((e for e in out if e["uncensored"]), key=lambda e: e["ram_required"], default=None)
            need = int(smallest_unc["ram_required"]) if smallest_unc else 6
            note = (f"No uncensored model fits ~{ram_gb:.0f} GB RAM — the smallest needs ~{need} GB. "
                    f"Close other apps to free RAM, or pick a smaller (possibly restricted) model.")
        elif rec_entry and (ram_gb - rec_entry["ram_required"]) < 4:
            note = (f"The recommended uncensored model needs ~{int(rec_entry['ram_required'])} GB of your "
                    f"~{ram_gb:.0f} GB — it will fit but run slowly on CPU and needs headroom "
                    f"(close other apps). A smaller model is snappier.")
        elif rec_entry:
            note = "CPU-only: responses take tens of seconds to a couple of minutes; that's normal without a GPU."

    return {
        "models": out,
        "recommended": recommended,
        "categories": categories,
        "uncensored_first": uncensored_first,
        "ram_gb": ram_gb,
        "vram_gb": vram_gb,
        "hardware_note": note,
    }


def recommend_uncensored_model(ram_gb: float, vram_gb: float = 0.0) -> dict[str, Any] | None:
    """The best uncensored model that fits this box (largest viable uncensored)."""
    picker = models_for_picker(ram_gb, vram_gb, uncensored_first=True)
    for e in picker["models"]:
        if e["viable"] and e["uncensored"]:
            return e
    return None


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
    if not compatible:
        return None
    # REQ-85: benchmark-driven selection — when this box has already measured some of the
    # memory-compatible models, prefer the best-measured one (quality then speed) over the
    # static fits-first heuristic. No stored benchmarks ⇒ this is a no-op (fits-first stands).
    best = _benchmark_preferred(compatible)
    return best if best is not None else compatible[0]


def _benchmark_preferred(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Among candidates, the one with the best stored benchmark (pass@1, then tok/s)."""
    try:
        from services.llm.model_benchmark import get_all_benchmarks
        marks = get_all_benchmarks() or {}
    except Exception:
        return None
    if not marks:
        return None

    def _score(m: dict) -> tuple | None:
        for key in ((m.get("filename") or ""), (m.get("name") or "")):
            b = marks.get(key)
            if isinstance(b, dict):
                return (float(b.get("pass_at_1", 0) or 0), float(b.get("tok_per_s", 0) or 0))
        return None

    scored = [(c, _score(c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s is not None]
    if not scored:
        return None
    scored.sort(key=lambda cs: cs[1], reverse=True)
    return scored[0][0]


# ---------------------------------------------------------------------------
# Domain "kit" recommendation (hardware + domain + priority aware)
# ---------------------------------------------------------------------------
# Measured wisdom (4-core / 16GB / no-GPU box): a 7B-Q4 runs ~4-5 tok/s on CPU,
# memory-bandwidth-bound — so a 14B would be ~2 tok/s (unusable for interactive
# coding). On CPU-only, "best experience" is the best model that stays RESPONSIVE,
# not the biggest that fits. Above this size, CPU latency hurts UX badly.
_CPU_USABLE_MAX_B = 9.0      # billion params; ceiling for a good CPU-only experience
_BALANCED_TARGET_B = 7.0     # the CPU sweet spot for coding quality vs. speed
_LITE_TARGET_B = 3.0         # constrained/older-CPU sweet spot (Castilla default)

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
    elif pref == "lite":  # constrained box (older CPU / tight disk): target ~3B, ties -> smaller
        usable.sort(key=lambda m: (abs(_params_b(m) - _LITE_TARGET_B), _params_b(m)))
    else:  # balanced: closest to the CPU sweet spot, ties → larger
        usable.sort(key=lambda m: (abs(_params_b(m) - _BALANCED_TARGET_B), -_params_b(m)))

    primary = usable[0]
    fam = (primary.get("family") or "").lower()

    # Same-family tiny model that *could* serve as a speculative-decoding draft (a
    # cross-family draft is unsafe — different tokenizer). We surface it as a candidate,
    # but only auto-ENABLE it where it's known to pay off.
    draft_candidate = None
    if _params_b(primary) >= 6.0:
        cands = [m for m in catalog
                 if (m.get("family") or "").lower() == fam and _params_b(m) <= 1.5
                 and m.get("name") != primary.get("name")]
        cands.sort(key=lambda m: _params_b(m))
        draft_candidate = cands[0] if cands else None

    # MEASURED (4-core/16GB CPU): speculative decoding does NOT help on pure CPU —
    # prompt-lookup ran *slower* (1.6 vs 2.6 tok/s) because the bottleneck is memory
    # bandwidth, not compute, so the draft/verify cycle is pure overhead. Only enable a
    # draft when a GPU makes it worthwhile; on CPU the real levers are a smaller model
    # or a GPU. (Keep the candidate exposed for users who want to A/B it on their box.)
    draft = draft_candidate if (has_gpu and pref != "speed") else None

    settings = {
        "n_gpu_layers": -1 if has_gpu else 0,  # offload all if GPU, else pure CPU
        "n_threads": int(hardware_info.get("physical_cores") or 4),
        "n_ctx": 8192 if _params_b(primary) <= 8 else 4096,
        "speculative_draft": (draft or {}).get("filename") if draft else None,
    }

    if has_gpu:
        speed_note = "GPU-accelerated"
    else:
        speed_note = (f"CPU-only (~{'5' if _params_b(primary) <= 8 else '2'} tok/s on this tier; "
                      "speculative decoding measured unhelpful on CPU)")
    rationale = (
        f"domain={category}, prefer={pref}, {speed_note}. "
        f"Chose {primary.get('name')} ({primary.get('size')}) as the best "
        f"{'responsive' if not has_gpu else 'capable'} fit within {budget:.0f}GB."
        + (f" Enabled draft {draft.get('name')} (GPU speculative decoding)." if draft else "")
    )

    too_heavy = (not has_gpu) and _params_b(primary) > _CPU_USABLE_MAX_B
    if too_heavy:
        rationale += (f" WARNING: smallest {category} model is {primary.get('size')} — too heavy for "
                      "CPU-only; expect <2 tok/s. Provision only if you accept that, or use a GPU.")
    return {
        "primary": primary,
        "draft": draft,                     # auto-enabled draft (GPU only); None on CPU
        "draft_candidate": draft_candidate,  # same-family tiny available to A/B test
        "aspect": _aspect_for_family(fam, recommended_aspects),
        "settings": settings,
        "rationale": rationale,
        "too_heavy": too_heavy,             # CPU-only + over the usability ceiling
    }


# Aspect (personality) -> domain (catalog category). Each personality can provision its
# own domain-optimized model. Spanish/other-language users can add a small language helper.
_ASPECT_DOMAIN = {
    "morrigan": "coding",      # the architect / coder
    "nyx": "reasoning",        # logic, math, step-by-step
    "cassandra": "reasoning",  # research / analysis
    "echo": "general",         # everyday chat
    "eris": "creative",        # writing / ideas
    "lilith": "creative",
}


def recommend_aspect_kit(aspect: str, hardware_info: dict, *, prefer: str = "lite") -> dict | None:
    """Recommend a kit for a specific personality, using its domain (Castilla: per-aspect models)."""
    domain = _ASPECT_DOMAIN.get(str(aspect).lower(), "general")
    return recommend_kit(hardware_info, domain=domain, prefer=prefer)


def recommend_language_assist(hardware_info: dict) -> dict | None:
    """Smallest MULTILINGUAL general model — a translation/intent helper for non-English users.

    Returns a catalog entry (not a full kit): a tiny model that understands the user's
    language, extracts intent, and conveys it for the task model. None if none fits.
    """
    doc = load_catalog_full()
    cat = validate_catalog_entries(doc.get("models", []))
    multiling = [m for m in cat if m.get("multilingual") and (m.get("category") in ("general", "fast"))]
    ram = float(hardware_info.get("ram_gb") or 0.0)
    budget = max(ram * _RAM_HEADROOM, 0.5) if ram else 999
    fits = [m for m in multiling if float(m.get("ram_required", 999) or 999) <= budget]
    pool = fits or multiling
    if not pool:
        return None
    pool.sort(key=_params_b)  # smallest first — it's a lightweight helper
    return pool[0]

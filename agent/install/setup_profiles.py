"""
setup_profiles.py — intent-driven Setup & Profiles (W-S keystone, BL-200/201/207).

Onboarding asks "what do you want to do?" (a use-case PROFILE) and "which extras?" (the
optional FEATURE_MANIFEST). Resolving those yields a startup default config that enables
only the tools/features you need — the potato win — and tells the installer which deps/
models to fetch. Feature UIs and tool visibility read the resulting flags.

Pure data + resolution (no I/O) so it unit-tests without an app or model.
"""
from __future__ import annotations

# Each optional feature: the config flag(s) it sets when enabled, extra pip deps + models
# it needs (so onboarding can install on demand, BL-204), an approx download size, and
# what it unlocks. `id` is stable (referenced by profiles + the UI).
FEATURE_MANIFEST = [
    {"id": "voice", "label": "Voice (speak & listen)",
     "flags": {"voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True},
     "deps": ["faster-whisper", "kokoro-onnx"], "models": ["whisper-base", "kokoro"], "size_mb": 500,
     "unlocks": "voice input + spoken replies"},
    {"id": "mcp", "label": "MCP plugins",
     "flags": {"mcp_client_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "external MCP tool servers"},
    {"id": "search_elastic", "label": "Elasticsearch memory search",
     "flags": {"elasticsearch_enabled": True}, "deps": ["elasticsearch"], "models": [], "size_mb": 0,
     "unlocks": "advanced learning search (needs a running Elasticsearch)"},
    {"id": "search_meili", "label": "Meilisearch indexing",
     "flags": {"meilisearch_enabled": True}, "deps": ["meilisearch"], "models": [], "size_mb": 0,
     "unlocks": "fast full-text search (needs a running Meilisearch)"},
    {"id": "discord", "label": "Discord bot",
     "flags": {"discord_bot_autostart": True}, "deps": ["discord.py"], "models": [], "size_mb": 0,
     "unlocks": "chat with Layla from Discord"},
    {"id": "fabrication", "label": "Geometry / CAD (fabrication)",
     # geometry_frameworks_enabled is a PER-BACKEND dict (the backends do enabled.get("cadquery",…));
     # a bare bool would crash them (bool has no .get). Enable all three backends.
     "flags": {"geometry_frameworks_enabled": {"cadquery": True, "trimesh": True, "openscad": True, "ezdxf": True}},
     "deps": ["cadquery", "trimesh", "ezdxf"], "models": [], "size_mb": 200,
     "unlocks": "the FabricationAssist / geometry tools"},
    {"id": "remote", "label": "Remote access (phone / other devices)",
     "flags": {"remote_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "tunnel / Tailscale access (audit auto-on)"},
    {"id": "hyde", "label": "HyDE retrieval (better recall)",
     "flags": {"hyde_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "hypothetical-answer retrieval"},
    {"id": "initiative", "label": "Proactive initiative",
     "flags": {"initiative_engine_enabled": True, "inline_initiative_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "Layla suggests next steps on her own"},
    {"id": "engineering", "label": "Engineering pipeline",
     "flags": {"engineering_pipeline_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "structured multi-step engineering tasks"},
    {"id": "ml_stack", "label": "Full ML stack (rerankers, best embeddings)",
     "flags": {"embedder_prefer_quality": True}, "deps": ["torch", "sentence-transformers", "flashrank"], "models": [], "size_mb": 2000,
     "unlocks": "higher-quality retrieval (heavier — off the potato path)"},
    {"id": "encryption", "label": "Encrypt sensitive data at rest",
     "flags": {"encryption_at_rest_enabled": True}, "deps": ["cryptography"], "models": [], "size_mb": 5,
     "unlocks": "AES encryption of `sensitive`-level memories (BL-020)"},
    {"id": "cloud_models", "label": "Cloud model providers",
     "flags": {"litellm_enabled": True}, "deps": ["litellm"], "models": [], "size_mb": 0,
     "unlocks": "route to OpenAI/etc. via LiteLLM"},
    {"id": "multi_agent", "label": "Multi-agent deliberation",
     "flags": {"multi_agent_orchestration_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "aspect council / debate depth on deep-reasoning turns (the Deliberate panel)"},
    {"id": "observability", "label": "Detailed tracing & telemetry",
     "flags": {"trace_id_enabled": True, "telemetry_log_trivial": True}, "deps": [], "models": [], "size_mb": 0,
     "unlocks": "per-request trace ids + verbose telemetry (diagnostics; a little overhead)"},
    {"id": "vision", "label": "Visual understanding (images)",
     "flags": {"vision_enabled": True}, "deps": ["pillow", "pytesseract"], "models": [], "size_mb": 0,
     "unlocks": "the analyze_image tool + image inputs on /v1: describe images (local GGUF VLM or BLIP) and OCR text"},
    # Intentionally NOT surfaced as picker features (kept as internal/admin flags, not dropped):
    #   • mem0_enabled — redundant memory backend, superseded by native memory (BL-078: cut from picker).
    #   • tool_replay_policy / pkg_policy_strict — security-hardening toggles (admin, not a use-case feature).
    #   • initiative_project_proposals — sub-capability folded under the `initiative` feature.
    #   • ui_decision_trace — surfaced by the Background-tasks panel, not a standalone feature.
]

_ALL_ASPECTS = ["morrigan", "nyx", "echo", "eris", "cassandra", "lilith"]

# Use-case profiles: what you want Layla for → a curated startup default.
PROFILES = [
    {"id": "companion", "label": "Companion", "desc": "Personality-first chat, memory, growth.",
     "features": ["initiative"], "aspects": _ALL_ASPECTS,
     "defaults": {"observation_mode_enabled": True}},
    {"id": "coding", "label": "Coding partner", "desc": "Repo-aware coding, diff-edits, IDE bridge.",
     "features": ["mcp"], "aspects": ["nyx", "morrigan"],
     "defaults": {"tool_first_enforcement_enabled": True, "tool_routing_enabled": True}},
    {"id": "language", "label": "Language learning", "desc": "German lessons, corrections, flashcards.",
     "features": ["voice"], "aspects": ["cassandra", "echo"], "defaults": {}},
    {"id": "research", "label": "Research", "desc": "Missions, knowledge base, web + deep research.",
     "features": ["search_elastic"], "aspects": ["cassandra", "echo"], "defaults": {}},
    {"id": "power", "label": "Power user (everything)", "desc": "Enable every feature.",
     "features": [f["id"] for f in FEATURE_MANIFEST], "aspects": _ALL_ASPECTS, "defaults": {}},
    {"id": "minimal", "label": "Minimal (potato)", "desc": "Lean chat only — least RAM.",
     "features": [], "aspects": ["morrigan"],
     "defaults": {"performance_mode": "potato"}},
]


def feature_by_id(fid: str) -> dict | None:
    return next((f for f in FEATURE_MANIFEST if f["id"] == fid), None)


def profile_by_id(pid: str) -> dict | None:
    return next((p for p in PROFILES if p["id"] == pid), None)


def enabled_feature_ids(cfg: dict | None = None) -> list[str]:
    """Feature ids whose flags are ALL truthy in `cfg` — i.e. the feature's capability is
    currently on. Drives UI gating (BL-208: the palette shows only what you enabled). Uses
    the live flag state (so a manually-toggled flag counts too, not just wizard choices);
    falls back to the persisted `setup_features` list for any flag-less feature."""
    cfg = cfg or {}
    setup_feats = set(cfg.get("setup_features") or [])
    out: list[str] = []
    for feat in FEATURE_MANIFEST:
        flags = feat.get("flags") or {}
        if flags:
            if all(cfg.get(k) for k in flags):
                out.append(feat["id"])
        elif feat["id"] in setup_feats:
            out.append(feat["id"])
    return out


def resolve_setup_config(profile_ids, feature_ids=None) -> dict:
    """
    Merge chosen profiles' defaults + every enabled feature's flags into one config-override
    dict. `feature_ids` explicitly enabled are unioned with the profiles' features. Later
    entries win on conflict. Also records the chosen profiles/features for reconfigure.
    """
    profile_ids = [p for p in (profile_ids or []) if profile_by_id(p)]
    enabled_features: list[str] = []
    cfg: dict = {}

    for pid in profile_ids:
        prof = profile_by_id(pid)
        cfg.update(prof.get("defaults") or {})
        for fid in prof.get("features") or []:
            if fid not in enabled_features:
                enabled_features.append(fid)

    for fid in feature_ids or []:
        if feature_by_id(fid) and fid not in enabled_features:
            enabled_features.append(fid)

    for fid in enabled_features:
        feat = feature_by_id(fid)
        if feat:
            cfg.update(feat.get("flags") or {})

    # Aspect roster from the union of chosen profiles (dedup, stable order).
    aspects: list[str] = []
    for pid in profile_ids:
        for a in profile_by_id(pid).get("aspects") or []:
            if a not in aspects:
                aspects.append(a)
    if aspects:
        cfg["enabled_aspects"] = aspects

    cfg["setup_profiles"] = profile_ids
    cfg["setup_features"] = enabled_features
    return cfg


def features_to_install(feature_ids) -> list[dict]:
    """The deps + models to fetch for the chosen features (drives BL-204's installer).
    Only returns features that actually need an install."""
    out = []
    for fid in feature_ids or []:
        feat = feature_by_id(fid)
        if feat and (feat.get("deps") or feat.get("models")):
            out.append({"id": fid, "label": feat["label"], "deps": feat.get("deps") or [],
                        "models": feat.get("models") or [], "size_mb": feat.get("size_mb", 0)})
    return out


def apply_setup(profile_ids, feature_ids=None, *, current_cfg=None, save=True) -> dict:
    """
    Resolve the chosen profiles/features into config overrides, merge onto the current
    config, and (optionally) persist as the startup default (BL-206). Returns the merged
    config. `current_cfg` + `save=False` makes this pure/testable.
    """
    if current_cfg is not None:
        cur = dict(current_cfg)
    else:
        import runtime_safety

        cur = dict(runtime_safety.load_config())
    merged = {**cur, **resolve_setup_config(profile_ids, feature_ids)}
    if save:
        import json

        import runtime_safety

        try:
            runtime_safety.CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            runtime_safety.invalidate_config_cache()
        except Exception:
            pass
    return merged

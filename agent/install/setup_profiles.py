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
    # LICENSING: deps must match the `layla[voice]` extra — faster-whisper (MIT) + pyttsx3
    # (system voice). kokoro-onnx is deliberately NOT here: it pulls phonemizer-fork (GPLv3+),
    # which pyproject keeps out of [voice]/[all], README documents as an explicit
    # `layla[voice-kokoro]` opt-in, and scripts/check_copyleft.py FAILS CI on. Before the
    # installer was wired this string was inert; wiring it turned a one-click checkbox into a
    # silent strong-copyleft install that could break the operator's own CI. tts.py already
    # falls back to pyttsx3, so voice works without it — kokoro stays an informed choice.
    {"id": "voice", "label": "Voice (speak & listen)",
     "flags": {"voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True},
     "deps": ["faster-whisper", "pyttsx3"], "models": ["whisper-base"], "size_mb": 500,
     "unlocks": "voice input + spoken replies (higher-quality kokoro TTS is a separate opt-in: pip install layla[voice-kokoro])"},
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
    {"id": "encryption", "label": "Install AES-at-rest crypto (not yet engaged)",
     "flags": {"encryption_at_rest_enabled": True}, "deps": ["cryptography"], "models": [], "size_mb": 5,
     "unlocks": "installs AES-at-rest crypto; no memory is marked `sensitive` yet, so it does not engage (BL-326)"},
    {"id": "cloud_models", "label": "Cloud model providers",
     "flags": {"litellm_enabled": True}, "deps": ["litellm"], "models": [], "size_mb": 0,
     "unlocks": "route to OpenAI/etc. via LiteLLM"},
    {"id": "multi_agent", "label": "Multi-agent deliberation",
     "flags": {"multi_agent_orchestration_enabled": True}, "deps": [], "models": [], "size_mb": 0,
     # NOT "(the Deliberate panel)". That parenthetical was false and it was load-bearing: the
     # sidebar inherited it as a gate identity and told operators a working panel was locked.
     # This flag is read in exactly two places — multi_agent.py::should_use_multi_agent, which
     # decides whether a CHAT turn is auto-routed to several aspects, and prompt_builder.py,
     # which deepens the prompt on deep-reasoning turns. The Deliberate panel POSTs /debate and
     # runs whether this is on or off. Describe the two paths that actually read it.
     "unlocks": "auto-routes complex CHAT turns to several aspects + deeper deep-reasoning prompts"},
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
    # SECURITY: "everything" deliberately EXCLUDES `remote` — remote access exposes the
    # app to the network, so it must always be a separate, explicit opt-in (with its own
    # warning), never a side effect of picking a broad profile. Users enable it via the
    # `remote` feature toggle. (Was: every feature incl. remote → silently opened a listener.)
    {"id": "power", "label": "Power user (everything)", "desc": "Enable every feature (except remote access — opt in separately).",
     "features": [f["id"] for f in FEATURE_MANIFEST if f["id"] != "remote"], "aspects": _ALL_ASPECTS, "defaults": {}},
    {"id": "minimal", "label": "Minimal (potato)", "desc": "Lean chat only — least RAM.",
     "features": [], "aspects": ["morrigan"],
     "defaults": {"performance_mode": "potato"}},
]


def feature_by_id(fid: str) -> dict | None:
    return next((f for f in FEATURE_MANIFEST if f["id"] == fid), None)


def flag_satisfied(actual, want) -> bool:
    """Does `actual` hold the value a feature's manifest DECLARES it needs?

    S2. Every reader of `flags` asked `bool(cfg.get(k))` — "is the key truthy?" — which is not
    the question the manifest poses. The manifest declares a VALUE. A flag downgraded to a
    truthy-but-wrong value (`1`, `"true"`, `"auto"`, a geometry dict with one framework turned
    off) satisfied truthiness and was reported ON, so the read-back that exists to catch a
    reverted flag caught only the half of the revert that lands on a falsy value.

    Strictness is the point: for a declared bool, an int or a string is NOT the value asked
    for, however truthy. Accepting a coercion here is how a capability that is not there gets
    reported as present — the same lie, one type away.

    Lives here, beside FEATURE_MANIFEST, because the declaration site owns what its own values
    mean; every reader imports this rather than re-deciding (that is how the two answers drift).
    """
    if isinstance(want, dict):
        # Nested requirement (geometry_frameworks_enabled): every declared sub-key must hold.
        if not isinstance(actual, dict):
            return False
        return all(flag_satisfied(actual.get(k), v) for k, v in want.items())
    if isinstance(want, bool):
        return isinstance(actual, bool) and actual is want
    return actual == want


def profile_by_id(pid: str) -> dict | None:
    return next((p for p in PROFILES if p["id"] == pid), None)


def enabled_feature_ids(cfg: dict | None = None) -> list[str]:
    """Feature ids whose flags ALL hold their declared value in `cfg` — i.e. the feature's
    capability is currently on. Drives UI gating (BL-208: the palette shows only what you
    enabled). Uses the live flag state (so a manually-toggled flag counts too, not just wizard
    choices); falls back to the persisted `setup_features` list for any flag-less feature.

    Shares `flag_satisfied` with install/feature_status.py deliberately: a palette that gates
    on truthiness while the status report gates on the declared value is two answers to one
    question, and the user meets both."""
    cfg = cfg or {}
    setup_feats = set(cfg.get("setup_features") or [])
    out: list[str] = []
    for feat in FEATURE_MANIFEST:
        flags = feat.get("flags") or {}
        if flags:
            if all(flag_satisfied(cfg.get(k), want) for k, want in flags.items()):
                out.append(feat["id"])
        elif feat["id"] in setup_feats:
            out.append(feat["id"])
    return out


def requested_feature_ids(profile_ids, feature_ids=None) -> list[str]:
    """Every feature the selection asks for — the explicit checkboxes UNIONED with the ones
    the chosen profiles imply. The caller needs this before applying, to decide which of them
    are actually installable right now (see `exclude_features`)."""
    out: list[str] = []
    for pid in [p for p in (profile_ids or []) if profile_by_id(p)]:
        for fid in profile_by_id(pid).get("features") or []:
            if fid not in out:
                out.append(fid)
    for fid in feature_ids or []:
        if feature_by_id(fid) and fid not in out:
            out.append(fid)
    return out


def resolve_setup_config(profile_ids, feature_ids=None, *, exclude_features=None) -> dict:
    """
    Merge chosen profiles' defaults + every enabled feature's flags into one config-override
    dict. `feature_ids` explicitly enabled are unioned with the profiles' features. Later
    entries win on conflict. Also records the chosen profiles/features for reconfigure.

    `exclude_features` drops features from the result entirely — no flags, and no entry in
    `setup_features`. It exists so a caller can say "enable everything the user picked EXCEPT
    the ones whose packages are not installed yet", which a plain `feature_ids` filter cannot
    express: a profile implies its own features, so an unsatisfiable one would sneak back in.
    """
    profile_ids = [p for p in (profile_ids or []) if profile_by_id(p)]
    skip = set(exclude_features or [])
    cfg: dict = {}

    for pid in profile_ids:
        cfg.update(profile_by_id(pid).get("defaults") or {})

    enabled_features = [f for f in requested_feature_ids(profile_ids, feature_ids) if f not in skip]

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


def apply_setup(profile_ids, feature_ids=None, *, current_cfg=None, save=True,
                exclude_features=None, additive=False) -> dict:
    """
    Resolve the chosen profiles/features into config overrides, merge onto the current
    config, and (optionally) persist as the startup default (BL-206). Returns the merged
    config. `current_cfg` + `save=False` makes this pure/testable.

    `additive=True` unions `setup_profiles`/`setup_features` with what is already persisted
    instead of replacing them. The wizard applies a whole selection at once and must be able
    to REMOVE a feature, so it replaces; the post-install flag write turns on exactly one
    feature and must not erase the other nine the operator already had (a plain replace made
    installing Voice reset `setup_features` to ["voice"]).
    """
    if current_cfg is not None:
        cur = dict(current_cfg)
    elif save:
        # THE MERGE BASE MUST BE THE REQUEST, NOT THE ANSWER.
        # load_config() returns the EFFECTIVE config — auto-tune and the maturity gates have already
        # overlaid it — so using it as the base and then writing `merged` back to disk PERSISTS every
        # owner-imposed value as though the operator had chosen it. Driven: a bare POST /setup/apply
        # took the file from 13 keys to 434, rewriting max_runtime_seconds 30 -> 300 and hyde_enabled
        # True -> False; the not-in-force report then read all-clear, because its entire evidence is
        # `file != effective` and this had just erased the difference. Two unrelated outstanding
        # requests were destroyed by a single feature install, and the wizard AUTO-OPENS on first run
        # (ui/components/setup.js), so it happened before a new operator had knowingly chosen anything.
        # The raw file is the only record of intent; keep it, and let the owners keep overlaying it.
        from services.infrastructure.route_helpers import raw_config_file

        cur = raw_config_file()
    else:
        # Not persisting: the caller wants a preview of what would be IN FORCE, so effective is right.
        import runtime_safety

        cur = dict(runtime_safety.load_config())
    resolved = resolve_setup_config(profile_ids, feature_ids, exclude_features=exclude_features)
    if additive:
        for key in ("setup_profiles", "setup_features"):
            out = [x for x in (cur.get(key) or []) if isinstance(x, str)]
            for x in resolved.get(key) or []:
                if x not in out:
                    out.append(x)
            resolved[key] = out
    merged = {**cur, **resolved}
    # Never persist remote_enabled without an auth credential — see
    # runtime_safety._invariant_remote_needs_credential for the reasoning that used to live
    # here as a comment.
    #
    # THIS IS NO LONGER A CHECK THIS FUNCTION OWNS. It was, and being the only owner is what
    # let POST /settings/themes and POST /settings persist the state this refuses: the rule was
    # a line in one surface rather than a property of the config. It now lives on the write
    # path, and this call is here only so the returned `merged` — which is also the wizard's
    # PREVIEW of what would land, computed on the `save=False` path that never reaches a
    # writer — shows the same coerced value the disk would get. Do not reintroduce the
    # comparison inline; a second copy is how this defect returns.
    # The refusal is reported to the operator by the wizard's existing read-back
    # (install/feature_status), which reads the effective config and names the security_policy
    # owner — so it is surfaced there rather than re-explained here.
    import runtime_safety as _rs_inv

    _rs_inv.enforce_config_invariants(merged)
    if save:
        import json

        import runtime_safety

        try:
            runtime_safety.CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            runtime_safety.invalidate_config_cache()
        except Exception:
            pass
    return merged

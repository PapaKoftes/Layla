"""
Config schema for Layla runtime_config.json.
Single source of truth for editable settings. Used by /settings API and UI.
Advanced users can edit agent/runtime_config.json directly — see docs/CONFIG_REFERENCE.md.
"""
from __future__ import annotations

from typing import Any

# Named merges for POST /settings/preset. Only keys in EDITABLE_SCHEMA are applied.
SETTINGS_PRESETS: dict[str, dict[str, Any]] = {
    "potato": {
        "performance_mode": "low",
        "n_ctx": 2048,
        "n_batch": 256,
        "n_gpu_layers": 0,
        "max_tool_calls": 2,
        "max_runtime_seconds": 20,
        "research_max_tool_calls": 6,
        "research_max_runtime_seconds": 60,
        "use_chroma": False,
        "completion_max_tokens": 192,
        "semantic_k": 3,
        "knowledge_chunks_k": 3,
        "learnings_n": 15,
        "scheduler_study_enabled": False,
        "whisper_model": "tiny",
    },
}

# Categories for UI grouping. "core" = always visible; "advanced" = collapsible.
EDITABLE_SCHEMA: list[dict[str, Any]] = [
    # ── Core (always shown) ──
    {"key": "model_filename", "type": "string", "category": "core", "hint": "GGUF filename in models/ folder. Restart required."},
    {"key": "models_dir", "type": "string", "category": "core", "hint": "Path to models folder. Default: repo/models/ or ~/.layla/models/"},
    {"key": "sandbox_root", "type": "string", "category": "core", "hint": "Workspace root. Layla can only read/write within this path."},
    {"key": "temperature", "type": "number", "category": "core", "default": 0.2, "min": 0.01, "max": 1.5, "hint": "Lower = deterministic. Higher = creative."},
    {"key": "completion_max_tokens", "type": "number", "category": "core", "default": 256, "min": 64, "max": 8192, "hint": "Max tokens per response. Higher = longer, slower."},
    # ── Model (advanced) ──
    {"key": "n_ctx", "type": "number", "category": "model", "default": 4096, "min": 256, "max": 131072, "hint": "Context window size. Larger = more memory."},
    {"key": "n_gpu_layers", "type": "number", "category": "model", "default": -1, "min": -1, "max": 99, "hint": "Layers on GPU. -1 = all. 0 = CPU only."},
    {"key": "n_batch", "type": "number", "category": "model", "default": 512, "min": 64, "max": 2048, "hint": "Batch size for prompt processing."},
    {"key": "n_threads", "type": "number", "category": "model", "default": None, "min": 1, "max": 64, "hint": "CPU threads. null = auto."},
    {"key": "top_p", "type": "number", "category": "model", "default": 0.95, "min": 0, "max": 1, "hint": "Nucleus sampling."},
    {"key": "top_k", "type": "number", "category": "model", "default": 40, "min": 1, "max": 100, "hint": "Top-k sampling."},
    {"key": "repeat_penalty", "type": "number", "category": "model", "default": 1.1, "min": 1, "max": 2, "hint": "Penalize repetition."},
    # ── Memory & retrieval ──
    {"key": "use_chroma", "type": "boolean", "category": "memory", "default": True, "hint": "Use ChromaDB for semantic search and learnings."},
    {"key": "knowledge_chunks_k", "type": "number", "category": "memory", "default": 5, "min": 1, "max": 20, "hint": "Chunks retrieved from knowledge base."},
    {"key": "learnings_n", "type": "number", "category": "memory", "default": 30, "min": 5, "max": 100, "hint": "Learnings injected into context."},
    {"key": "semantic_k", "type": "number", "category": "memory", "default": 5, "min": 1, "max": 20, "hint": "Semantic search results."},
    {"key": "learning_quality_gate_enabled", "type": "boolean", "category": "memory", "default": True, "hint": "Reject low-quality distill content before DB insert (see distill.passes_learning_quality_gate)."},
    {"key": "learning_quality_min_score", "type": "number", "category": "memory", "default": 0.35, "min": 0.05, "max": 1.0, "hint": "Minimum heuristic score when learning_quality_gate_enabled is true."},
    # ── Voice ──
    {"key": "tts_voice", "type": "string", "category": "voice", "options": ["af_heart", "af_sky", "am_adam", "bf_emma", "bm_george"], "hint": "TTS voice."},
    {"key": "whisper_model", "type": "string", "category": "voice", "options": ["tiny", "base", "small", "medium"], "hint": "STT model. tiny=fastest, medium=best."},
    {"key": "tts_speed", "type": "number", "category": "voice", "default": 1.0, "min": 0.5, "max": 2, "hint": "TTS playback speed."},
    # ── Scheduler ──
    {"key": "scheduler_study_enabled", "type": "boolean", "category": "scheduler", "default": True, "hint": "Enable study plan scheduler."},
    {"key": "scheduler_interval_minutes", "type": "number", "category": "scheduler", "default": 30, "min": 5, "max": 120, "hint": "Minutes between scheduler runs."},
    {"key": "scheduler_recent_activity_minutes", "type": "number", "category": "scheduler", "default": 90, "min": 15, "max": 480, "hint": "Activity window for scheduler."},
    # ── Runtime limits (effective values also in /health effective_limits) ──
    {
        "key": "performance_mode",
        "type": "string",
        "category": "limits",
        "options": ["auto", "low", "mid", "high"],
        "default": "auto",
        "hint": "CPU/RAM caps: low tightens ctx and tool budgets. auto = hardware tier.",
    },
    {"key": "max_tool_calls", "type": "number", "category": "limits", "default": 5, "min": 1, "max": 50, "hint": "Max tool calls per agent turn (non-research)."},
    {"key": "max_runtime_seconds", "type": "number", "category": "limits", "default": 30, "min": 5, "max": 3600, "hint": "Max wall time per agent turn (seconds)."},
    {"key": "research_max_tool_calls", "type": "number", "category": "limits", "default": 20, "min": 1, "max": 100, "hint": "Max tool calls when research_mode is on."},
    {"key": "research_max_runtime_seconds", "type": "number", "category": "limits", "default": 120, "min": 30, "max": 14400, "hint": "Max wall time for research-style runs (seconds)."},
    # ── Safety & behavior ──
    {"key": "safe_mode", "type": "boolean", "category": "safety", "default": True, "hint": "Require approval for file writes and code execution."},
    {"key": "uncensored", "type": "boolean", "category": "safety", "default": True, "hint": "Uncensored model behavior."},
    {"key": "enable_cot", "type": "boolean", "category": "safety", "default": True, "hint": "Chain-of-thought reasoning."},
    {"key": "enable_self_reflection", "type": "boolean", "category": "safety", "default": False, "hint": "Post-response self-reflection."},
    {"key": "custom_system_prefix", "type": "string", "category": "safety", "multiline": True, "hint": "Custom system addition (e.g. Always respond in bullet points)."},
    # ── Remote ──
    {"key": "remote_enabled", "type": "boolean", "category": "remote", "default": False, "hint": "Allow remote API access."},
    {"key": "llama_server_url", "type": "string", "category": "remote", "hint": "External llama.cpp server URL. Overrides local model."},
    # ── Integrations (Discord, Slack, etc.) ──
    {"key": "discord_webhook_url", "type": "string", "category": "integrations", "hint": "Discord webhook URL for discord_send. Server Settings → Integrations → Webhooks."},
    {"key": "discord_bot_token", "type": "string", "category": "integrations", "hint": "Discord bot token for full bot (voice, TTS, music). Create at Discord Developer Portal."},
    {"key": "slack_webhook_url", "type": "string", "category": "integrations", "hint": "Slack incoming webhook URL for notifications."},
]


def get_editable_keys() -> set[str]:
    """Set of keys that can be edited via /settings API."""
    return {e["key"] for e in EDITABLE_SCHEMA}


def get_schema_by_category() -> dict[str, list[dict]]:
    """Schema grouped by category for UI."""
    out: dict[str, list[dict]] = {}
    for e in EDITABLE_SCHEMA:
        cat = e.get("category", "advanced")
        out.setdefault(cat, []).append(e)
    return out


def get_schema_for_api() -> dict[str, Any]:
    """Schema formatted for GET /settings/schema."""
    return {
        "categories": list(get_schema_by_category().keys()),
        "fields": EDITABLE_SCHEMA,
        "config_file": "agent/runtime_config.json",
        "docs": "docs/CONFIG_REFERENCE.md",
        "presets": list(SETTINGS_PRESETS.keys()),
    }


def apply_settings_preset(existing_cfg: dict[str, Any], preset_name: str) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Merge preset values into a copy of existing_cfg.
    Returns (new_cfg, list of keys applied). Unknown preset → (None, []).
    """
    preset = SETTINGS_PRESETS.get(preset_name.strip().lower())
    if not preset:
        return None, []
    editable = get_editable_keys()
    applied: list[str] = []
    out = {**existing_cfg}
    for k, v in preset.items():
        if k in editable:
            out[k] = v
            applied.append(k)
    return out, applied

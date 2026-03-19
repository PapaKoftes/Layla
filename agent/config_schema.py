"""
Config schema for Layla runtime_config.json.
Single source of truth for editable settings. Used by /settings API and UI.
Advanced users can edit agent/runtime_config.json directly — see docs/CONFIG_REFERENCE.md.
"""
from __future__ import annotations

from typing import Any

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
    # ── Voice ──
    {"key": "tts_voice", "type": "string", "category": "voice", "options": ["af_heart", "af_sky", "am_adam", "bf_emma", "bm_george"], "hint": "TTS voice."},
    {"key": "whisper_model", "type": "string", "category": "voice", "options": ["tiny", "base", "small", "medium"], "hint": "STT model. tiny=fastest, medium=best."},
    {"key": "tts_speed", "type": "number", "category": "voice", "default": 1.0, "min": 0.5, "max": 2, "hint": "TTS playback speed."},
    # ── Scheduler ──
    {"key": "scheduler_study_enabled", "type": "boolean", "category": "scheduler", "default": True, "hint": "Enable study plan scheduler."},
    {"key": "scheduler_interval_minutes", "type": "number", "category": "scheduler", "default": 30, "min": 5, "max": 120, "hint": "Minutes between scheduler runs."},
    {"key": "scheduler_recent_activity_minutes", "type": "number", "category": "scheduler", "default": 90, "min": 15, "max": 480, "hint": "Activity window for scheduler."},
    # ── Safety & behavior ──
    {"key": "safe_mode", "type": "boolean", "category": "safety", "default": True, "hint": "Require approval for file writes and code execution."},
    {"key": "uncensored", "type": "boolean", "category": "safety", "default": True, "hint": "Uncensored model behavior."},
    {"key": "max_tool_calls", "type": "number", "category": "safety", "default": 5, "min": 1, "max": 20, "hint": "Max tool calls per turn."},
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
    }

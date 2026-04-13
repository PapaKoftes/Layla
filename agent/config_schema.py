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
    {
        "key": "memory_retrieval_min_adjusted_confidence",
        "type": "number",
        "category": "memory",
        "default": 0.0,
        "min": 0.0,
        "max": 1.0,
        "hint": "Drop memory hits below this adjusted confidence in semantic recall (0 = no filter).",
    },
    {
        "key": "inline_initiative_enabled",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "After 2+ tool steps, append one heuristic next-step line to the final reply.",
    },
    {
        "key": "project_discovery_auto_inject",
        "type": "boolean",
        "category": "memory",
        "default": False,
        "hint": "Sparse .layla/project_memory.json: inject deterministic workspace scan into context (filesystem only).",
    },
    {"key": "learning_quality_gate_enabled", "type": "boolean", "category": "memory", "default": True, "hint": "Reject low-quality distill content before DB insert (see distill.passes_learning_quality_gate)."},
    {"key": "learning_quality_min_score", "type": "number", "category": "memory", "default": 0.35, "min": 0.05, "max": 1.0, "hint": "Minimum heuristic score when learning_quality_gate_enabled is true."},
    {"key": "file_checkpoint_enabled", "type": "boolean", "category": "memory", "default": True, "hint": "Snapshot files before write_file / apply_patch / search_replace / write_files_batch for restore_file_checkpoint."},
    {"key": "file_checkpoint_max_count", "type": "number", "category": "memory", "default": 200, "min": 0, "max": 50000, "hint": "Max checkpoint bundles per workspace; 0 = unlimited. Oldest deleted first."},
    {"key": "file_checkpoint_max_bytes", "type": "number", "category": "memory", "default": 209715200, "min": 0, "max": 2147483647, "hint": "Max total bytes for checkpoints (~200MB default); 0 = unlimited."},
    {"key": "elasticsearch_enabled", "type": "boolean", "category": "memory", "default": False, "hint": "Mirror new learnings to Elasticsearch; use GET /memory/elasticsearch/search."},
    {"key": "elasticsearch_url", "type": "string", "category": "memory", "default": "", "hint": "Elasticsearch 8.x base URL, e.g. http://127.0.0.1:9200"},
    {"key": "elasticsearch_index_prefix", "type": "string", "category": "memory", "default": "layla", "hint": "Index name prefix; learnings use {prefix}-learnings."},
    {"key": "elasticsearch_api_key", "type": "string", "category": "memory", "default": None, "hint": "Optional API key for Elasticsearch (cloud deployments)."},
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
    {"key": "max_runtime_seconds", "type": "number", "category": "limits", "default": 900, "min": 5, "max": 3600, "hint": "Max wall time per agent turn (seconds). Align with ui_agent_stream_timeout_seconds so the server does not stop before the browser."},
    {"key": "tool_call_timeout_seconds", "type": "number", "category": "limits", "default": 60, "min": 5, "max": 600, "hint": "Max seconds a single tool call may run before being killed."},
    {"key": "approval_ttl_seconds", "type": "number", "category": "limits", "default": 3600, "min": 60, "max": 86400, "hint": "Seconds before a pending approval expires (default: 1 hour)."},
    {"key": "hyde_enabled", "type": "boolean", "category": "limits", "default": False, "hint": "Enable HyDE retrieval (generates a hypothetical answer before embedding — extra LLM call per query, improves recall quality)."},
    {"key": "research_max_tool_calls", "type": "number", "category": "limits", "default": 20, "min": 1, "max": 100, "hint": "Max tool calls when research_mode is on."},
    {"key": "research_max_runtime_seconds", "type": "number", "category": "limits", "default": 1800, "min": 30, "max": 14400, "hint": "Max wall time for research-style runs (seconds)."},
    # ── Safety & behavior ──
    {"key": "safe_mode", "type": "boolean", "category": "safety", "default": True, "hint": "Require approval for file writes and code execution."},
    {"key": "uncensored", "type": "boolean", "category": "safety", "default": True, "hint": "Uncensored model behavior."},
    {
        "key": "nsfw_allowed",
        "type": "boolean",
        "category": "safety",
        "default": True,
        "hint": "Allow adult/NSFW content in system policy when combined with uncensored; use @lilith + register keywords per message for Lilith NSFW mode.",
    },
    {"key": "enable_cot", "type": "boolean", "category": "safety", "default": True, "hint": "Chain-of-thought reasoning."},
    {"key": "enable_self_reflection", "type": "boolean", "category": "safety", "default": False, "hint": "Post-response self-reflection."},
    {
        "key": "direct_feedback_enabled",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Opt-in blunt collaboration: honest critique of work (not personal attacks). Non-clinical — no psychiatric labels. See ETHICAL_AI_PRINCIPLES §11.",
    },
    {
        "key": "pin_psychology_framework_excerpt",
        "type": "boolean",
        "category": "safety",
        "default": True,
        "hint": "Echo/Lilith: inject short non-clinical interaction-framework reminder (observation not diagnosis).",
    },
    {"key": "custom_system_prefix", "type": "string", "category": "safety", "multiline": True, "hint": "Custom system addition (e.g. Always respond in bullet points)."},
    {
        "key": "planning_strict_mode",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Mutating/run-class tools require an approved plan binding (plan_id) or allow_write/run on the request; see RUNBOOKS.",
    },
    {
        "key": "engineering_pipeline_enabled",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Structured engineering partner: plan/execute modes with clarifier, critics, refiner, validator. See docs/STRUCTURED_ENGINEERING_PARTNER.md.",
    },
    {
        "key": "engineering_pipeline_default_mode",
        "type": "string",
        "category": "safety",
        "options": ["chat", "plan", "execute"],
        "default": "chat",
        "hint": "Default when POST /agent omits engineering_pipeline_mode. execute = full pipeline (slow).",
    },
    {
        "key": "engineering_pipeline_max_clarify_rounds",
        "type": "number",
        "category": "safety",
        "default": 3,
        "min": 1,
        "max": 10,
        "hint": "Reserved: max clarifier rounds per turn (protocol uses clarification_reply on follow-up requests).",
    },
    {
        "key": "engineering_pipeline_validator_max_retries",
        "type": "number",
        "category": "safety",
        "default": 1,
        "min": 0,
        "max": 2,
        "hint": "When execute-mode validator suggests retry, bounded re-runs of execute_plan.",
    },
    {
        "key": "in_loop_plan_governance_enabled",
        "type": "boolean",
        "category": "safety",
        "default": True,
        "hint": "Long-goal in-loop planner uses execute_plan(step_governance=True) like /execute_plan. Set false for legacy behavior.",
    },
    {
        "key": "in_loop_plan_default_max_retries",
        "type": "number",
        "category": "safety",
        "default": 1,
        "min": 0,
        "max": 3,
        "hint": "Per-step governance retries for in-loop plans (same cap as /plans execute body).",
    },
    {
        "key": "plan_governance_require_nonempty_step_tools",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Approve rejects mutating step types with empty tools[]; in-loop may auto-fill read-only defaults (marks _tools_auto_filled).",
    },
    {
        "key": "plan_governance_reject_auto_filled_tools",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Governed steps fail if tools were auto-filled — forces explicit tools in the plan.",
    },
    {
        "key": "plan_governance_strict_tool_evidence",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Edit/test steps need tool traces with substantive results (paths for writes; pytest/unittest evidence for tests). Disallows text-only proof. Implied when plan_governance_hard_mode is on.",
    },
    {
        "key": "plan_governance_hard_mode",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "One switch: same as nonempty tools on mutating steps + reject auto-filled tools + strict tool evidence.",
    },
    {
        "key": "llm_serialize_per_workspace",
        "type": "boolean",
        "category": "limits",
        "default": False,
        "hint": "Per-workspace autonomous_run lock; local llama generation stays globally serialized. Enable for multi-repo parallelism.",
    },
    # ── Remote ──
    {"key": "remote_enabled", "type": "boolean", "category": "remote", "default": False, "hint": "Allow remote API access."},
    {"key": "llama_server_url", "type": "string", "category": "remote", "hint": "External llama.cpp server URL. Overrides local model."},
    # ── Integrations (Discord, Slack, etc.) ──
    {
        "key": "mcp_client_enabled",
        "type": "boolean",
        "category": "integrations",
        "default": False,
        "hint": "Enable MCP stdio client (services/mcp_client.py). When true, the mcp_tools_call tool can reach configured mcp_stdio_servers (requires allow_run + approvals like shell).",
    },
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

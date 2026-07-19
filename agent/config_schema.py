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
        # Semantic memory stays ON even on a potato — model2vec static embeddings
        # (no torch) + sqlite-vec make it cheap, so the wedge ("it remembers") holds.
        # embedder_prefer_quality off = the fast static embedder. (Was use_chroma:False
        # before cheap embeddings existed.)
        "use_chroma": True,
        "embedder_prefer_quality": False,
        # 192 hard-cut genuinely long answers mid-sentence (~140 words), contradicting the loosened
        # "length follows need" output-discipline rule. Raised to the default tier's 256 — this only
        # costs latency on answers that actually need the length (short replies stop early at natural
        # completion), so a how-to / explanation can finish instead of truncating on the potato box.
        "completion_max_tokens": 256,
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
    {"key": "ui_language", "type": "string", "category": "core", "default": "en", "hint": "Web UI language (en, es, de, fr, it, pt, ja, zh, ar, ru, ko). Falls back to English for missing strings."},
    {"key": "model_filename", "type": "string", "category": "core", "hint": "GGUF filename in models/ folder. Restart required."},
    {"key": "models_dir", "type": "string", "category": "core", "hint": "Path to models folder. Default: repo/models/ or ~/.layla/models/"},
    {"key": "sandbox_root", "type": "string", "category": "core", "hint": "Workspace root. Layla can only read/write within this path."},
    {"key": "temperature", "type": "number", "category": "core", "default": 0.2, "min": 0.01, "max": 1.5, "hint": "Lower = deterministic. Higher = creative."},
    {"key": "completion_max_tokens", "type": "number", "category": "core", "default": 256, "min": 64, "max": 8192, "hint": "Max tokens per response. Higher = longer, slower. NOTE: hardware auto-tune manages this per tier — to make a manual value stick, add 'completion_max_tokens' to auto_tune_locked_keys or turn off auto_tune_enabled."},
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
    {"key": "embedder_prefer_quality", "type": "boolean", "category": "memory", "default": False, "hint": "Prefer heavier sentence-transformers embeddings over fast model2vec static embeddings (needs torch; better quality, slower on low-end)."},
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
    {"key": "people_codex_enabled", "type": "boolean", "category": "memory", "default": True, "hint": "Daily maintenance scans recent conversations for people you mention and saves them to the people codex."},
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
    {"key": "tts_voice", "type": "string", "category": "voice", "options": ["af_heart", "af_bella", "af_sarah", "am_adam", "am_michael", "bf_emma", "bf_sarah", "bm_george", "bm_lewis"], "hint": "TTS voice (kokoro-onnx catalog)."},
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
    {
        "key": "auto_tune_enabled",
        "type": "boolean",
        "category": "limits",
        "default": True,
        "hint": "Hardware-adaptive optimization: auto-detect the machine tier and set inference + pipeline weight (context size, prompt budget, response length / completion_max_tokens, extra LLM calls, timeouts) for the best speed/quality on ANY hardware. Turn off for fully manual control. Lock individual keys via auto_tune_locked_keys.",
    },
    {
        # The documented escape hatch from auto-tune was NOT a schema key, so it was
        # unreachable from both the UI and POST /settings: every hint that said "add it to
        # auto_tune_locked_keys" described an action no user could perform, and there was no
        # way at all to opt a single key out of auto-tune short of disabling the whole suite.
        "key": "auto_tune_locked_keys",
        "type": "list",
        "category": "limits",
        "default": [],
        "hint": "Comma-separated list of settings auto-tune must NOT overwrite — the per-key escape hatch. Only auto-tune-managed keys can be locked; anything else is reported back as rejected.",
    },
    {"key": "max_tool_calls", "type": "number", "category": "limits", "default": 5, "min": 1, "max": 50, "hint": "Max tool calls per agent turn (non-research)."},
    {"key": "max_runtime_seconds", "type": "number", "category": "limits", "default": 900, "min": 5, "max": 3600, "hint": "Max wall time per agent turn (seconds). Align with ui_agent_stream_timeout_seconds so the server does not stop before the browser."},
    {"key": "tool_call_timeout_seconds", "type": "number", "category": "limits", "default": 60, "min": 5, "max": 600, "hint": "Max seconds a single tool call may run before being killed."},
    {"key": "approval_ttl_seconds", "type": "number", "category": "limits", "default": 3600, "min": 60, "max": 86400, "hint": "Seconds before a pending approval expires (default: 1 hour)."},
    {"key": "models_max_keep", "type": "number", "category": "limits", "default": 0, "min": 0, "max": 100, "hint": "Daily maintenance prunes downloaded GGUFs to the newest N (the active model is always kept). 0 = keep all."},
    {"key": "hyde_enabled", "type": "boolean", "category": "limits", "default": False, "hint": "Enable HyDE retrieval (generates a hypothetical answer before embedding — extra LLM call per query, improves recall quality)."},
    {"key": "research_max_tool_calls", "type": "number", "category": "limits", "default": 20, "min": 1, "max": 100, "hint": "Max tool calls when research_mode is on."},
    {"key": "research_max_runtime_seconds", "type": "number", "category": "limits", "default": 1800, "min": 30, "max": 14400, "hint": "Max wall time for research-style runs (seconds)."},
    # ── Safety & behavior ──
    {"key": "safe_mode", "type": "boolean", "category": "safety", "default": True, "hint": "Hard floor for destructive tools: while on (default), file writes and code execution (write_file, shell, run_python, git, …) ALWAYS require approval — even if tool_approval_bypass is set. Turn off only if you deliberately want the bypass to auto-approve destructive tools too."},
    {"key": "plugins_enabled", "type": "boolean", "category": "safety", "default": False, "hint": "Allow skill plugins to EXECUTE Python code (exec_module) and contribute MCP subprocess servers. Off = declarative skills only. Security-sensitive: only enable for plugins you trust."},
    {"key": "skill_venv_enabled", "type": "boolean", "category": "safety", "default": False, "hint": "On skill-pack install, provision a per-pack venv and pip-install its declared dependencies (heavier install; rolled back atomically on failure)."},
    {"key": "skill_deps_require_pinned", "type": "boolean", "category": "safety", "default": True, "hint": "Reject skill-pack installs whose dependencies aren't version-pinned (name==x.y.z). Prevents supply-chain drift from floating deps."},
    {"key": "skill_packs_execute_enabled", "type": "boolean", "category": "safety", "default": False, "hint": "Allow the run_skill_pack tool to EXECUTE an installed pack's Python entry point. Off = installing a pack never runs its code. The per-pack venv is dependency isolation, not a security jail: the pack runs as a subprocess at your full privilege. Only enable for packs you trust."},
    {"key": "agent_hooks_enabled", "type": "boolean", "category": "safety", "default": True, "hint": "Allow operator-configured agent_hooks (session_start/pre_tool/post_tool) to run subprocess commands. session_start hooks run automatically when this is on."},
    {"key": "hooks_require_allow_run", "type": "boolean", "category": "safety", "default": True, "hint": "pre_tool/post_tool hooks run only when the turn has allow_run (or this is off). Keep on unless you trust every configured hook."},
    {"key": "uncensored", "type": "boolean", "category": "safety", "default": True, "hint": "Uncensored model behavior."},
    {
        "key": "nsfw_allowed",
        "type": "boolean",
        "category": "safety",
        "default": True,
        "hint": "Allow adult/NSFW content in system policy when combined with uncensored; use @lilith + register keywords per message for Lilith NSFW mode.",
    },
    {"key": "enable_cot", "type": "boolean", "category": "safety", "default": True, "hint": "Chain-of-thought reasoning."},
    {"key": "deliberation_enabled", "type": "boolean", "category": "safety", "default": False, "hint": "Multi-aspect debate prompt: all six aspects weigh in before answering. Off by default — small models render the six scaffold lines as ~6 stitched answers. Leave off for normal single-voice chat."},
    {"key": "deliberation_mode", "type": "string", "category": "safety", "options": ["solo", "auto", "debate", "council", "tribunal"], "default": "auto", "hint": "Multi-aspect deliberation: solo=one voice, auto=detect complexity, debate=2, council=3, tribunal=all 6."},
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
        "key": "completion_gate_enabled",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Deterministic quality gate: retry or structured failure when output does not meet minimum standards.",
    },
    {
        "key": "deterministic_tool_routes_enabled",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Deterministic tool routing: reduce visible tools and constrain tool choice to task type.",
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
        "key": "ui_theme_preset",
        "type": "string",
        "category": "core",
        "default": "",
        "hint": "Optional UI theme preset (applied on load). Leave blank for default.",
    },
    {
        "key": "wizard_complete",
        "type": "boolean",
        "category": "core",
        "default": False,
        "hint": "Web setup wizard completion flag (set by UI).",
    },
    # engineering_pipeline_max_clarify_rounds removed from EDITABLE_SCHEMA (audit round-4 #5): it was a
    # numeric Settings-UI control that NO code reads ("Reserved" — the clarify protocol uses
    # clarification_reply on follow-up requests), so it silently did nothing. The default stays in
    # runtime_safety for internal use; it just no longer renders as a no-op user knob.
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
    {
        "key": "remote_api_key",
        "type": "string",
        "category": "remote",
        "default": "",
        "hint": "Bearer token required for non-localhost clients when remote_enabled (store via UI or edit runtime_config.json).",
    },
    {
        "key": "allow_legacy_remote_api_key",
        "type": "boolean",
        "category": "remote",
        "default": False,
        "hint": "Honor the DEPRECATED plaintext remote_api_key. Off by default — a stale key won't authenticate. Prefer tunnel_token_hash (rotate via /remote/token/rotate).",
    },
    {
        "key": "remote_rate_limit_per_minute",
        "type": "number",
        "category": "remote",
        "default": 100,
        "hint": "When remote_enabled, max requests per minute per non-localhost IP (0 = unlimited).",
    },
    {"key": "llama_server_url", "type": "string", "category": "remote", "hint": "External llama.cpp server URL. Overrides local model."},
    # ── Admin mode (trusted operator) ──
    {
        "key": "admin_mode",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Auto-approve dangerous tools (still audited). The hard shell command blocklist (rm/dd/format/…) always applies regardless.",
    },
    {
        "key": "admin_auto_checkpoint",
        "type": "boolean",
        "category": "safety",
        "default": True,
        "hint": "When admin_mode, best-effort git commit before mutating file/shell tools.",
    },
    {
        "key": "admin_blocklist_override",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "Relaxes admin-mode APPROVAL gating for otherwise-blocklisted tools. NOTE: the hard shell command blocklist (rm/dd/format/…) still applies regardless — this does not grant those commands. Do not enable on shared machines.",
    },
    {
        "key": "tool_approval_bypass",
        "type": "boolean",
        "category": "safety",
        "default": False,
        "hint": "DANGEROUS: auto-approve tools with no prompt and no checkpoint. GUARDED: while safe_mode is on (the default), this still does NOT skip approval for destructive tools (writes, shell, run_python, git, …) — to fully auto-approve those you must also turn safe_mode off. Ignored entirely when remote_enabled is on. Off by default; leave off unless you know what you're doing.",
    },
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
]


def get_editable_keys() -> set[str]:
    """Set of keys that can be edited via /settings API."""
    return {e["key"] for e in EDITABLE_SCHEMA}


_SCHEMA_BY_KEY: dict[str, dict[str, Any]] = {e["key"]: e for e in EDITABLE_SCHEMA}


def _is_float_field(entry: dict[str, Any]) -> bool:
    """A number field is float-typed if its default or a fractional bound is a float."""
    if isinstance(entry.get("default"), float):
        return True
    for bound in ("min", "max"):
        bv = entry.get(bound)
        if isinstance(bv, float) and not bv.is_integer():
            return True
    return False


def coerce_and_clamp(key: str, value: Any) -> Any:
    """Coerce a settings value to its schema type and clamp numbers to [min, max].

    Single source of truth used by BOTH the write path (POST /settings, presets,
    appearance) and the read path (runtime_safety.load_config). A malformed or
    out-of-range value therefore cannot reach the model layer regardless of whether
    it arrived from the UI/API or a hand-edited runtime_config.json — e.g.
    temperature=50 clamps to 1.5, n_gpu_layers=-999 clamps to -1, n_ctx="abc" falls
    back to the default. Unknown keys pass through unchanged; booleans are
    normalised; un-parseable numbers fall back to the schema default.
    """
    entry = _SCHEMA_BY_KEY.get(key)
    if entry is None:
        return value
    t = entry.get("type")
    if t == "number":
        if value is None:
            return entry.get("default")
        try:
            num = float(value)
        except (ValueError, TypeError):
            return entry.get("default")
        lo, hi = entry.get("min"), entry.get("max")
        if lo is not None and num < lo:
            num = float(lo)
        if hi is not None and num > hi:
            num = float(hi)
        return num if _is_float_field(entry) else int(num)
    if t == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    if t == "list":
        return normalize_list_value(value)
    return value


def describe_adjustment(key: str, requested: Any, stored: Any) -> str | None:
    """How `stored` differs from what the caller asked for — or None when it honoured it.

    `coerce_and_clamp` silently rewrites out-of-range and malformed input, and the save path
    then appended the key to `saved` unconditionally. So typing 500 into "Max tool calls"
    (max 50) produced a green "Settings saved" with 50 on disk, and {"max_tool_calls":
    "not-a-number"} produced {"ok": true, "saved": [...]} with the value silently replaced by
    the schema default. The write happened, so it is not a rejection; the value is not the
    user's, so it is not a clean save. It needs its own name:

      'clamped'    — a number outside [min, max], pinned to the bound
      'coerced'    — unparseable for its type, replaced by the schema default
      'normalized' — same value, tidier form (" a , b " → ["a","b"]); NOT reported

    Type-equivalent input (5 vs 5.0, "true" vs True) is a clean save, not an adjustment —
    reporting it would bury the two cases that matter in noise.
    """
    entry = _SCHEMA_BY_KEY.get(key)
    if entry is None or requested is stored:
        return None
    t = entry.get("type")
    if t == "number":
        if isinstance(requested, bool):
            return "coerced"
        try:
            num = float(requested)
        except (ValueError, TypeError):
            # Unparseable → coerce_and_clamp substituted the schema default.
            return "coerced"
        if float(stored) == num:
            return None
        lo, hi = entry.get("min"), entry.get("max")
        if (lo is not None and num < float(lo)) or (hi is not None and num > float(hi)):
            return "clamped"
        return "coerced"  # e.g. 2.7 → 2 on an int field
    if t == "boolean":
        return None if coerce_and_clamp(key, requested) == stored else "coerced"
    if t == "list":
        return None if normalize_list_value(requested) == stored else "coerced"
    return None if requested == stored else "coerced"


def normalize_list_value(value: Any) -> list[str]:
    """Coerce a `list`-typed setting to a de-duplicated list of non-empty strings.

    Accepts a real list or the comma/whitespace-separated string a text input produces,
    so the same key is writable from the UI, the API and a hand-edited config file.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("\n", ",").replace(" ", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(p).strip() for p in value]
    else:
        return []
    out: list[str] = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return out


def auto_tune_managed_keys() -> set[str]:
    """Editable settings that hardware auto-tune OVERWRITES on every config load.

    These are the keys where a UI edit is silently reverted unless the key is locked —
    the reason POST /settings must report them rather than answering a blanket ok:true.
    Imported lazily: auto_tune pulls in hardware detection, and config_schema must stay
    importable by everything (including that module) without a cycle.
    """
    try:
        from services.infrastructure.auto_tune import PROFILE_KEYS

        return set(PROFILE_KEYS) & get_editable_keys()
    except Exception:
        return set()


def get_schema_by_category() -> dict[str, list[dict]]:
    """Schema grouped by category for UI."""
    out: dict[str, list[dict]] = {}
    for e in EDITABLE_SCHEMA:
        cat = e.get("category", "advanced")
        out.setdefault(cat, []).append(e)
    return out


# Human-readable label overrides for keys the generic humanizer can't get right
# (acronyms, domain terms). Anything not listed is title-cased from the key.
_LABEL_OVERRIDES: dict[str, str] = {
    "n_ctx": "Context window (tokens)",
    "n_batch": "Batch size",
    "n_gpu_layers": "GPU layers",
    "max_tool_calls": "Max tool calls per turn",
    "max_runtime_seconds": "Max time per turn (seconds)",
    "tool_call_timeout_seconds": "Tool-call timeout (seconds)",
    "approval_ttl_seconds": "Approval expiry (seconds)",
    "completion_max_tokens": "Max reply length (tokens)",
    "enable_cot": "Chain-of-thought reasoning",
    "hyde_enabled": "HyDE retrieval",
    "use_chroma": "Use Chroma vector store",
    "nsfw_allowed": "Allow NSFW content",
    "tts_voice": "Voice (text-to-speech)",
    "tts_speed": "Speech speed",
    "whisper_model": "Speech-to-text model",
    "plugins_enabled": "Allow plugin code execution",
    "mcp_client_enabled": "MCP client",
    "remote_enabled": "Remote API access",
    "remote_api_key": "Remote API key",
    "remote_cors_origins": "Allowed browser origins (CORS)",
    "llama_server_url": "External llama.cpp server URL",
    "models_max_keep": "GGUF models to keep",
    "semantic_k": "Memories retrieved per query",
    "learnings_n": "Recent learnings injected",
    "people_codex_enabled": "Remember people you mention",
    "skill_deps_require_pinned": "Require pinned skill dependencies",
    "skill_packs_execute_enabled": "Allow skill packs to run code",
    "agent_hooks_enabled": "Allow agent hooks (subprocess)",
    "confirm_autonomous": "Confirm autonomous actions",
}

_LABEL_ACRONYMS = {"ui": "UI", "api": "API", "cors": "CORS", "url": "URL", "ttl": "TTL",
                   "id": "ID", "llm": "LLM", "gpu": "GPU", "cpu": "CPU", "tts": "TTS",
                   "stt": "STT", "cot": "CoT", "rag": "RAG", "mcp": "MCP", "nsfw": "NSFW",
                   "kv": "KV", "db": "DB", "os": "OS", "hyde": "HyDE"}


def humanize_key(key: str) -> str:
    """Turn a snake_case config key into a human-readable label."""
    if key in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[key]
    words = [w for w in str(key).split("_") if w]
    if not words:
        return str(key)
    out = []
    for i, w in enumerate(words):
        if w in _LABEL_ACRONYMS:
            out.append(_LABEL_ACRONYMS[w])
        elif i == 0:
            out.append(w[:1].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def get_schema_for_api() -> dict[str, Any]:
    """Schema formatted for GET /settings/schema. Attaches a human-readable label per field,
    plus WHO OWNS the field.

    Ten editable settings (n_ctx, n_batch, n_gpu_layers, n_threads, hyde_enabled,
    performance_mode, enable_self_reflection, completion_max_tokens, max_runtime_seconds,
    tool_call_timeout_seconds) are overwritten by hardware auto-tune on every config load.
    Editing one used to return ok:true and then silently revert; only ONE of the ten carried
    any warning at all. `auto_tune_owned` lets the UI mark them and offer the lock, so the
    control tells the truth about who is in charge of it before the user spends a change on it.
    """
    managed = auto_tune_managed_keys()
    try:
        import runtime_safety

        locked = set(normalize_list_value(runtime_safety.load_config().get("auto_tune_locked_keys")))
        tune_on = bool(runtime_safety.load_config().get("auto_tune_enabled", True))
    except Exception:
        locked, tune_on = set(), True

    fields = []
    for f in EDITABLE_SCHEMA:
        e = {**f, "label": f.get("label") or humanize_key(f["key"])}
        if f["key"] in managed:
            e["auto_tune_owned"] = True
            e["auto_tune_locked"] = f["key"] in locked
            e["auto_tune_active"] = tune_on and f["key"] not in locked
        fields.append(e)
    return {
        "categories": list(get_schema_by_category().keys()),
        "fields": fields,
        "config_file": "agent/runtime_config.json",
        "docs": "docs/CONFIG_REFERENCE.md",
        "presets": list(SETTINGS_PRESETS.keys()),
        "auto_tune_owned_keys": sorted(managed),
        "auto_tune_enabled": tune_on,
        "auto_tune_locked_keys": sorted(locked),
    }


# ── Feature themes ──────────────────────────────────────────────────────────
# High-level "feature areas" the user can switch on/off as a group, so an install only
# carries the capabilities it needs. Each theme maps to a DISJOINT set of runtime-config
# flags that ACTUALLY gate that feature (verified — no no-op toggles). A theme is "on" when
# every one of its flags is at its enabled value. Applying a theme sets exactly those flags
# (a whitelist), so this can never write an arbitrary key.
FEATURE_THEMES: list[dict[str, Any]] = [
    {
        "key": "automation",
        "label": "Background automation",
        "desc": "Scheduled study sessions and autonomous work while you're away.",
        "flags": {"scheduler_study_enabled": True},
    },
    {
        "key": "advanced_search",
        "label": "Advanced retrieval & search",
        "desc": "HyDE query expansion and the optional Elasticsearch backend for deeper memory search.",
        "flags": {"hyde_enabled": True, "elasticsearch_enabled": True},
    },
    {
        "key": "people_workspace",
        "label": "People & workspace awareness",
        "desc": "Remember people you mention and auto-scan your project for context.",
        "flags": {"people_codex_enabled": True, "project_discovery_auto_inject": True},
    },
    {
        "key": "clustering",
        "label": "Device clustering",
        "desc": "Distribute heavy work across paired devices on your network.",
        "flags": {"cluster_enabled": True},
    },
    {
        "key": "external_tools",
        "label": "External tools (MCP + plugins)",
        "desc": "Connect MCP tool servers and run skill plugins. Security-sensitive — enables code execution.",
        "flags": {"mcp_client_enabled": True, "plugins_enabled": True},
    },
    {
        "key": "remote_access",
        "label": "Remote access",
        "desc": "Reach Layla from another device over your network or a tunnel.",
        "flags": {"remote_enabled": True},
    },
]

# Every flag any theme controls — the whitelist apply is allowed to touch.
_THEME_FLAG_WHITELIST: set[str] = {k for t in FEATURE_THEMES for k in t["flags"]}


def get_feature_themes(cfg: dict[str, Any],
                       requested: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the themes with an on/off state read back from the EFFECTIVE config.

    C2 — three defects lived in the two lines this replaced.

    (1) `enabled = all(bool(cfg.get(k)) == bool(v) ...)` is the truthiness comparison
        `flag_satisfied` exists to kill: a flag downgraded to a truthy-but-wrong value (1,
        "true", "auto") read as ON. The manifest declares a VALUE; ask whether it holds.
    (2) `managed_flags` was `auto_tune_managed_keys() & flags` — a HARDCODED single-owner
        list, byte-for-byte the shape route_helpers had just deleted, and structurally blind
        to MATURITY_GATED_KEYS, security_policy, and every future owner. It now asks
        `key_owner`, so a theme held off by the maturity gate says so instead of appearing
        unowned. `managed_flags` is kept (it means what it always meant: the auto-tune-owned
        subset, which is the subset the lock remedy applies to) but is DERIVED from the
        registry rather than from a parallel intersection.
    (3) Packages were never consulted, so "Advanced retrieval & search" reported enabled:true
        with elasticsearch not installed — a capability advertised over an absent engine.

    A theme is `enabled` only when every flag holds its declared value in the effective config
    AND every package those flags need is installed.
    """
    from install.feature_status import key_missing_packages, key_owner
    from install.setup_profiles import flag_satisfied

    cfg = cfg or {}
    # Ownership is asked against a config with the lock list neutralised, i.e. "who would hold
    # this key if you were not already pinning it?" — the question both the ON path (do I need
    # to take a lock?) and the OFF path (is this lock mine to release?) actually pose. Asking
    # with the locks in place makes an already-locked key answer "nobody owns me", which is
    # true only for as long as the lock exists.
    probe_cfg = {**cfg, "auto_tune_locked_keys": []}
    out = []
    for t in FEATURE_THEMES:
        off_flags = [k for k, v in t["flags"].items() if not flag_satisfied(cfg.get(k), v)]
        missing: list[str] = []
        for k in t["flags"]:
            for d in key_missing_packages(k):
                if d not in missing:
                    missing.append(d)
        # `blocked_by` is EVIDENCE, not prediction: a flag is reported as held only when the
        # config FILE asks for the declared value and the effective config disagrees — the
        # same write-then-read gap the save path measures, asked without a write.
        #
        # The alternative (ask key_owner about every flag that is merely off) reads as "you
        # cannot turn this on", and that message is wrong wherever an owner blocks a DIFFERENT
        # path than this one. Driven: `remote_access` is off with no credential, so the
        # security_policy probe claims it — but that probe describes apply_setup's refusal,
        # and this surface writes remote_enabled anyway (see residuals). Reporting a
        # confident, actionable, wrong reason is the failure mode this slice exists to remove,
        # so an owner has to have actually held the key to be named.
        owners: list[dict[str, str]] = []
        if requested:
            for k in off_flags:
                if not flag_satisfied(requested.get(k), t["flags"][k]):
                    continue  # never asked for — it is off because nobody turned it on
                hit = key_owner(k, cfg)
                if hit:
                    owners.append({"key": k, "owner": hit[0], "reason": hit[1]})
        managed = [k for k in sorted(t["flags"])
                   if (key_owner(k, probe_cfg) or ("", ""))[0] == "auto_tune"]
        out.append({"key": t["key"], "label": t["label"], "desc": t["desc"],
                    "flags": list(t["flags"].keys()),
                    "enabled": (not off_flags) and (not missing),
                    "off_flags": off_flags,
                    "missing_packages": missing,
                    "blocked_by": owners,
                    "managed_flags": managed})
    return out


def feature_theme_updates(theme_key: str, enabled: bool,
                          cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return the {flag: value} updates to switch a theme on/off, or None if unknown.

    Enabling sets each flag to its theme value; disabling sets it to the opposite. Only
    flags in the theme's own declared set are returned (whitelist) — plus, when the theme
    owns any auto-tune-managed flag, an updated `auto_tune_locked_keys` so the setting the
    user just asked for survives the next config load instead of being reverted under them.
    """
    t = next((t for t in FEATURE_THEMES if t["key"] == theme_key), None)
    if not t:
        return None
    updates: dict[str, Any] = {k: (bool(v) if enabled else (not bool(v))) for k, v in t["flags"].items()}

    # C2: was `auto_tune_managed_keys() & set(t["flags"])` — the last parallel owner list on
    # these surfaces. It is now the registry's answer, asked with the lock list neutralised so
    # the OFF path can still recognise (and release) a lock the ON path took. Only auto-tune's
    # keys appear here because the lock is auto-tune's OWN remedy — auto_tune_locked_keys
    # cannot unlock a maturity-gated key, and pretending otherwise would send the operator to
    # a control that does nothing. The other owners are not silenced: they are reported by the
    # read-back in the POST handler, which is where an unfixable block belongs.
    from install.feature_status import key_owner

    probe_cfg = {**(cfg or {}), "auto_tune_locked_keys": []}
    managed = {k for k in t["flags"]
               if (key_owner(k, probe_cfg) or ("", ""))[0] == "auto_tune"}
    if managed:
        current = normalize_list_value((cfg or {}).get("auto_tune_locked_keys"))
        if enabled:
            updates["auto_tune_locked_keys"] = current + [k for k in sorted(managed) if k not in current]
        else:
            # Turning the theme off hands the key back to auto-tune — leaving it locked would
            # pin a hand value the user never chose.
            updates["auto_tune_locked_keys"] = [k for k in current if k not in managed]
    return updates


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

"""
Model router. Select models based on task type.
coding → code model, reasoning → reasoning model, chat → chat model.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

TASK_TYPES = ("coding", "reasoning", "chat", "default")


def _warn_router_model_missing(model_fn: str | None, label: str) -> None:
    m = (model_fn or "").strip()
    if not m:
        return
    try:
        import runtime_safety

        cfg0 = runtime_safety.load_config()
        probe = dict(cfg0)
        probe["model_filename"] = m
        p = runtime_safety.resolve_model_path(probe)
        if not p.exists():
            d = (cfg0.get("model_filename") or "").strip() or "model_filename"
            logger.warning(
                "model_router fallback: %s not found → using default at load (%s) [%s]",
                m, d, label,
            )
    except Exception:
        pass


def _select_return(sel: str | None, label: str) -> str | None:
    if sel is None:
        return None
    s = str(sel).strip()
    if not s:
        return None
    _warn_router_model_missing(s, label)
    return s
_ROUTER_CONFIG: dict[str, str | None] = {}

# Alias → common GGUF basename (resolved under models_dir; not a filesystem path)
MODEL_ALIASES: dict[str, str] = {
    "magicoder": "Magicoder-S-DS-6.7B-Instruct.Q4_K_M.gguf",
}


def reset_router_config_cache() -> None:
    """Clear cached routing config (tests / hot-reload)."""
    global _ROUTER_CONFIG
    _ROUTER_CONFIG = {}


def _resolve_models_block_alias(raw: str) -> str:
    """If value is a known alias, return mapped filename; else pass through."""
    s = (raw or "").strip()
    if not s:
        return ""
    key = s.lower().replace(" ", "_").replace(".gguf", "")
    if key in MODEL_ALIASES:
        return MODEL_ALIASES[key]
    return s


def _load_router_config() -> dict[str, str | None]:
    """Load model routing from config. Keys: coding_model, reasoning_model, chat_model, models{}."""
    global _ROUTER_CONFIG
    if _ROUTER_CONFIG:
        return _ROUTER_CONFIG
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        coding = (cfg.get("coding_model") or "").strip() or None
        reasoning = (cfg.get("reasoning_model") or "").strip() or None
        chat = (cfg.get("chat_model") or "").strip() or None
        default_fn = (cfg.get("model_filename") or "").strip() or None
        fallback_m: str | None = None

        models_block = cfg.get("models")
        if isinstance(models_block, dict):
            m_def = (_resolve_models_block_alias(str(models_block.get("default") or "")) or "").strip() or None
            m_code = (_resolve_models_block_alias(str(models_block.get("code") or "")) or "").strip() or None
            m_fast = (_resolve_models_block_alias(str(models_block.get("fast") or "")) or "").strip() or None
            m_fb = (_resolve_models_block_alias(str(models_block.get("fallback") or "")) or "").strip() or None
            if m_code:
                coding = coding or m_code
            if m_def:
                default_fn = m_def
            if m_fast:
                chat = chat or m_fast
            fallback_m = m_fb

        _ROUTER_CONFIG["coding"] = coding
        _ROUTER_CONFIG["reasoning"] = reasoning
        _ROUTER_CONFIG["chat"] = chat
        _ROUTER_CONFIG["default"] = default_fn
        _ROUTER_CONFIG["fallback_model"] = fallback_m
    except Exception:
        _ROUTER_CONFIG = {
            "coding": None, "reasoning": None, "chat": None,
            "default": None, "fallback_model": None,
        }
    return _ROUTER_CONFIG


def classify_task(text: str, context: str = "") -> str:
    """
    Classify task type from text. Returns 'coding', 'reasoning', 'chat', or 'default'.
    Uses keyword heuristics; optional context boosts coding when code-like.
    """
    t = (text or "").lower()
    ctx = (context or "").lower()
    coding_kw = (
        "code", "implement", "fix", "debug", "refactor", "write", "function", "class", "test", "lint",
    )
    code_ctx_signals = ("def ", "class ", "import ", ".py", "traceback", "error:", "pytest")
    if any(k in t for k in coding_kw) or any(sig in ctx for sig in code_ctx_signals):
        return "coding"
    reasoning_kw = ("analyze", "explain", "why", "compare", "evaluate", "reason", "logic", "proof")
    if len(t) > 400 or t.count("\n") > 6:
        return "reasoning"
    if any(k in t for k in reasoning_kw):
        return "reasoning"
    if len(t) < 100 and not any(k in t for k in ("research", "investigate", "search")):
        return "chat"
    return "default"


def route_model(task_type: str) -> str | None:
    """
    Return model filename for task type. None = use default from config.
    """
    cfg = _load_router_config()
    if task_type == "default":
        return cfg.get("default")
    model = cfg.get(task_type) or cfg.get("default")
    return model


def select_model(
    task: str,
    context_len: int,
    hardware: dict,
    latency_budget: int,
) -> str | None:
    """
    Task + hardware + latency aware model filename (for logging / routing).
    Uses llm_model_coding capability when coding; prefers coding_model when Magicoder wins benchmarks.
    """
    import runtime_safety

    cfg = runtime_safety.load_config()
    tt = task if task in TASK_TYPES else classify_task(task)
    try:
        from capabilities.registry import get_best_llm_filename_for_task

        best_fn = get_best_llm_filename_for_task(tt, cfg)
        if best_fn and str(best_fn).strip():
            return _select_return(str(best_fn).strip(), "capability_best")
    except Exception as e:
        logger.debug("select_model get_best: %s", e)
    if tt == "coding":
        try:
            lg = (cfg.get("coding_model_large_context") or "").strip()
            thresh = int(cfg.get("coding_large_context_threshold", 12000))
            if lg and int(context_len) >= thresh:
                return _select_return(_resolve_models_block_alias(lg), "coding_large_context")
        except Exception as e:
            logger.debug("select_model large_context: %s", e)
        try:
            from capabilities.registry import get_active_implementation

            impl = get_active_implementation("llm_model_coding", cfg)
            if impl and impl.id == "magicoder":
                cm = (cfg.get("coding_model") or "").strip()
                if cm:
                    return _select_return(_resolve_models_block_alias(cm), "coding_magicoder")
        except Exception as e:
            logger.debug("select_model coding capability: %s", e)
        # Latency: prefer fastest benchmarked among configured candidates if budget tight
        if latency_budget and latency_budget < 5000:
            try:
                candidates = [x for x in (route_model("coding"), cfg.get("model_filename")) if x]
                from services.model_benchmark import select_fastest_model

                fastest = select_fastest_model([str(c) for c in candidates if c])
                if fastest:
                    return _select_return(str(fastest), "benchmark_fastest")
            except Exception:
                pass
    try:
        from services.telemetry import get_user_profile

        profile = get_user_profile()
        if profile.get("simple_ratio", 0) > 0.7:
            chat_m = (cfg.get("chat_model") or cfg.get("model_filename") or "").strip()
            if chat_m:
                return _select_return(chat_m, "telemetry_chat")
    except Exception as e:
        logger.debug("select_model telemetry bias: %s", e)
    return _select_return(route_model(tt), "route_model")


def get_model_for_task(task_text: str) -> str | None:
    """
    Classify task and return appropriate model filename.
    Returns None to use default (current config model).
    """
    task_type = classify_task(task_text)
    return route_model(task_type)


def is_routing_enabled() -> bool:
    """True if model routing is configured (any task-specific model or models{} block)."""
    cfg = _load_router_config()
    if cfg.get("coding") or cfg.get("reasoning") or cfg.get("chat"):
        return True
    try:
        import runtime_safety
        mb = runtime_safety.load_config().get("models")
        if isinstance(mb, dict) and any(
            str(mb.get(k) or "").strip() for k in ("default", "code", "fast", "fallback")
        ):
            return True
    except Exception:
        pass
    return False


def get_fastest_benchmarked(available: list[str] | None = None) -> str | None:
    """
    Return filename of fastest benchmarked model from ~/.layla/benchmarks.json.
    If available is given, only consider those. Used when no explicit routing.
    """
    try:
        from services.model_benchmark import select_fastest_model
        return select_fastest_model(available)
    except Exception:
        return None


def get_benchmark_for_model(model_name: str) -> dict | None:
    """Return stored benchmark (tokens_per_sec, first_token_ms, memory_mb) for a model."""
    try:
        from services.model_benchmark import get_benchmark
        return get_benchmark(model_name)
    except Exception:
        return None

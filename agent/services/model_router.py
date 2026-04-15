"""
Model router. Select models based on task type.
coding → code model, reasoning → reasoning model, chat → chat model.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("layla")

TASK_TYPES = ("coding", "reasoning", "chat", "decision", "default")


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


def _router_fields_from_cfg(cfg: dict) -> dict[str, str | None]:
    """Derive routing fields from a config dict (no process-wide cache)."""
    coding = (cfg.get("coding_model") or "").strip() or None
    reasoning = (cfg.get("reasoning_model") or "").strip() or None
    chat = (cfg.get("chat_model") or "").strip() or None
    decision = (cfg.get("decision_model") or "").strip() or None
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

    return {
        "coding": coding,
        "reasoning": reasoning,
        "chat": chat,
        "decision": decision,
        "default": default_fn,
        "fallback_model": fallback_m,
    }


def _load_router_config() -> dict[str, str | None]:
    """Load model routing from config. Keys: coding_model, reasoning_model, chat_model, models{}."""
    global _ROUTER_CONFIG
    if _ROUTER_CONFIG:
        return _ROUTER_CONFIG
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        _ROUTER_CONFIG = _router_fields_from_cfg(cfg)
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


def _path_points_to_existing_file(path_str: str) -> str | None:
    """Return basename if path exists and is a file."""
    try:
        p = Path(path_str).expanduser().resolve()
        if p.is_file():
            return p.name
    except Exception:
        pass
    return None


def _basename_file_exists(cfg: dict, basename: str | None) -> bool:
    if not basename or not str(basename).strip():
        return False
    try:
        import runtime_safety

        probe = dict(cfg)
        probe["model_filename"] = str(basename).strip()
        return runtime_safety.resolve_model_path(probe).is_file()
    except Exception:
        return False


def resolve_dual_model_basenames(cfg: dict | None = None) -> tuple[str | None, str | None]:
    """
    Resolve chat + agent GGUF basenames for dual-model mode (under models_dir).
    Honors chat_model_path / agent_model_path when they point at existing files;
    otherwise uses router chat / coding / default basenames when those files exist.
    """
    import runtime_safety

    if cfg is None:
        cfg = runtime_safety.load_config()
    rf = _router_fields_from_cfg(cfg)
    chat_b: str | None = None
    agent_b: str | None = None

    cp = (cfg.get("chat_model_path") or "").strip()
    if cp:
        chat_b = _path_points_to_existing_file(cp)
    if not chat_b and rf.get("chat"):
        bn = str(rf["chat"]).strip()
        if bn and _basename_file_exists(cfg, bn):
            chat_b = bn

    ap = (cfg.get("agent_model_path") or "").strip()
    if ap:
        agent_b = _path_points_to_existing_file(ap)
    if not agent_b:
        for cand in (rf.get("coding"), rf.get("reasoning"), rf.get("default")):
            if not cand:
                continue
            bn = str(cand).strip()
            if bn and _basename_file_exists(cfg, bn):
                agent_b = bn
                break

    return (chat_b, agent_b)


def _fast_chat_configured(cfg: dict) -> bool:
    """True if a fast/chat model is configured (path, chat_model, or models.fast)."""
    p = (cfg.get("chat_model_path") or "").strip()
    if p:
        try:
            if Path(p).expanduser().resolve().is_file():
                return True
        except Exception:
            pass
    rf = _router_fields_from_cfg(cfg)
    if rf.get("chat"):
        return True
    mb = cfg.get("models")
    if isinstance(mb, dict) and str(mb.get("fast") or "").strip():
        return True
    return False


def classify_task_for_routing(text: str, context: str = "", cfg: dict | None = None) -> str:
    """
    Like classify_task, but optionally maps 'default' → 'chat' when route_default_to_chat_model
    is set and a fast/chat model is configured.
    """
    import runtime_safety

    if cfg is None:
        cfg = runtime_safety.load_config()
    t = classify_task(text, context)
    if t != "default":
        return t
    if not cfg.get("route_default_to_chat_model"):
        return t
    if not _fast_chat_configured(cfg):
        return t
    return "chat"


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

    # Soft adaptive bias: prefer models with a materially higher historical success rate
    # for this task type (when enough samples exist).
    try:
        from services.telemetry import get_model_success_rates

        stats = get_model_success_rates(min_count=5)
        if isinstance(stats, dict) and stats:
            base = _select_return(route_model(tt), "route_model") or _select_return(cfg.get("model_filename"), "default")
            if base:
                best = base
                best_sr = None
                base_sr = None
                for model_name, by_task in stats.items():
                    if not isinstance(by_task, dict):
                        continue
                    row = by_task.get(tt) or by_task.get("default")
                    if not isinstance(row, dict):
                        continue
                    sr = row.get("success_rate")
                    if sr is None:
                        continue
                    try:
                        sr_f = float(sr)
                    except Exception:
                        continue
                    if model_name == base:
                        base_sr = sr_f
                    if best_sr is None or sr_f > best_sr:
                        best_sr = sr_f
                        best = model_name
                if base_sr is not None and best_sr is not None:
                    # Require a meaningful lift to avoid noise and oscillation.
                    if (best_sr - base_sr) >= 0.20:
                        return _select_return(best, "adaptive_success_rate")
    except Exception:
        pass
    return _select_return(route_model(tt), "route_model")


def get_model_for_task(task_text: str) -> str | None:
    """
    Classify task and return appropriate model filename.
    Returns None to use default (current config model).
    """
    task_type = classify_task(task_text)
    return route_model(task_type)


def is_routing_enabled() -> bool:
    """True if model routing is configured (task models, models{}, dual paths, or force_dual_models)."""
    cfg = _load_router_config()
    if cfg.get("coding") or cfg.get("reasoning") or cfg.get("chat"):
        return True
    try:
        import runtime_safety

        raw = runtime_safety.load_config()
        mb = raw.get("models")
        if isinstance(mb, dict) and any(
            str(mb.get(k) or "").strip() for k in ("default", "code", "fast", "fallback")
        ):
            return True
        if (raw.get("chat_model_path") or "").strip() or (raw.get("agent_model_path") or "").strip():
            return True
        if raw.get("force_dual_models"):
            chat_b, agent_b = resolve_dual_model_basenames(raw)
            return bool(chat_b and agent_b)
    except Exception:
        pass
    return False


def get_model_routing_summary(cfg: dict | None = None) -> dict:
    """Read-only snapshot for /health and /platform/models (no LLM load)."""
    import runtime_safety
    from services.resource_manager import should_use_dual_models

    if cfg is None:
        cfg = runtime_safety.load_config()
    chat_b, agent_b = resolve_dual_model_basenames(cfg)
    return {
        "routing_enabled": is_routing_enabled(),
        "dual_models_active": should_use_dual_models(),
        "force_dual_models": bool(cfg.get("force_dual_models")),
        "route_default_to_chat_model": bool(cfg.get("route_default_to_chat_model")),
        "chat_basename": chat_b,
        "agent_basename": agent_b,
        "dual_model_threshold_gb": cfg.get("dual_model_threshold_gb", 24),
    }


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

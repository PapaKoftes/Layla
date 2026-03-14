"""
Model router. Select models based on task type.
coding → code model, reasoning → reasoning model, chat → chat model.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("layla")

TASK_TYPES = ("coding", "reasoning", "chat", "default")
_ROUTER_CONFIG: dict[str, str] = {}


def _load_router_config() -> dict[str, str | None]:
    """Load model routing from config. Keys: coding_model, reasoning_model, chat_model."""
    global _ROUTER_CONFIG
    if _ROUTER_CONFIG:
        return _ROUTER_CONFIG
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        for k, cfg_key in [("coding", "coding_model"), ("reasoning", "reasoning_model"), ("chat", "chat_model")]:
            v = (cfg.get(cfg_key) or "").strip()
            _ROUTER_CONFIG[k] = v or None
        _ROUTER_CONFIG["default"] = (cfg.get("model_filename") or "").strip() or None
    except Exception:
        pass
    return _ROUTER_CONFIG


def classify_task(text: str) -> str:
    """
    Classify task type from text. Returns 'coding', 'reasoning', 'chat', or 'default'.
    Uses keyword heuristics; can be extended with LLM classification.
    """
    t = (text or "").lower()
    coding_kw = ("code", "implement", "fix", "debug", "refactor", "write", "function", "class", "test", "lint")
    reasoning_kw = ("analyze", "explain", "why", "compare", "evaluate", "reason", "logic", "proof")
    if any(k in t for k in coding_kw):
        return "coding"
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
    model = cfg.get(task_type) or cfg.get("default")
    return model


def get_model_for_task(task_text: str) -> str | None:
    """
    Classify task and return appropriate model filename.
    Returns None to use default (current config model).
    """
    task_type = classify_task(task_text)
    return route_model(task_type)


def is_routing_enabled() -> bool:
    """True if model routing is configured (any task-specific model set)."""
    cfg = _load_router_config()
    return bool(cfg.get("coding") or cfg.get("reasoning") or cfg.get("chat"))

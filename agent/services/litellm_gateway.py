"""
LiteLLM multi-provider gateway for Layla.

Wraps litellm to provide unified access to 100+ LLM providers through a single
interface. Supports:
- Provider failover (anthropic → ollama → groq → together → ...)
- Streaming (compatible with existing SSE pipeline)
- Cost tracking (via litellm callbacks + provider_health)
- Circuit-breaker integration (unhealthy providers are skipped)

Config keys (runtime_safety.py):
  litellm_enabled: bool          — master switch (default false)
  litellm_default_model: str     — default model (e.g. "anthropic/claude-3-5-sonnet-20241022")
  litellm_fallback_chain: list   — ordered list of model strings for failover
  litellm_api_keys: dict         — provider → API key mapping
  litellm_timeout_seconds: int   — per-request timeout
  litellm_max_retries: int       — retries before moving to next provider
"""
from __future__ import annotations

import logging
import time
from typing import Any, Generator

logger = logging.getLogger("layla")

_litellm = None  # lazy import


def _import_litellm():
    """Lazy-import litellm to avoid startup cost when disabled."""
    global _litellm
    if _litellm is not None:
        return _litellm
    try:
        import litellm
        # Suppress litellm's verbose logging
        litellm.suppress_debug_info = True
        litellm.set_verbose = False
        _litellm = litellm
        return _litellm
    except ImportError:
        logger.warning("litellm not installed; multi-provider gateway unavailable (pip install litellm)")
        return None


def _extract_provider_name(model_string: str) -> str:
    """Extract provider name from litellm model string (e.g. 'anthropic/claude-3' → 'anthropic')."""
    if "/" in model_string:
        return model_string.split("/", 1)[0]
    # Common prefixes
    for prefix in ("gpt-", "o1-", "o3-"):
        if model_string.startswith(prefix):
            return "openai"
    if model_string.startswith("claude-"):
        return "anthropic"
    if model_string.startswith("gemini"):
        return "google"
    return model_string.split("-")[0] if "-" in model_string else "unknown"


def _configure_api_keys(cfg: dict) -> None:
    """Set API keys from config into litellm/environment."""
    import os
    keys = cfg.get("litellm_api_keys", {})
    if not isinstance(keys, dict):
        return
    key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "together": "TOGETHER_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "cohere": "COHERE_API_KEY",
        "google": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    for provider, env_var in key_map.items():
        api_key = (keys.get(provider) or "").strip()
        if api_key and not os.environ.get(env_var):
            os.environ[env_var] = api_key


def _safe_int(val: Any, default: int) -> int:
    """Safely convert *val* to int, returning *default* on failure."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _load_gateway_config() -> dict:
    """Load litellm-specific config from runtime_safety."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    return {
        "enabled": bool(cfg.get("litellm_enabled", False)),
        "default_model": (cfg.get("litellm_default_model") or "").strip(),
        "fallback_chain": cfg.get("litellm_fallback_chain") or [],
        "api_keys": cfg.get("litellm_api_keys") or {},
        "timeout": _safe_int(cfg.get("litellm_timeout_seconds"), 120),
        "max_retries": _safe_int(cfg.get("litellm_max_retries"), 2),
        "raw_cfg": cfg,
    }


def is_available() -> bool:
    """Check if litellm is installed and enabled in config."""
    gcfg = _load_gateway_config()
    if not gcfg["enabled"]:
        return False
    return _import_litellm() is not None


def get_supported_models() -> list[str]:
    """List models litellm claims to support (static list from package)."""
    lit = _import_litellm()
    if lit is None:
        return []
    try:
        return list(lit.model_list) if hasattr(lit, "model_list") else []
    except Exception:
        return []


# ── Completion (sync, non-streaming) ─────────────────────────────────────────


def complete(
    messages: list[dict[str, str]],
    model: str | None = None,
    *,
    max_tokens: int = 512,
    temperature: float = 0.2,
    stop: list[str] | None = None,
    timeout: int | None = None,
    fallback_chain: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run a completion through litellm with failover.

    Returns dict with keys: content, model, provider, latency_ms, cost_usd, usage.
    Raises RuntimeError if all providers fail.
    """
    from services.provider_health import record_success, record_failure, is_healthy

    lit = _import_litellm()
    if lit is None:
        raise RuntimeError("litellm not installed")

    gcfg = _load_gateway_config()
    _configure_api_keys(gcfg["raw_cfg"])

    effective_model = model or gcfg["default_model"]
    if not effective_model:
        raise ValueError("No model specified and litellm_default_model not configured")

    chain = fallback_chain or gcfg["fallback_chain"] or []
    # Build ordered attempt list: primary model first, then fallback chain
    models_to_try = [effective_model] + [m for m in chain if m != effective_model]

    effective_timeout = timeout if timeout is not None else gcfg["timeout"]
    max_retries = gcfg["max_retries"]

    last_error: Exception | None = None

    for model_str in models_to_try:
        provider = _extract_provider_name(model_str)
        if not is_healthy(provider):
            logger.debug("litellm_gateway: skipping unhealthy provider %s", provider)
            continue

        for attempt in range(max_retries + 1):
            t0 = time.monotonic()
            try:
                response = lit.completion(
                    model=model_str,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop or [],
                    timeout=effective_timeout,
                )
                latency = time.monotonic() - t0
                content = response.choices[0].message.content or ""
                usage = {}
                cost = 0.0
                if hasattr(response, "usage") and response.usage:
                    usage = {
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    }
                try:
                    cost = lit.completion_cost(completion_response=response)
                except Exception:
                    pass

                record_success(provider, latency_seconds=latency, cost_usd=cost)
                return {
                    "content": content,
                    "model": model_str,
                    "provider": provider,
                    "latency_ms": round(latency * 1000, 1),
                    "cost_usd": cost,
                    "usage": usage,
                }
            except Exception as e:
                latency = time.monotonic() - t0
                last_error = e
                error_msg = f"{type(e).__name__}: {e!s}"[:300]
                logger.warning(
                    "litellm_gateway: %s attempt %d/%d failed (%.1fs): %s",
                    model_str, attempt + 1, max_retries + 1, latency, error_msg,
                )
                if attempt == max_retries:
                    record_failure(provider, error=error_msg)

    raise RuntimeError(
        f"All providers failed. Last error: {last_error!s}" if last_error
        else "No healthy providers available"
    )


# ── Completion (streaming) ───────────────────────────────────────────────────


def complete_stream(
    messages: list[dict[str, str]],
    model: str | None = None,
    *,
    max_tokens: int = 512,
    temperature: float = 0.2,
    stop: list[str] | None = None,
    timeout: int | None = None,
    fallback_chain: list[str] | None = None,
) -> Generator[str, None, None]:
    """
    Stream a completion through litellm with failover.

    Yields text chunks. On provider failure, transparently switches to next in chain.
    """
    from services.provider_health import record_success, record_failure, is_healthy

    lit = _import_litellm()
    if lit is None:
        raise RuntimeError("litellm not installed")

    gcfg = _load_gateway_config()
    _configure_api_keys(gcfg["raw_cfg"])

    effective_model = model or gcfg["default_model"]
    if not effective_model:
        raise ValueError("No model specified and litellm_default_model not configured")

    chain = fallback_chain or gcfg["fallback_chain"] or []
    models_to_try = [effective_model] + [m for m in chain if m != effective_model]
    effective_timeout = timeout if timeout is not None else gcfg["timeout"]

    last_error: Exception | None = None

    for model_str in models_to_try:
        provider = _extract_provider_name(model_str)
        if not is_healthy(provider):
            logger.debug("litellm_gateway: skipping unhealthy provider %s (stream)", provider)
            continue

        t0 = time.monotonic()
        try:
            response = lit.completion(
                model=model_str,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop or [],
                timeout=effective_timeout,
                stream=True,
            )
            chunk_count = 0
            for chunk in response:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    text = getattr(delta, "content", None)
                    if text:
                        chunk_count += 1
                        yield text

            latency = time.monotonic() - t0
            record_success(provider, latency_seconds=latency)
            return  # Success — done streaming
        except Exception as e:
            last_error = e
            error_msg = f"{type(e).__name__}: {e!s}"[:300]
            logger.warning(
                "litellm_gateway: %s streaming failed: %s", model_str, error_msg,
            )
            record_failure(provider, error=error_msg)

    raise RuntimeError(
        f"All providers failed (stream). Last error: {last_error!s}" if last_error
        else "No healthy providers available"
    )


# ── Prompt → Messages conversion ────────────────────────────────────────────


def prompt_to_messages(prompt: str) -> list[dict[str, str]]:
    """Convert a raw prompt string to messages format for litellm."""
    # Simple heuristic: if it looks like it has a system block, split it
    if prompt.startswith("[") and "You are" in prompt[:200]:
        # Likely has a system prompt block
        # Find where the system block ends (first double newline after opening)
        end = prompt.find("\n\n", 100)
        if end > 0:
            return [
                {"role": "system", "content": prompt[:end].strip()},
                {"role": "user", "content": prompt[end:].strip()},
            ]
    return [{"role": "user", "content": prompt}]


# ── Integration with inference_router ────────────────────────────────────────


def run_completion_litellm(
    cfg: dict,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stop: list[str] | None = None,
    stream: bool = False,
    timeout: int | None = None,
    model_name: str | None = None,
) -> dict | Generator[str, None, None]:
    """
    Drop-in compatible with inference_router's run_completion_* functions.

    Returns dict (non-streaming) or Generator[str] (streaming).
    Non-streaming returns {"choices": [{"message": {"content": "..."}}]} for compat.
    """
    messages = prompt_to_messages(prompt)

    # Resolve model: use model_name if provided, else litellm_default_model from cfg
    model = model_name
    if not model:
        model = (cfg.get("litellm_default_model") or "").strip()
    fallback_chain = cfg.get("litellm_fallback_chain") or []

    if stream:
        return complete_stream(
            messages, model=model,
            max_tokens=max_tokens, temperature=temperature,
            stop=stop, timeout=timeout,
            fallback_chain=fallback_chain,
        )
    else:
        result = complete(
            messages, model=model,
            max_tokens=max_tokens, temperature=temperature,
            stop=stop, timeout=timeout,
            fallback_chain=fallback_chain,
        )
        # Convert to OpenAI-compatible format for inference_router compat
        return {
            "choices": [{
                "message": {"content": result["content"]},
                "finish_reason": "stop",
            }],
            "_litellm_meta": {
                "model": result["model"],
                "provider": result["provider"],
                "latency_ms": result["latency_ms"],
                "cost_usd": result["cost_usd"],
                "usage": result["usage"],
            },
        }


# ── Status & info ────────────────────────────────────────────────────────────


def get_gateway_info() -> dict:
    """Return gateway status for /health and /models/providers endpoints."""
    gcfg = _load_gateway_config()
    installed = _import_litellm() is not None
    from services.provider_health import get_all_status
    return {
        "installed": installed,
        "enabled": gcfg["enabled"],
        "default_model": gcfg["default_model"],
        "fallback_chain": gcfg["fallback_chain"],
        "provider_health": get_all_status(),
    }

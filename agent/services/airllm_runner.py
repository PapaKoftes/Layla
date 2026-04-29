"""
airllm_runner.py — Layer-by-layer local large model inference via AirLLM.

AirLLM (https://github.com/lyogavin/airllm) enables running models up to 70B+
on a single consumer GPU by loading one transformer layer at a time. This lets
Layla run offline large models (Mistral 70B, LLaMA-3 70B, Falcon 40B, etc.)
without needing 140GB of VRAM.

Trade-off: generation is ~10-50x slower than fully-loaded inference, but it works
on 4-8GB VRAM cards. Best for long-form autonomous tasks, research generation,
and KB synthesis where speed is less critical than capability.

Config keys in config.json:
    airllm_enabled          bool    — Enable AirLLM (default false; requires airllm package)
    airllm_model_path       str     — HuggingFace model ID or local path
                                      e.g. "mistralai/Mistral-7B-Instruct-v0.2"
                                      or "C:/models/llama-3-70b"
    airllm_cache_dir        str     — Where AirLLM stores layer shards (default: agent/.airllm_cache)
    airllm_max_new_tokens   int     — Max tokens to generate (default 512)
    airllm_compression      str     — "4bit" | "8bit" | None (None = bf16/fp16 default)
    airllm_device           str     — "cuda" | "cpu" (default "cuda" if available)

Usage:
    from services.airllm_runner import generate, is_available

    if is_available():
        response = generate("Write a poem about recursion", max_tokens=200)
        print(response["text"])
    else:
        print("AirLLM not configured or not installed")

The module is entirely lazy — importing it never errors even if airllm is missing.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_DEFAULT_CACHE = str(Path(__file__).resolve().parent.parent / ".airllm_cache")
_model_cache: dict[str, Any] = {}  # model_path → loaded AirLLM model


# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        import json
        p = Path(__file__).resolve().parent.parent / "config.json"
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _enabled() -> bool:
    return bool(_cfg().get("airllm_enabled", False))


def _model_path() -> str:
    return _cfg().get("airllm_model_path", "")


def _cache_dir() -> str:
    return _cfg().get("airllm_cache_dir", _DEFAULT_CACHE)


def _max_new_tokens() -> int:
    return int(_cfg().get("airllm_max_new_tokens", 512))


def _compression() -> str | None:
    v = _cfg().get("airllm_compression", None)
    return v if v in ("4bit", "8bit") else None


def _device() -> str:
    d = _cfg().get("airllm_device", "auto")
    if d == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return d


# ── Availability check ────────────────────────────────────────────────────────

def is_available() -> bool:
    """Return True only when airllm is installed, enabled, and a model path is set."""
    if not _enabled():
        return False
    if not _model_path():
        return False
    try:
        import airllm  # noqa: F401
        return True
    except ImportError:
        return False


def get_info() -> dict:
    """Return diagnostic info about AirLLM configuration."""
    try:
        import airllm
        airllm_version = getattr(airllm, "__version__", "unknown")
    except ImportError:
        airllm_version = None

    cfg = _cfg()
    return {
        "enabled": _enabled(),
        "installed": airllm_version is not None,
        "airllm_version": airllm_version,
        "model_path": _model_path() or None,
        "cache_dir": _cache_dir(),
        "compression": _compression(),
        "device": _device(),
        "max_new_tokens": _max_new_tokens(),
        "model_loaded": _model_path() in _model_cache,
        "available": is_available(),
    }


# ── Model loader ──────────────────────────────────────────────────────────────

def _load_model(model_path: str) -> Any:
    """Load (or return cached) AirLLM model. Thread-unsafe; call under a lock if needed."""
    if model_path in _model_cache:
        return _model_cache[model_path]

    import airllm

    logger.info("airllm_runner: loading model '%s' (this may take a minute)...", model_path)
    t0 = time.monotonic()

    cache_dir = _cache_dir()
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    compression = _compression()

    kwargs: dict = {
        "model": model_path,
        "profiling_mode": False,
    }
    if compression == "4bit":
        kwargs["compression"] = "4bit"
    elif compression == "8bit":
        kwargs["compression"] = "8bit"

    # AirLLM model class: AutoModel for general HF models
    model = airllm.AutoModel.from_pretrained(model_path, **kwargs)
    elapsed = time.monotonic() - t0
    logger.info("airllm_runner: model loaded in %.1fs", elapsed)
    _model_cache[model_path] = model
    return model


def unload_model(model_path: str | None = None) -> None:
    """Unload model from memory. Pass None to unload all."""
    if model_path:
        _model_cache.pop(model_path, None)
    else:
        _model_cache.clear()
    try:
        import torch, gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ── Generation ────────────────────────────────────────────────────────────────

def generate(
    prompt: str,
    *,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    model_path: str | None = None,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> dict:
    """
    Generate text from a local model via AirLLM.

    Returns:
        {
            "ok": True,
            "text": "...",
            "model": "model/path",
            "tokens_generated": 123,
            "duration_ms": 4500,
            "device": "cuda",
        }
    On failure returns {"ok": False, "error": "..."}
    """
    if not _enabled():
        return {"ok": False, "error": "AirLLM not enabled (set airllm_enabled=true in config.json)"}

    mp = model_path or _model_path()
    if not mp:
        return {"ok": False, "error": "No airllm_model_path set in config.json"}

    try:
        import airllm  # noqa: F401
    except ImportError:
        return {"ok": False, "error": "airllm package not installed (pip install airllm)"}

    max_new = max_tokens if max_tokens is not None else _max_new_tokens()

    try:
        model = _load_model(mp)
        t0 = time.monotonic()

        # Build tokenized input
        import torch
        device = _device()

        # AirLLM uses the underlying tokenizer
        tokenizer = model.tokenizer
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        input_len = inputs["input_ids"].shape[1]

        gen_kwargs: dict = {
            "max_new_tokens": max_new,
            "do_sample": temperature > 0,
        }
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
            gen_kwargs["top_p"] = top_p

        with torch.no_grad():
            output_ids = model.generate(**inputs, **gen_kwargs)

        # Decode only newly generated tokens (not the prompt)
        new_ids = output_ids[0][input_len:]
        text = tokenizer.decode(new_ids, skip_special_tokens=True)

        # Apply stop sequences
        if stop:
            for s in stop:
                if s in text:
                    text = text[:text.index(s)]

        duration_ms = int((time.monotonic() - t0) * 1000)
        tokens_generated = len(new_ids)

        logger.info(
            "airllm_runner: generated %d tokens in %dms (%.1f tok/s)",
            tokens_generated, duration_ms, tokens_generated / max(0.001, duration_ms / 1000),
        )

        return {
            "ok": True,
            "text": text.strip(),
            "model": mp,
            "tokens_generated": tokens_generated,
            "duration_ms": duration_ms,
            "device": device,
        }

    except Exception as exc:
        logger.error("airllm_runner: generation failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def generate_chat(
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    model_path: str | None = None,
    temperature: float = 0.7,
) -> dict:
    """
    Chat-style generation. messages = [{"role": "user"|"assistant"|"system", "content": "..."}]
    Formats the conversation using the model's chat template if available, then calls generate().
    """
    mp = model_path or _model_path()
    if not mp:
        return {"ok": False, "error": "No airllm_model_path set"}

    # Format messages into a single prompt string
    # Use HuggingFace chat template if available
    try:
        _load_model(mp)  # Ensure loaded
        model = _model_cache.get(mp)
        if model and hasattr(model, "tokenizer") and hasattr(model.tokenizer, "apply_chat_template"):
            prompt = model.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            # Generic fallback: build a simple prompt
            parts = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    parts.append(f"[System]: {content}")
                elif role == "assistant":
                    parts.append(f"[Assistant]: {content}")
                else:
                    parts.append(f"[User]: {content}")
            parts.append("[Assistant]:")
            prompt = "\n".join(parts)
    except Exception as exc:
        return {"ok": False, "error": f"Chat template error: {exc}"}

    return generate(prompt, max_tokens=max_tokens, temperature=temperature, model_path=mp)

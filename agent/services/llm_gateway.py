"""
Shared LLM completion gateway. Single point of access for local Llama or remote
OpenAI-compatible server. Serializes all completion calls so they never run concurrently.
"""
import logging
import os
import threading
import time
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_llm = None
_llm_lock = threading.Lock()
# Exposed so agent_loop can serialize full autonomous_run (one run at a time for LLM)
llm_serialize_lock = _llm_lock

# Per-request model override: "default" | "coding" | "reasoning" | "chat" (for remote backends)
_model_override_var: ContextVar[str | None] = ContextVar("model_override", default=None)
# Per-request reasoning: "high" = use reasoning_budget from config for thinking models
_reasoning_effort_var: ContextVar[str | None] = ContextVar("reasoning_effort", default=None)


def set_model_override(override: str | None) -> None:
    """Set model override for current request. Used by agent router."""
    _model_override_var.set(override)


def get_model_override() -> str | None:
    """Get model override for current request."""
    return _model_override_var.get(None)


def set_reasoning_effort(effort: str | None) -> None:
    """Set reasoning effort for current request. 'high' = use reasoning_budget."""
    _reasoning_effort_var.set(effort)


def get_reasoning_effort() -> str | None:
    """Get reasoning effort for current request."""
    return _reasoning_effort_var.get(None)


# Token usage tracking (session totals since server start)
_token_usage_lock = threading.Lock()
_token_usage = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "request_count": 0,
    "session_start": time.time(),
}


def model_loaded_status() -> dict:
    """Return model status for /health. If path invalid, includes error message."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        url = (cfg.get("llama_server_url") or "").strip()
        if url:
            return {"remote": True, "error": None}
        model_filename = cfg.get("model_filename", "your-model.gguf")
        if not model_filename or model_filename == "your-model.gguf":
            return {"error": "Model not loaded. Please configure model_filename in runtime_config.json"}
        model_path = runtime_safety.resolve_model_path(cfg)
        if not model_path.exists():
            return {"error": "Model not loaded. Please configure model_path in runtime_config.json and place the .gguf file in models/"}
        if _llm is not None:
            return {"error": None}
        return {"error": None}
    except Exception as e:
        return {"error": str(e)}


def _auto_threads() -> int:
    """Best thread count for inference: physical cores only, capped sensibly."""
    try:
        # psutil gives physical core count (no HT), which beats logical for LLM
        import psutil
        cores = psutil.cpu_count(logical=False) or os.cpu_count() or 4
    except Exception:
        cores = os.cpu_count() or 4
    # Leave one core free for OS + FastAPI; cap at 16 (diminishing returns above that)
    return max(1, min(cores - 1, 16))


def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama

        import runtime_safety
        cfg = runtime_safety.load_config()
        model_filename = cfg.get("model_filename", "your-model.gguf")
        model_path = runtime_safety.resolve_model_path(cfg)

        n_ctx = max(512, int(cfg.get("n_ctx", 4096)))
        n_batch = max(1, min(n_ctx, int(cfg.get("n_batch", 512))))

        # Auto-detect thread counts if not in config
        auto_t = _auto_threads()
        n_threads = max(1, int(cfg["n_threads"])) if cfg.get("n_threads") else auto_t
        # Batch threads: more threads help here; use logical count capped at 2× physical
        n_threads_batch = (
            max(1, int(cfg["n_threads_batch"])) if cfg.get("n_threads_batch")
            else min(n_threads * 2, (os.cpu_count() or n_threads))
        )

        # n_keep: pin this many tokens in KV cache during context-shifting.
        # Set to system prompt token estimate so the identity is never evicted.
        # ~1 token per 4 chars; system prompts are typically 500-2000 chars.
        n_keep = max(64, int(cfg.get("n_keep", 512)))

        kwargs = {
            "model_path": str(model_path),
            "n_ctx": n_ctx,
            "n_gpu_layers": int(cfg.get("n_gpu_layers", -1)),  # -1 = full GPU offload when VRAM allows
            "n_batch": n_batch,
            "n_threads": n_threads,
            "n_threads_batch": n_threads_batch,
            "use_mlock": bool(cfg.get("use_mlock", False)),
            "use_mmap": bool(cfg.get("use_mmap", True)),
            "verbose": False,
            # Flash attention: dramatically reduces VRAM + speeds up long contexts
            "flash_attn": bool(cfg.get("flash_attn", True)),
            # KV-cache quantization: int8 halves VRAM for KV cache (safe quality tradeoff)
            "type_k": int(cfg.get("type_k", 8)),   # 8 = GGML_TYPE_Q8_0
            "type_v": int(cfg.get("type_v", 8)),
            # Pin system-prompt tokens in KV cache — never re-evaluated on context shift
            "n_keep": n_keep,
        }

        # Rope scaling for extended contexts
        if cfg.get("rope_freq_base"):
            kwargs["rope_freq_base"] = float(cfg["rope_freq_base"])
        if cfg.get("rope_freq_scale"):
            kwargs["rope_freq_scale"] = float(cfg["rope_freq_scale"])

        try:
            _llm = Llama(**kwargs)
        except TypeError:
            # Older llama-cpp-python may not support all kwargs; retry with safe subset
            safe_keys = {"model_path", "n_ctx", "n_gpu_layers", "n_batch",
                         "n_threads", "n_threads_batch", "use_mlock", "use_mmap", "verbose"}
            _llm = Llama(**{k: v for k, v in kwargs.items() if k in safe_keys})

        logger.info(
            "LLM loaded: %s | ctx=%d batch=%d n_keep=%d gpu_layers=%s threads=%d/%d flash=%s",
            model_filename, n_ctx, n_batch, n_keep, kwargs["n_gpu_layers"],
            n_threads, n_threads_batch, kwargs.get("flash_attn"),
        )
        if cfg.get("benchmark_on_load"):
            try:
                from services.model_benchmark import run_benchmark
                res = run_benchmark(model_filename)
                if res.get("ok") and res.get("tokens_per_sec"):
                    logger.info("Model benchmark: %.1f tokens/sec", res["tokens_per_sec"])
            except Exception as e:
                logger.debug("benchmark on load skipped: %s", e)
    return _llm


def prewarm_llm() -> None:
    """Load the LLM in a background thread at startup so first request is instant."""
    def _load():
        try:
            with _llm_lock:
                _get_llm()
            logger.info("LLM pre-warm complete.")
        except Exception as e:
            logger.warning("LLM pre-warm failed: %s", e)

    t = threading.Thread(target=_load, daemon=True, name="llm-prewarm")
    t.start()


def get_stop_sequences():
    """Stop sequences so the model does not continue into the next turn."""
    import runtime_safety
    cfg = runtime_safety.load_config()
    stop = cfg.get("stop_sequences")
    if isinstance(stop, list) and stop:
        return [str(s) for s in stop if s]
    return ["\nUser:", " User:"]


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base, approximate for GGUF)."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception as e:
        logger.debug("tiktoken count failed: %s", e)
        return max(0, len(text) // 4)


def _add_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Add token counts to session totals."""
    with _token_usage_lock:
        _token_usage["prompt_tokens"] += prompt_tokens
        _token_usage["completion_tokens"] += completion_tokens
        _token_usage["total_tokens"] += prompt_tokens + completion_tokens
        _token_usage["request_count"] += 1


def get_token_usage() -> dict:
    """Return session token usage for /usage or /health."""
    with _token_usage_lock:
        return {
            "prompt_tokens": _token_usage["prompt_tokens"],
            "completion_tokens": _token_usage["completion_tokens"],
            "total_tokens": _token_usage["total_tokens"],
            "request_count": _token_usage["request_count"],
            "session_start": _token_usage["session_start"],
        }


def run_completion(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list | None = None,
    timeout_seconds: int | None = None,
):
    """
    Run completion via inference_router (llama_cpp, openai_compatible, or ollama).
    If stream=True, yields token strings; else returns {"choices": [{"message": {"content": text}}]}.
    timeout_seconds: used for remote HTTP only; local Llama has no timeout in this call.
    Token usage is tracked for /usage endpoint.
    """
    from services.inference_router import run_completion as _run

    prompt_tokens = _count_tokens(prompt)
    model_override = get_model_override()
    reasoning_effort = get_reasoning_effort()
    reasoning_budget = None
    if reasoning_effort == "high":
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
            budget = cfg.get("reasoning_budget", -1)
            if budget != 0:
                reasoning_budget = int(budget) if budget else -1
        except Exception:
            pass

    if stream:
        def _counting_gen():
            completion_tokens = 0
            inner = _run(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stop=stop,
                timeout_seconds=timeout_seconds,
                _get_llm=_get_llm,
                _llm_lock=_llm_lock,
                model_override=model_override,
                reasoning_budget=reasoning_budget,
            )
            try:
                for chunk in inner:
                    completion_tokens += _count_tokens(chunk)
                    yield chunk
            finally:
                _add_usage(prompt_tokens, completion_tokens)

        return _counting_gen()
    else:
        for attempt in range(2):
            try:
                out = _run(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=False,
                    stop=stop,
                    timeout_seconds=timeout_seconds,
                    _get_llm=_get_llm,
                    _llm_lock=_llm_lock,
                    model_override=model_override,
                    reasoning_budget=reasoning_budget,
                )
                break
            except Exception:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise
        text = ""
        if isinstance(out, dict):
            choices = out.get("choices") or [{}]
            msg = (choices[0] if choices else {}).get("message") or {}
            text = msg.get("content") or (choices[0] if choices else {}).get("text") or ""
        completion_tokens = _count_tokens(text)
        _add_usage(prompt_tokens, completion_tokens)
        return out

"""
Shared LLM completion gateway. Single point of access for local Llama or remote
OpenAI-compatible server. Serializes all completion calls so they never run concurrently.
"""
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_llm = None
_llm_lock = threading.Lock()
# Exposed so agent_loop can serialize full autonomous_run (one run at a time for LLM)
llm_serialize_lock = _llm_lock


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
        import runtime_safety
        from llama_cpp import Llama
        cfg = runtime_safety.load_config()
        model_filename = cfg.get("model_filename", "your-model.gguf")
        model_path = REPO_ROOT / "models" / model_filename

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
            "LLM loaded: %s | ctx=%d batch=%d gpu_layers=%s threads=%d/%d flash=%s",
            model_filename, n_ctx, n_batch, kwargs["n_gpu_layers"],
            n_threads, n_threads_batch, kwargs.get("flash_attn"),
        )
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


def run_completion(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list | None = None,
    timeout_seconds: int | None = None,
):
    """
    Run completion via local Llama or optional llama_server_url (OpenAI-compatible).
    If stream=True, yields token strings; else returns {"choices": [{"message": {"content": text}}]}.
    timeout_seconds: used for remote HTTP only; local Llama has no timeout in this call.
    """
    import runtime_safety
    cfg = runtime_safety.load_config()
    if stop is None:
        stop = get_stop_sequences()
    top_p = float(cfg.get("top_p", 0.95))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))
    top_k = max(1, int(cfg.get("top_k", 40)))
    url = (cfg.get("llama_server_url") or "").strip().rstrip("/")
    timeout = timeout_seconds if timeout_seconds is not None else 120

    if url:
        import urllib.request
        import json as _json
        model_name = cfg.get("remote_model_name") or "layla"
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            "stop": stop,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
            "top_k": top_k,
        }
        data = _json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url + "/v1/chat/completions",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            if stream:
                def gen():
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            for line in resp:
                                line = line.decode("utf-8").strip()
                                if not line or not line.startswith("data: ") or line == "data: [DONE]":
                                    continue
                                try:
                                    chunk = _json.loads(line[6:])
                                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                                    text = delta.get("content") or ""
                                    if text:
                                        yield text
                                except Exception as e:
                                    logger.debug("stream chunk parse: %s", e)
                    except Exception as e:
                        logger.exception("remote completion stream failed: %s", e)
                        yield ""
                return gen()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            try:
                out = _json.loads(raw)
            except _json.JSONDecodeError:
                out = {"choices": [{"message": {"content": "Remote server returned invalid JSON."}}]}
            return out
        except Exception as e:
            logger.exception("remote completion failed: %s", e)
            return {"choices": [{"message": {"content": f"Request failed: {e!s}. Is the model server running?"}}]}

    # Local: serialize with lock
    if stream:
        def gen():
            with _llm_lock:
                llm = _get_llm()
                for chunk in llm.create_completion(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    repeat_penalty=repeat_penalty,
                    top_k=top_k,
                    stream=True,
                    stop=stop,
                ):
                    t = (chunk.get("choices") or [{}])[0].get("text") or ""
                    if t:
                        yield t
        return gen()
    with _llm_lock:
        llm = _get_llm()
        out = llm.create_completion(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            stream=False,
            stop=stop,
        )
    if isinstance(out, dict):
        return out
    text = "".join((c.get("choices") or [{}])[0].get("text") or "" for c in out)
    return {"choices": [{"message": {"content": text}}]}

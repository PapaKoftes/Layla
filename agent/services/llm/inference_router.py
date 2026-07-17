"""
Inference router. Routes LLM completion requests to the appropriate backend:
- llama_cpp: local GGUF via llama-cpp-python
- openai_compatible: vLLM, LiteLLM, or any OpenAI-compatible HTTP API
- ollama: Ollama server (uses OpenAI-compatible /v1/chat/completions when available)
- cluster: offload to a paired Layla device on the LAN (Phase 9.3)

Config: inference_backend ("auto" | "llama_cpp" | "openai_compatible" | "ollama").
When "auto": no llama_server_url → llama_cpp; URL with port 11434 → ollama; else → openai_compatible.

Cluster offloading fallback chain (when cluster_offload_enabled=true):
  local GPU → local CPU → paired device (highest tier) → queue for later
"""
from __future__ import annotations

import json as _json
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKENDS = ("llama_cpp", "openai_compatible", "ollama", "litellm", "onnx")
_AUTO = "auto"


def ollama_http_base(cfg: dict) -> str:
    """Ollama API base URL: ollama_base_url wins, else llama_server_url (legacy)."""
    u = (cfg.get("ollama_base_url") or "").strip().rstrip("/")
    if u:
        return u
    return (cfg.get("llama_server_url") or "").strip().rstrip("/")


def _detect_backend(cfg: dict) -> str:
    """Detect backend from config. Returns one of _BACKENDS."""
    explicit = (cfg.get("inference_backend") or "").strip().lower()
    if explicit and explicit != _AUTO and explicit in _BACKENDS:
        return explicit
    # ONNX Runtime GenAI backend (BL-159): auto-selected when an ONNX model dir is set.
    if (cfg.get("onnx_model_path") or "").strip():
        return "onnx"
    if (cfg.get("ollama_base_url") or "").strip():
        return "ollama"
    url = (cfg.get("llama_server_url") or "").strip().rstrip("/")
    if not url:
        return "llama_cpp"
    # Ollama default port 11434
    if ":11434" in url or url.endswith(":11434"):
        return "ollama"
    if "ollama" in url.lower():
        return "ollama"
    return "openai_compatible"


def _get_backend(cfg: dict) -> str:
    """Return effective backend for current config."""
    return _detect_backend(cfg)


def effective_inference_backend(cfg: dict) -> str:
    """Public alias for the resolved backend: llama_cpp | openai_compatible | ollama | litellm."""
    return _get_backend(cfg)


def inference_backend_uses_local_gguf(cfg: dict) -> bool:
    """True when completions load GGUF in-process (subprocess workers would duplicate RAM)."""
    return _get_backend(cfg) == "llama_cpp"


def _openai_compatible_url(url: str) -> str:
    """OpenAI-compatible servers use /v1/chat/completions."""
    return url.rstrip("/")


def _openai_compatible_base_urls(cfg: dict) -> list[str]:
    u = (cfg.get("llama_server_url") or "").strip().rstrip("/")
    out: list[str] = []
    if u:
        out.append(u)
    for x in cfg.get("inference_fallback_urls") or []:
        sx = str(x).strip().rstrip("/")
        if sx and sx not in out:
            out.append(sx)
    return out


def run_completion_openai_compatible(
    cfg: dict,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    top_k: int,
    stop: list[str],
    stream: bool,
    timeout: int,
    _llm_lock: threading.Lock,
    model_name: str | None = None,
) -> dict | Generator[str, None, None]:
    """Run completion via OpenAI-compatible HTTP API (vLLM, LiteLLM, etc.)."""
    urls = _openai_compatible_base_urls(cfg)
    if not urls:
        return {"choices": [{"message": {"content": "No llama_server_url configured."}}]}
    model_name = model_name or cfg.get("remote_model_name") or "layla"
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
    primary_url = urls[0]

    def _one_request(url: str) -> urllib.request.Request:
        return urllib.request.Request(
            _openai_compatible_url(url) + "/v1/chat/completions",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

    try:
        if stream:
            req = _one_request(primary_url)

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
        last_exc: Exception | None = None
        for url in urls:
            req = _one_request(url)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                try:
                    return _json.loads(raw)
                except _json.JSONDecodeError:
                    return {"choices": [{"message": {"content": "Remote server returned invalid JSON."}}]}
            except urllib.error.HTTPError as e:
                last_exc = e
                if e.code >= 500 and url != urls[-1]:
                    logger.warning("openai_compatible %s HTTP %s; trying fallback", url, e.code)
                    continue
                break
            except Exception as e:
                last_exc = e
                if url != urls[-1]:
                    logger.warning("openai_compatible %s failed: %s; trying fallback", url, e)
                    continue
                break
        err = last_exc or RuntimeError("unknown")
        return {"choices": [{"message": {"content": f"Request failed: {err!s}. Is the model server running?"}}]}
    except Exception as e:
        logger.exception("remote completion failed: %s", e)
        return {"choices": [{"message": {"content": f"Request failed: {e!s}. Is the model server running?"}}]}


def run_completion_ollama(
    cfg: dict,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    top_k: int,
    stop: list[str],
    stream: bool,
    timeout: int,
    _llm_lock: threading.Lock,
    model_name: str | None = None,
) -> dict | Generator[str, None, None]:
    """Run completion via Ollama. Uses /v1/chat/completions (OpenAI-compatible)."""
    url = ollama_http_base(cfg)
    if not url:
        return {"choices": [{"message": {"content": "No ollama_base_url or llama_server_url configured."}}]}
    model_name = model_name or cfg.get("remote_model_name") or "llama3.1"
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
                    logger.exception("ollama completion stream failed: %s", e)
                    yield ""
            return gen()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            return {"choices": [{"message": {"content": "Ollama returned invalid JSON."}}]}
    except Exception as e:
        logger.exception("ollama completion failed: %s", e)
        return {"choices": [{"message": {"content": f"Ollama request failed: {e!s}. Is Ollama running?"}}]}


def run_completion_llama_cpp(
    cfg: dict,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    repeat_penalty: float,
    top_k: int,
    stop: list[str],
    stream: bool,
    _get_llm: Any,
    _llm_lock: threading.Lock,
    reasoning_budget: int | None = None,
) -> dict | Generator[str, None, None]:
    """Run completion via local llama-cpp-python. reasoning_budget for thinking models."""
    llm = _get_llm()
    extra_kw = {}
    if reasoning_budget is not None:
        extra_kw["reasoning_budget"] = reasoning_budget
    # If llama-cpp-python doesn't support reasoning_budget, drop it (TypeError)
    def _call_create_completion(stream_mode: bool = False, **kwargs):
        # Full KV cache reset: clear C-level cache + reset Python n_tokens counter.
        # Both are required — reset() alone leaves C cache stale; kv_cache_clear()
        # alone leaves n_tokens > 0, causing mismatched scoring on the next eval.
        try:
            llm._ctx.kv_cache_clear()
        except Exception:
            pass
        try:
            llm.reset()  # sets n_tokens = 0
        except Exception:
            pass
        kwargs.pop("reasoning_budget", None)  # not supported in 0.3.16
        return llm.create_completion(prompt, stream=stream_mode, **kwargs)
    if stream:
        def gen():
            yielded_any = False
            for _attempt in range(2):
                try:
                    with _llm_lock:
                        for chunk in _call_create_completion(
                            stream_mode=True,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            top_p=top_p,
                            repeat_penalty=repeat_penalty,
                            top_k=top_k,
                            stop=stop,
                            **extra_kw,
                        ):
                            t = (chunk.get("choices") or [{}])[0].get("text") or ""
                            if t:
                                yielded_any = True
                                yield t
                    return  # success
                except Exception as _se:
                    _emsg = str(_se)
                    # KV-cache corruption ("broadcast"/"shape"): only retry if we have NOT
                    # emitted anything yet. Retrying AFTER partial output re-runs the whole
                    # completion and re-yields every token, concatenating a second (mangled)
                    # copy onto the consumer's buffer — the duplicated/mangled-reply bug.
                    if ("broadcast" in _emsg or "shape" in _emsg) and _attempt == 0 and not yielded_any:
                        try:
                            from services.llm.llm_gateway import invalidate_llm_cache
                            invalidate_llm_cache()
                        except Exception:
                            pass
                        continue
                    raise
        return gen()
    import concurrent.futures as _cf
    timeout_s = int(cfg.get("llm_local_timeout_seconds", 180) or 180)
    with _llm_lock:
        # Do NOT use the executor as a `with` block: its __exit__ (like shutdown(wait=True)) JOINS the
        # worker, so a HUNG completion would block HERE despite the timeout below — while holding
        # _llm_lock — stalling every other LLM caller (audit #13). Detach a hung worker instead of joining.
        ex = _cf.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(
            _call_create_completion,
            False,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            top_k=top_k,
            stop=stop,
            **extra_kw,
        )
        try:
            out = fut.result(timeout=max(10, timeout_s))
        except _cf.TimeoutError:
            # Detach the hung worker without joining so the lock releases (an effective timeout). BUT the
            # detached worker is STILL running llm.create_completion() natively on the shared Llama
            # instance — so we MUST fence that instance before releasing _llm_lock, or the next caller
            # would run kv_cache_clear()/reset()/create_completion() on the SAME instance concurrently
            # (llama-cpp drops the GIL during C inference → native heap-corruption race). Fence by
            # dropping the module cache so the next caller builds a FRESH instance; the detached worker
            # keeps its own reference to the old one until it finishes, so no two callers ever touch the
            # same native context. (Cache-drop is Python-ref-only; it does not free the worker's C object.
            # already_locked=True: we already hold _llm_lock, and the earlier claim that invalidating here
            # corrupts state was wrong — this is exactly the fence the single-in-flight invariant needs.)
            ex.shutdown(wait=False, cancel_futures=True)
            try:
                from services.llm.llm_gateway import invalidate_llm_cache
                invalidate_llm_cache(already_locked=True)
            except Exception:
                pass
            return {"choices": [{"message": {"content": "Local LLM timed out. Please retry."}}]}
        except Exception as _fe:
            # The completion FAILED (worker finished), so it is safe to recover the KV cache here.
            ex.shutdown(wait=False, cancel_futures=True)
            if "broadcast" in str(_fe) or "shape" in str(_fe):
                try:
                    from services.llm.llm_gateway import invalidate_llm_cache
                    invalidate_llm_cache()
                except Exception:
                    pass
            raise
        else:
            ex.shutdown(wait=False)
    if isinstance(out, dict):
        return out
    text = "".join((c.get("choices") or [{}])[0].get("text") or "" for c in out)
    return {"choices": [{"message": {"content": text}}]}


def _resolve_model_override(override: str | None, cfg: dict) -> str | None:
    """Resolve model_override (task type or raw name) to model name for remote backends."""
    if not override or override == "default":
        return None
    if override in ("coding", "reasoning", "chat"):
        try:
            from services.llm.model_router import route_model
            return route_model(override)
        except Exception:
            return None
    return override  # raw model name


def apply_decoding_determinism(cfg: dict | None, temperature: float, top_p: float, top_k: int) -> "tuple[float, float, int]":
    """Release-gate determinism (BL-107 / REQ-22): when `deterministic_decoding_enabled` is set,
    force GREEDY decoding — temperature 0, top_k 1, top_p 1 — so eval / release-gate runs are
    reproducible (same prompt → same output). Greedy needs no seed plumbing (there's no sampling
    randomness to seed). Off by default, so normal chat keeps its configured sampling. Returns the
    (possibly overridden) (temperature, top_p, top_k)."""
    if cfg and cfg.get("deterministic_decoding_enabled", False):
        return 0.0, 1.0, 1
    return temperature, top_p, top_k


_onnx_cache: dict[str, Any] = {}


def _onnx_error(msg: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "error"}],
            "error": msg, "backend": "onnx"}


def _onnx_ret(d: dict, stream: bool):
    """Respect the stream contract. When stream=True the caller (llm_gateway._counting_gen) ITERATES
    the return value expecting a token generator — returning the raw dict made it iterate the dict and
    yield its KEYS ('choices', 'backend'/'error') as literal reply tokens ('choicesbackend'). So on the
    stream path wrap the assistant text in a single-chunk generator; otherwise return the dict as before."""
    if not stream:
        return d
    def _gen():
        try:
            yield (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        except Exception as _e:
            logger.debug("onnx stream chunk extract failed: %s", _e)
            yield ""
    return _gen()


def run_completion_onnx(
    cfg: dict, prompt: str, max_tokens: int, temperature: float,
    stop: list[str] | None, stream: bool, timeout: int,
) -> dict:
    """ONNX Runtime GenAI backend (BL-159) — local inference for ONNX-format models.

    Prebuilt-OSS: `onnxruntime-genai`. Degrades gracefully — a missing library or model
    dir returns an OpenAI-shaped error dict rather than raising, so callers/tests are safe.
    (Streaming falls back to a single block; the agent tolerates non-streamed completions.)
    """
    model_dir = (cfg.get("onnx_model_path") or "").strip()
    if not model_dir or not Path(model_dir).exists():
        return _onnx_ret(_onnx_error(f"onnx_model_path not found: {model_dir!r}"), stream)
    try:
        import onnxruntime_genai as og
    except Exception:
        return _onnx_ret(_onnx_error("onnxruntime-genai not installed (pip install onnxruntime-genai)"), stream)
    try:
        cached = _onnx_cache.get(model_dir)
        if cached is None:
            model = og.Model(model_dir)
            tokenizer = og.Tokenizer(model)
            cached = _onnx_cache[model_dir] = (model, tokenizer)
        model, tokenizer = cached
        input_ids = tokenizer.encode(prompt)
        params = og.GeneratorParams(model)
        params.set_search_options(
            # max_length is the TOTAL sequence budget — use the real ENCODED prompt-token count, not the
            # whitespace word count, or a multi-thousand-token system prompt undercounts and max_length
            # falls below the prompt length → zero generated tokens.
            max_length=int(max_tokens) + len(input_ids),
            temperature=float(max(0.0, temperature)),
            do_sample=temperature > 0.0,
        )
        params.input_ids = input_ids
        out_tokens = model.generate(params)
        text = tokenizer.decode(out_tokens[0]) if out_tokens else ""
        if text.startswith(prompt):
            text = text[len(prompt):]
        for s in stop or []:
            i = text.find(s)
            if i != -1:
                text = text[:i]
        return _onnx_ret({"choices": [{"message": {"role": "assistant", "content": text.strip()},
                                       "finish_reason": "stop"}], "backend": "onnx"}, stream)
    except Exception as e:  # noqa: BLE001
        logger.warning("onnx completion failed: %s", e)
        return _onnx_ret(_onnx_error(f"onnx inference error: {e}"), stream)


def run_completion(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list[str] | None = None,
    timeout_seconds: int | None = None,
    *,
    cfg_override: dict | None = None,
    _get_llm: Any = None,
    _llm_lock: threading.Lock | None = None,
    model_override: str | None = None,
    reasoning_budget: int | None = None,
) -> dict | Generator[str, None, None]:
    """
    Route completion to the configured backend.
    Returns dict or generator (when stream=True) in OpenAI-compatible format.
    model_override: "default"|"coding"|"reasoning"|"chat" or raw model name (remote only).
    """
    import runtime_safety
    cfg = cfg_override if isinstance(cfg_override, dict) else runtime_safety.load_config()
    if stop is None:
        from services.llm.llm_gateway import get_stop_sequences
        stop = get_stop_sequences()
    top_p = float(cfg.get("top_p", 0.95))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))
    top_k = max(1, int(cfg.get("top_k", 40)))
    # Release-gate/eval determinism (BL-107): force greedy decoding when enabled.
    temperature, top_p, top_k = apply_decoding_determinism(cfg, temperature, top_p, top_k)
    timeout = timeout_seconds if timeout_seconds is not None else 120
    backend = _get_backend(cfg)
    lock = _llm_lock
    if lock is None:
        from services.llm.llm_gateway import llm_serialize_lock
        lock = llm_serialize_lock
    get_llm = _get_llm
    if get_llm is None:
        from services.llm.llm_gateway import _get_llm
        get_llm = _get_llm

    # Resolve model override for remote backends (local llama_cpp uses single model)
    effective_model = None
    if backend != "llama_cpp" and cfg.get("model_override_enabled", True):
        effective_model = _resolve_model_override(model_override, cfg)
    if effective_model is None:
        effective_model = cfg.get("remote_model_name") or ("llama3.1" if backend == "ollama" else "layla")

    if backend == "litellm":
        try:
            from services.llm.litellm_gateway import run_completion_litellm
            return run_completion_litellm(
                cfg, prompt, max_tokens, temperature, stop, stream, timeout,
                model_name=effective_model,
            )
        except ImportError:
            logger.warning("inference_router: litellm backend selected but not installed; falling back to llama_cpp")
            # Fall through to llama_cpp
    if backend == "onnx":
        return run_completion_onnx(cfg, prompt, max_tokens, temperature, stop, stream, timeout)
    if backend == "ollama":
        return run_completion_ollama(
            cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
            stop, stream, timeout, lock,
            model_name=effective_model,
        )
    if backend == "openai_compatible":
        return run_completion_openai_compatible(
            cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
            stop, stream, timeout, lock,
            model_name=effective_model,
        )
    # llama_cpp
    return run_completion_llama_cpp(
        cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
        stop, stream, get_llm, lock,
        reasoning_budget=reasoning_budget,
    )


# ── Cluster offloading (Phase 9.3) ──────────────────────────────────────────

_TIER_RANK = {"cpu": 0, "gpu_low": 1, "gpu_mid": 2, "gpu_high": 3}


def _get_cluster_peers() -> list[dict]:
    """Return paired peers that allow inference offloading, sorted by tier (highest first)."""
    try:
        from services.cluster.mdns_discovery import get_discovered_peers
        peers = get_discovered_peers(max_age_s=60.0)
    except Exception:
        return []
    # Filter to paired devices with inference_offload permission
    try:
        from routers.pairing import _load_paired_devices
        paired = _load_paired_devices()
    except Exception:
        return []
    result = []
    for p in peers:
        iid = p.get("instance_id", "")
        dev = paired.get(iid)
        if dev and dev.get("permissions", {}).get("inference_offload", False):
            result.append(p)
    result.sort(key=lambda x: _TIER_RANK.get(x.get("hardware_tier", "cpu"), 0), reverse=True)
    return result


def run_completion_cluster(
    peer: dict,
    prompt: str,
    max_tokens: int,
    temperature: float,
    stream: bool,
    stop: list[str],
    timeout: int,
    model_name: str | None = None,
) -> dict | Generator[str, None, None]:
    """
    Route a completion request to a paired Layla peer's /agent endpoint via HTTP.
    Uses the peer's OpenAI-compatible /v1/chat/completions proxy.
    Falls back to the peer's own inference routing.
    """
    ip = peer.get("ip", "127.0.0.1")
    port = peer.get("port", 8000)
    peer_name = peer.get("name", ip)
    base_url = f"http://{ip}:{port}"

    # Try peer's OpenAI-compatible endpoint first
    body = _json.dumps({
        "model": model_name or "default",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
        "stop": stop,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    logger.info("cluster_offload: routing to peer %s @ %s:%s", peer_name, ip, port)

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
                                logger.debug("cluster stream chunk: %s", e)
                except Exception as e:
                    logger.warning("cluster_offload stream from %s failed: %s", peer_name, e)
                    yield ""
            return gen()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        try:
            result = _json.loads(raw)
            logger.info("cluster_offload: success from %s", peer_name)
            return result
        except _json.JSONDecodeError:
            return {"choices": [{"message": {"content": f"Cluster peer {peer_name} returned invalid JSON."}}]}
    except Exception as e:
        logger.warning("cluster_offload to %s failed: %s", peer_name, e)
        return {"choices": [{"message": {"content": f"Cluster offload to {peer_name} failed: {e!s}"}}]}


def run_completion_with_fallback(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list[str] | None = None,
    timeout_seconds: int | None = None,
    *,
    cfg_override: dict | None = None,
    _get_llm: Any = None,
    _llm_lock: threading.Lock | None = None,
    model_override: str | None = None,
    reasoning_budget: int | None = None,
) -> dict | Generator[str, None, None]:
    """
    Enhanced run_completion with cluster offloading fallback chain:
      1. Try local inference (GPU or CPU)
      2. If local fails and cluster_offload_enabled=true, try paired peers
      3. Return error if all fail

    Same signature as run_completion() — drop-in replacement.

    NO ENTRY POINT — VERIFIED 2026-07-17 (BL-350). Despite being a "drop-in replacement", nothing in the
    live tree calls this: every caller uses run_completion() directly, so the cluster fallback below is
    unreachable and `cluster_offload_enabled` has no UI and no effect on inference. Together with
    submit_task's zero callers (cluster_network.py) this is why LAN clustering moves zero work.

    Before wiring this in, note the architecture review's verdict (CUT): distributed inference is how you
    run a model that does not FIT locally, at ~2x worse decode — it is not a speedup for a model that
    does fit, and the 3B fits here with room.
    """
    import runtime_safety
    cfg = cfg_override if isinstance(cfg_override, dict) else runtime_safety.load_config()
    cluster_enabled = bool(cfg.get("cluster_offload_enabled", False))

    # Try local first
    try:
        result = run_completion(
            prompt, max_tokens, temperature, stream, stop, timeout_seconds,
            cfg_override=cfg, _get_llm=_get_llm, _llm_lock=_llm_lock,
            model_override=model_override, reasoning_budget=reasoning_budget,
        )
        # For non-streaming, check if the result indicates failure
        if not stream and isinstance(result, dict):
            text = ""
            try:
                text = result["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                pass
            if text and ("failed" in text.lower() or "timed out" in text.lower()):
                raise RuntimeError(f"Local inference signaled failure: {text[:100]}")
        return result
    except Exception as local_err:
        if not cluster_enabled:
            raise
        logger.info("Local inference failed (%s); trying cluster offload...", local_err)
        _saved_local_err = local_err

    # Cluster fallback
    peers = _get_cluster_peers()
    if not peers:
        logger.warning("No cluster peers available for offloading")
        return {"choices": [{"message": {"content":
            f"Local inference failed and no cluster peers available. Error: {_saved_local_err!s}"}}]}

    timeout = timeout_seconds if timeout_seconds is not None else 120
    effective_model = None
    if cfg.get("model_override_enabled", True):
        effective_model = _resolve_model_override(model_override, cfg)

    if stop is None:
        try:
            from services.llm.llm_gateway import get_stop_sequences
            stop = get_stop_sequences()
        except Exception:
            stop = []

    last_err: Exception | None = None
    for peer in peers:
        try:
            result = run_completion_cluster(
                peer, prompt, max_tokens, temperature, stream, stop, timeout,
                model_name=effective_model,
            )
            return result
        except Exception as e:
            last_err = e
            logger.warning("Cluster peer %s failed: %s; trying next...", peer.get("name"), e)

    return {"choices": [{"message": {"content":
        f"All inference targets failed. Local: {_saved_local_err!s}. Last cluster: {last_err!s}"}}]}


def get_cluster_status() -> dict:
    """Return cluster inference status for UI display."""
    import runtime_safety
    cfg = runtime_safety.load_config()
    enabled = bool(cfg.get("cluster_offload_enabled", False))
    local_tier = (cfg.get("hardware_tier") or "").strip()
    if not local_tier:
        try:
            from services.cluster.mdns_discovery import detect_hardware_tier
            local_tier = detect_hardware_tier()
        except Exception:
            local_tier = "cpu"
    peers = _get_cluster_peers() if enabled else []
    return {
        "cluster_enabled": enabled,
        "local_tier": local_tier,
        "local_backend": _get_backend(cfg),
        "available_peers": len(peers),
        "peers": [
            {
                "name": p.get("name"),
                "ip": p.get("ip"),
                "port": p.get("port"),
                "tier": p.get("hardware_tier"),
                "models": p.get("models", []),
            }
            for p in peers
        ],
        "fallback_chain": _build_fallback_chain_description(cfg, local_tier, peers),
    }


def _build_fallback_chain_description(cfg: dict, local_tier: str, peers: list) -> list[str]:
    """Build a human-readable fallback chain for diagnostics."""
    chain = []
    backend = _get_backend(cfg)
    if backend == "llama_cpp":
        chain.append(f"Local GGUF ({local_tier})")
    elif backend == "ollama":
        chain.append(f"Ollama ({local_tier})")
    elif backend == "openai_compatible":
        chain.append(f"OpenAI-compatible server ({local_tier})")
    for p in peers:
        chain.append(f"Peer: {p.get('name')} ({p.get('hardware_tier', 'cpu')}) @ {p.get('ip')}:{p.get('port')}")
    chain.append("Error: all targets exhausted")
    return chain

"""
Inference router. Routes LLM completion requests to the appropriate backend:
- llama_cpp: local GGUF via llama-cpp-python
- openai_compatible: vLLM, LiteLLM, or any OpenAI-compatible HTTP API
- ollama: Ollama server (uses OpenAI-compatible /v1/chat/completions when available)

Config: inference_backend ("auto" | "llama_cpp" | "openai_compatible" | "ollama").
When "auto": no llama_server_url → llama_cpp; URL with port 11434 → ollama; else → openai_compatible.
"""
from __future__ import annotations

import json as _json
import logging
import threading
import urllib.request
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKENDS = ("llama_cpp", "openai_compatible", "ollama")
_AUTO = "auto"


def _detect_backend(cfg: dict) -> str:
    """Detect backend from config. Returns one of _BACKENDS."""
    explicit = (cfg.get("inference_backend") or "").strip().lower()
    if explicit and explicit != _AUTO and explicit in _BACKENDS:
        return explicit
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


def _ollama_base_url(url: str) -> str:
    """Ollama uses /v1/chat/completions (OpenAI-compatible) since 0.3.x."""
    return url.rstrip("/")


def _openai_compatible_url(url: str) -> str:
    """OpenAI-compatible servers use /v1/chat/completions."""
    return url.rstrip("/")


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
) -> dict | Generator[str, None, None]:
    """Run completion via OpenAI-compatible HTTP API (vLLM, LiteLLM, etc.)."""
    url = (cfg.get("llama_server_url") or "").strip().rstrip("/")
    if not url:
        return {"choices": [{"message": {"content": "No llama_server_url configured."}}]}
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
        _openai_compatible_url(url) + "/v1/chat/completions",
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
            return _json.loads(raw)
        except _json.JSONDecodeError:
            return {"choices": [{"message": {"content": "Remote server returned invalid JSON."}}]}
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
) -> dict | Generator[str, None, None]:
    """Run completion via Ollama. Uses /v1/chat/completions (OpenAI-compatible)."""
    url = (cfg.get("llama_server_url") or "").strip().rstrip("/")
    if not url:
        return {"choices": [{"message": {"content": "No llama_server_url configured."}}]}
    model_name = cfg.get("remote_model_name") or "llama3.1"
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
        _ollama_base_url(url) + "/v1/chat/completions",
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
) -> dict | Generator[str, None, None]:
    """Run completion via local llama-cpp-python."""
    llm = _get_llm()
    if stream:
        def gen():
            with _llm_lock:
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


def run_completion(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list[str] | None = None,
    timeout_seconds: int | None = None,
    *,
    _get_llm: Any = None,
    _llm_lock: threading.Lock | None = None,
) -> dict | Generator[str, None, None]:
    """
    Route completion to the configured backend.
    Returns dict or generator (when stream=True) in OpenAI-compatible format.
    """
    import runtime_safety
    cfg = runtime_safety.load_config()
    if stop is None:
        from services.llm_gateway import get_stop_sequences
        stop = get_stop_sequences()
    top_p = float(cfg.get("top_p", 0.95))
    repeat_penalty = float(cfg.get("repeat_penalty", 1.1))
    top_k = max(1, int(cfg.get("top_k", 40)))
    timeout = timeout_seconds if timeout_seconds is not None else 120
    backend = _get_backend(cfg)
    lock = _llm_lock
    if lock is None:
        from services.llm_gateway import llm_serialize_lock
        lock = llm_serialize_lock
    get_llm = _get_llm
    if get_llm is None:
        from services.llm_gateway import _get_llm
        get_llm = _get_llm

    if backend == "ollama":
        return run_completion_ollama(
            cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
            stop, stream, timeout, lock,
        )
    if backend == "openai_compatible":
        return run_completion_openai_compatible(
            cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
            stop, stream, timeout, lock,
        )
    # llama_cpp
    return run_completion_llama_cpp(
        cfg, prompt, max_tokens, temperature, top_p, repeat_penalty, top_k,
        stop, stream, get_llm, lock,
    )

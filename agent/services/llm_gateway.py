"""
Shared LLM completion gateway. Single point of access for local Llama or remote
OpenAI-compatible server. Serializes all completion calls via asyncio queue.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_llm = None  # legacy: first loaded instance (health/UI)
_llm_by_path: dict[str, Any] = {}  # resolved model path -> Llama (task-based routing)
# RLock: kept for legacy sync callers (e.g. prewarm_llm) and _get_llm internal locking.
_llm_lock = threading.RLock()
# llm_serialize_lock is kept as a shim for legacy sync callers (agent_loop imports it).
# All async paths use LLMRequestQueue instead.
llm_serialize_lock = _llm_lock

# When llm_serialize_per_workspace is true: agent runs hold per-workspace RLocks; local llama_cpp
# generation uses this global Lock so two workspaces never call create_completion concurrently.
llm_generation_lock = threading.Lock()

_workspace_agent_locks: dict[str, threading.RLock] = {}
_workspace_agent_locks_guard = threading.Lock()


def get_agent_serialize_lock(workspace_key: str) -> threading.RLock:
    """RLock for one autonomous_run flight; key should be resolved workspace path or '__default__'."""
    key = (workspace_key or "").strip() or "__default__"
    with _workspace_agent_locks_guard:
        lock = _workspace_agent_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _workspace_agent_locks[key] = lock
        return lock


def _resolve_workspace_lock_key(workspace_root: str) -> str:
    raw = (workspace_root or "").strip()
    if not raw:
        return "__default__"
    try:
        return str(Path(raw).expanduser().resolve())
    except Exception:
        return raw[:512]


# Priority constants for queue-based submission (async paths)
PRIORITY_CHAT = 0
PRIORITY_BACKGROUND = 1


class LLMTimeoutError(Exception):
    """Raised when an LLM request times out."""


@dataclasses.dataclass
class _LLMRequest:
    prompt: str
    params: dict
    future: asyncio.Future
    cancel_event: asyncio.Event | None
    priority: int


class LLMRequestQueue:
    """
    Asyncio-based request queue for serialised LLM access.
    Replaces the threading.RLock bottleneck for async paths.
    """

    def __init__(self, maxsize: int = 20) -> None:
        self._queue: asyncio.Queue[_LLMRequest] = asyncio.Queue(maxsize=maxsize)
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start background worker. Call from FastAPI lifespan startup."""
        loop = asyncio.get_event_loop()
        self._worker_task = loop.create_task(self._worker(), name="llm-queue-worker")

    async def stop(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _worker(self) -> None:
        """Single worker that processes requests one at a time."""
        while True:
            try:
                req: _LLMRequest = await self._queue.get()
                try:
                    if req.cancel_event and req.cancel_event.is_set():
                        if not req.future.done():
                            req.future.cancel()
                        continue
                    loop = asyncio.get_event_loop()
                    try:
                        result = await loop.run_in_executor(
                            None,
                            lambda r=req: run_completion(
                                r.prompt,
                                **r.params,
                            ),
                        )
                        if not req.future.done():
                            req.future.set_result(result)
                    except Exception as exc:
                        if not req.future.done():
                            req.future.set_exception(exc)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("LLMRequestQueue worker error: %s", e)

    async def submit(
        self,
        prompt: str,
        params: dict | None = None,
        priority: int = PRIORITY_CHAT,
        cancel_event: asyncio.Event | None = None,
    ) -> Any:
        """Submit a completion request and await the result."""
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        req = _LLMRequest(
            prompt=prompt,
            params=params or {},
            future=future,
            cancel_event=cancel_event,
            priority=priority,
        )
        await self._queue.put(req)
        return await future


# Global queue instance — started in FastAPI lifespan
llm_request_queue: LLMRequestQueue = LLMRequestQueue()


async def run_completion_async(
    prompt: str,
    params: dict | None = None,
    cancel_event: asyncio.Event | None = None,
    priority: int = PRIORITY_CHAT,
) -> Any:
    """
    Submit a completion to the async queue and await the result.
    Raises asyncio.CancelledError if cancel_event is set before/during processing.
    """
    import runtime_safety
    p = params or {}
    timeout_sec = runtime_safety.load_config().get("llm_timeout_seconds", 120)
    if cancel_event and cancel_event.is_set():
        raise asyncio.CancelledError("Request cancelled before submission")
    try:
        return await asyncio.wait_for(
            llm_request_queue.submit(prompt, p, priority=priority, cancel_event=cancel_event),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        raise LLMTimeoutError(f"LLM request timed out after {timeout_sec}s")


# Per-request model override: "default" | "coding" | "reasoning" | "chat" (for remote backends)
_model_override_var: ContextVar[str | None] = ContextVar("model_override", default=None)
# Per-request reasoning: "high" = use reasoning_budget from config for thinking models
_reasoning_effort_var: ContextVar[str | None] = ContextVar("reasoning_effort", default=None)
# Current completion prompt snippet: enables routing when model_override is unset (single source of truth in _effective_model_filename)
_routing_prompt_var: ContextVar[str | None] = ContextVar("routing_prompt", default=None)


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


def _prompt_is_router_internal(prompt: str) -> bool:
    """True for decision/critic/summarizer prompts — do not re-classify task from these."""
    if not (prompt or "").strip():
        return True
    markers = (
        "Choose one: run one tool",
        "Output exactly one JSON line",
        "You are a response quality critic",
        "Summarize this conversation excerpt",
        "Score this response 1-10",
    )
    return any(m in prompt for m in markers)


# Token usage tracking (session totals since server start)
_token_usage_lock = threading.Lock()
_token_usage = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "request_count": 0,
    "tool_calls": 0,
    "session_start": time.time(),
}


def model_loaded_status() -> dict:
    """Return model status for /health. If path invalid, includes error message."""
    try:
        import runtime_safety
        from services.dependency_recovery import missing_gguf_recovery

        cfg = runtime_safety.load_config()
        url = (cfg.get("llama_server_url") or "").strip()
        if url:
            return {"remote": True, "error": None}
        try:
            import llama_cpp  # noqa: F401
        except ImportError as e:
            from services.dependency_recovery import llama_cpp_import_recovery, merge_recovery_message

            rec = llama_cpp_import_recovery(str(e))
            return {"error": merge_recovery_message(rec), "recovery": rec}
        model_filename = (cfg.get("model_filename") or "").strip() or "your-model.gguf"
        if not model_filename or model_filename == "your-model.gguf":
            md_raw = cfg.get("models_dir")
            md = Path(md_raw).expanduser().resolve() if md_raw else REPO_ROOT / "models"
            rec = missing_gguf_recovery(str(model_filename), md)
            return {"error": "Model not loaded. Set model_filename in runtime_config.json", "recovery": rec}
        model_path = runtime_safety.resolve_model_path(cfg)
        if not model_path.exists():
            md = model_path.parent
            rec = missing_gguf_recovery(str(model_filename), md, resolved_path=model_path)
            return {
                "error": f"GGUF not found at {model_path}",
                "recovery": rec,
            }
        if _llm is not None or _llm_by_path:
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


def _effective_model_filename(cfg: dict) -> str:
    """
    Resolve GGUF basename: ContextVar override, else classify from routing prompt, else default.
    Uses model_router.select_model (capability + benchmark aware) when a task type applies.
    """
    override = get_model_override()
    # Optional dual-model routing: chat model for reactive turns, agent model for heavy work.
    # Falls back to existing routing when unset or unavailable.
    try:
        from services.resource_manager import should_use_dual_models

        if should_use_dual_models():
            from services.model_router import resolve_dual_model_basenames

            chat_fn, agent_fn = resolve_dual_model_basenames(cfg)
            if override == "chat" and chat_fn:
                return chat_fn
            if override in ("coding", "reasoning") and agent_fn:
                return agent_fn
    except Exception:
        pass
    rp = (_routing_prompt_var.get(None) or "").strip()
    # Hard override: allow internal callers to route decisions to a dedicated JSON/structured model.
    if override == "decision":
        dm = (cfg.get("decision_model") or "").strip()
        if dm:
            return dm
        # If decision model isn't configured, fall through to normal routing.

    task: str | None = override if override in ("coding", "reasoning", "chat") else None
    if task is None and rp and not _prompt_is_router_internal(rp):
        if cfg.get("tool_routing_enabled", True):
            try:
                from services.model_router import classify_task_for_routing, is_routing_enabled

                if is_routing_enabled():
                    c = classify_task_for_routing(rp[:4000], "", cfg)
                    if c in ("coding", "reasoning", "chat"):
                        task = c
            except Exception:
                pass
    if task in ("coding", "reasoning", "chat"):
        try:
            from services.hardware_detect import detect_hardware
            from services.model_router import route_model, select_model

            hw = detect_hardware()
            lat = 0
            try:
                lat = int(cfg.get("latency_budget_ms") or 0)
            except (TypeError, ValueError):
                lat = 0
            picked = select_model(task, len(rp), hw, lat)
            if picked and str(picked).strip():
                return str(picked).strip()
            alt = route_model(task)
            if alt and str(alt).strip():
                return str(alt).strip()
        except Exception as e:
            logger.debug("task model route failed: %s", e)
    return (cfg.get("model_filename") or "your-model.gguf").strip()


def _get_llm():
    global _llm
    try:
        from llama_cpp import Llama
    except ImportError as e:
        import runtime_safety
        from services.dependency_recovery import ensure_feature, llama_cpp_import_recovery, merge_recovery_message

        ok, rec = ensure_feature("llama_cpp", runtime_safety.load_config())
        if ok:
            from llama_cpp import Llama
        else:
            r = rec or llama_cpp_import_recovery(str(e))
            msg = merge_recovery_message(r)
            logger.error("llm_gateway: %s", msg)
            raise RuntimeError(msg) from e

    import runtime_safety
    cfg = runtime_safety.load_config()
    model_filename = _effective_model_filename(cfg)
    cfg_eff = dict(cfg)
    cfg_eff["model_filename"] = model_filename
    model_path = runtime_safety.resolve_model_path(cfg_eff)
    if not model_path.exists():
        wanted = model_filename
        chain = cfg.get("model_fallback_chain") or []
        if not isinstance(chain, list):
            chain = []
        candidates: list[str] = []
        # Preserve existing behavior: always try default model_filename.
        default_fn = (cfg.get("model_filename") or "your-model.gguf").strip()
        for cand in list(chain) + [default_fn]:
            sc = str(cand).strip()
            if sc and sc not in candidates:
                candidates.append(sc)
        picked = None
        for fallback_fn in candidates:
            probe = dict(cfg)
            probe["model_filename"] = fallback_fn
            p = runtime_safety.resolve_model_path(probe)
            if p.exists():
                picked = (fallback_fn, p)
                break
        if picked is None:
            logger.warning(
                "llm_gateway: routed model missing (%s at %s) and no fallback candidates exist; keeping default path",
                wanted,
                model_path,
            )
        else:
            model_filename, model_path = picked
            logger.warning(
                "llm_gateway: routed model missing (%s); falling back to %s at %s",
                wanted,
                model_filename,
                model_path,
            )
            cfg_eff = dict(cfg)
            cfg_eff["model_filename"] = model_filename
    try:
        path_key = str(model_path.resolve())
    except Exception:
        path_key = str(model_path)

    # Fast path without lock: autonomous_run holds llm_serialize_lock (same as _llm_lock);
    # re-entering would deadlock during reflection / nested completion.
    cached_fast = _llm_by_path.get(path_key)
    if cached_fast is not None:
        return cached_fast

    with _llm_lock:
        cached = _llm_by_path.get(path_key)
        if cached is not None:
            return cached

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

        # Speculative decoding (prompt lookup) can significantly increase throughput.
        # Safe on older llama-cpp-python: unsupported kwargs are stripped by the TypeError fallback below.
        if cfg.get("speculative_decoding_enabled", True):
            try:
                from llama_cpp.llama_speculative import LlamaPromptLookupDecoding

                n_pred = int(cfg.get("speculative_num_pred_tokens", 10))
                kwargs["draft_model"] = LlamaPromptLookupDecoding(num_pred_tokens=max(1, n_pred))
            except Exception as e:
                logger.debug("speculative decoding unavailable: %s", e)

        # Rope scaling for extended contexts
        if cfg.get("rope_freq_base"):
            kwargs["rope_freq_base"] = float(cfg["rope_freq_base"])
        if cfg.get("rope_freq_scale"):
            kwargs["rope_freq_scale"] = float(cfg["rope_freq_scale"])

        try:
            inst = Llama(**kwargs)
        except TypeError:
            # Older llama-cpp-python may not support all kwargs; retry with safe subset
            safe_keys = {"model_path", "n_ctx", "n_gpu_layers", "n_batch",
                         "n_threads", "n_threads_batch", "use_mlock", "use_mmap", "verbose"}
            inst = Llama(**{k: v for k, v in kwargs.items() if k in safe_keys})

        # Guard: llama-cpp-python <=0.3.16 bug — when draft_model is set, _logits_all is
        # forced True at runtime but scores is still allocated (n_batch, vocab) instead of
        # (n_ctx, vocab). Any prompt > n_batch tokens causes a broadcast ValueError.
        # Detect and fix: resize scores to (n_ctx, vocab) so eval() writes land correctly.
        try:
            import numpy as np
            if getattr(inst, "_logits_all", False) and inst.scores.shape[0] < n_ctx:
                logger.warning(
                    "llm scores array mismatch (shape=%s, n_ctx=%d) — resizing. "
                    "This is a llama-cpp-python speculative-decoding bug; "
                    "set speculative_decoding_enabled=false to avoid it.",
                    inst.scores.shape, n_ctx,
                )
                inst.scores = np.ndarray((n_ctx, inst._n_vocab), dtype=np.single)
        except Exception as _e:
            logger.debug("scores resize check failed: %s", _e)

        _llm_by_path[path_key] = inst
        if _llm is None:
            _llm = inst

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
        return inst


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


def invalidate_llm_cache() -> None:
    """Drop cached llama-cpp instances so next call reloads GGUF."""
    global _llm, _llm_by_path
    try:
        with _llm_lock:
            _llm = None
            _llm_by_path = {}
    except Exception:
        _llm = None
        _llm_by_path = {}


def get_stop_sequences():
    """Stop sequences so the model does not continue into the next turn."""
    import runtime_safety
    cfg = runtime_safety.load_config()
    stop = cfg.get("stop_sequences")
    if isinstance(stop, list) and stop:
        return [str(s) for s in stop if s]
    # Stop the model from echoing system-prompt section headers back into replies.
    # SmolLM2 and similar small models tend to repeat ## CONTEXT / ## TASK verbatim.
    return ["\nUser:", " User:", "\n## ", "## CONTEXT", "## TASK", "## SCRATCHPAD", "## REPO", "<|endoftext|>", "<|im_end|>"]


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


def record_tool_call() -> None:
    """Increment session tool-call counter (exposed via /health token_usage)."""
    with _token_usage_lock:
        _token_usage["tool_calls"] = int(_token_usage.get("tool_calls", 0)) + 1


def get_token_usage() -> dict:
    """Return session token usage for /usage or /health."""
    with _token_usage_lock:
        elapsed = max(0.001, time.time() - float(_token_usage["session_start"]))
        tout = int(_token_usage["completion_tokens"])
        return {
            "prompt_tokens": _token_usage["prompt_tokens"],
            "completion_tokens": _token_usage["completion_tokens"],
            "total_tokens": _token_usage["total_tokens"],
            "request_count": _token_usage["request_count"],
            "tool_calls": int(_token_usage.get("tool_calls", 0)),
            "session_start": _token_usage["session_start"],
            "elapsed_seconds": round(elapsed),
            "tokens_per_second": round(tout / elapsed, 2),
        }


def run_completion(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stream: bool = False,
    stop: list | None = None,
    timeout_seconds: int | None = None,
    _retry_on_transient: bool = True,
):
    """
    Run completion via inference_router (llama_cpp, openai_compatible, or ollama).
    If stream=True, yields token strings; else returns {"choices": [{"message": {"content": text}}]}.
    timeout_seconds: used for remote HTTP only; local Llama has no timeout in this call.
    Includes exponential backoff retry (max 2 retries) for transient errors.
    Token usage is tracked for /usage endpoint.
    Sets routing prompt ContextVar so _effective_model_filename always has authority
    (override or classify-from-prompt + select_model); internal prompts are excluded.
    """
    import runtime_safety
    from services.inference_router import run_completion as _run

    routing_tok = _routing_prompt_var.set((prompt or "")[:16000])
    prompt_tokens = _count_tokens(prompt)
    model_override = get_model_override()
    routing_tag = str(model_override or "none")
    cache_model_name = ""
    reasoning_effort = get_reasoning_effort()
    reasoning_budget = None
    cfg: dict = {}
    try:
        cfg = runtime_safety.load_config()
        try:
            cache_model_name = str(_effective_model_filename(cfg) or cfg.get("model_filename") or "")
        except Exception:
            cache_model_name = str(cfg.get("model_filename") or "")
        if reasoning_effort == "high":
            budget = cfg.get("reasoning_budget", -1)
            if budget != 0:
                reasoning_budget = int(budget) if budget else -1
    except Exception:
        pass

    infer_lock = llm_generation_lock if cfg.get("llm_serialize_per_workspace") else llm_serialize_lock

    try:
        if (
            not stream
            and cfg.get("completion_cache_enabled")
            and len(prompt or "") < 12000
        ):
            try:
                from services.completion_cache import get_cached

                hit = get_cached(
                    prompt or "",
                    routing_tag,
                    cache_model_name or "unknown",
                    float(temperature),
                    int(max_tokens),
                )
                if hit is not None:
                    choices = hit.get("choices") or [{}]
                    msg = (choices[0] if choices else {}).get("message") or {}
                    text = msg.get("content") or (choices[0] if choices else {}).get("text") or ""
                    _routing_prompt_var.reset(routing_tok)
                    _add_usage(prompt_tokens, _count_tokens(text))
                    return hit
            except Exception as e:
                logger.debug("completion cache get: %s", e)

        if stream:

            def _counting_gen():
                completion_tokens = 0
                try:
                    from services.otel_export import maybe_span

                    with maybe_span(cfg, "llm_completion", stream="true"):
                        inner = _run(
                            prompt=prompt,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stream=True,
                            stop=stop,
                            timeout_seconds=timeout_seconds,
                            cfg_override=cfg,
                            _get_llm=_get_llm,
                            _llm_lock=infer_lock,
                            model_override=model_override,
                            reasoning_budget=reasoning_budget,
                        )
                        try:
                            for chunk in inner:
                                completion_tokens += _count_tokens(chunk)
                                yield chunk
                        finally:
                            _add_usage(prompt_tokens, completion_tokens)
                finally:
                    _routing_prompt_var.reset(routing_tok)

            return _counting_gen()

        # Determine effective timeout from config when not explicitly provided
        import runtime_safety as _rs_retry
        _cfg_retry = _rs_retry.load_config()
        effective_timeout = timeout_seconds if timeout_seconds is not None else _cfg_retry.get("llm_timeout_seconds", 120)
        _MAX_RETRIES = 2 if _retry_on_transient else 0
        out = None
        from services.otel_export import maybe_span

        for attempt in range(_MAX_RETRIES + 1):
            try:
                with maybe_span(cfg, "llm_completion", stream="false"):
                    out = _run(
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=False,
                        stop=stop,
                        timeout_seconds=effective_timeout,
                        cfg_override=cfg,
                        _get_llm=_get_llm,
                        _llm_lock=infer_lock,
                        model_override=model_override,
                        reasoning_budget=reasoning_budget,
                    )
                break
            except LLMTimeoutError:
                raise
            except Exception as _retry_exc:
                if attempt < _MAX_RETRIES:
                    backoff = 2 ** attempt  # 1s, 2s
                    logger.warning("LLM transient error (attempt %d/%d), retrying in %ds: %s", attempt + 1, _MAX_RETRIES + 1, backoff, _retry_exc)
                    time.sleep(backoff)
                    continue
                raise
        text = ""
        if isinstance(out, dict):
            choices = out.get("choices") or [{}]
            msg = (choices[0] if choices else {}).get("message") or {}
            text = msg.get("content") or (choices[0] if choices else {}).get("text") or ""
        completion_tokens = _count_tokens(text)
        _add_usage(prompt_tokens, completion_tokens)
        if cfg.get("completion_cache_enabled") and isinstance(out, dict):
            try:
                from services.completion_cache import set_cached

                set_cached(
                    prompt or "",
                    routing_tag,
                    cache_model_name or "unknown",
                    float(temperature),
                    int(max_tokens),
                    out,
                )
            except Exception as e:
                logger.debug("completion cache set: %s", e)
        return out
    finally:
        if not stream:
            try:
                _routing_prompt_var.reset(routing_tok)
            except (ValueError, LookupError):
                pass


def run_completion_stream(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.2,
    stop: list | None = None,
    timeout_seconds: int | None = None,
):
    """Explicit streaming helper for callers that always want token iterator semantics."""
    return run_completion(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        stop=stop,
        timeout_seconds=timeout_seconds,
    )

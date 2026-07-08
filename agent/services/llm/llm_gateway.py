"""
Shared LLM completion gateway. Single point of access for local Llama or remote
OpenAI-compatible server. Serializes all completion calls via a single lock
(`llm_serialize_lock`); async paths run generation in an executor under that lock.
"""
from __future__ import annotations

import asyncio
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


def model_is_loaded() -> bool:
    """True if a model is actually RESIDENT in this process (not merely present on disk).

    model_loaded_status() reports OK whenever the GGUF exists, so it can't tell a warm
    process from a cold one. This lets the chat stream show a truthful "Loading model…"
    state on the first cold request instead of an ambiguous "thinking" spinner.
    """
    return _llm is not None or bool(_llm_by_path)

_DEFAULT_MAX_RESIDENT_MODELS = 2  # cap on concurrently-loaded GGUF models (memory bound, F9)


def _free_llm_instance(inst) -> None:
    """Best-effort release of a loaded model's native resources before eviction."""
    try:
        close = getattr(inst, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _evict_models_if_needed(max_resident: int) -> list[str]:
    """Bound _llm_by_path so multi-model routing can't OOM the single process (F9).

    Evicts the OLDEST non-primary model(s) until there is room for one more, then
    frees them. The primary instance (``_llm``) is never evicted. Caller holds the
    lock. Returns the evicted path keys.
    """
    global _llm
    try:
        cap = max(1, int(max_resident))
    except (TypeError, ValueError):
        cap = _DEFAULT_MAX_RESIDENT_MODELS
    evicted: list[str] = []
    while len(_llm_by_path) >= cap:
        victim_key = None
        for k, inst in _llm_by_path.items():
            if inst is not _llm:
                victim_key = k
                break
        if victim_key is None:
            break  # only the primary remains — never evict it
        old = _llm_by_path.pop(victim_key)
        _free_llm_instance(old)
        evicted.append(victim_key)
    if evicted:
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        logger.info("llm_gateway: evicted %d resident model(s) to stay within max_resident_models=%s", len(evicted), max_resident)
    return evicted

# RLock: kept for legacy sync callers (e.g. prewarm_llm) and _get_llm internal locking.
_llm_lock = threading.RLock()
# llm_serialize_lock is THE single serialization point for LLM access: sync callers take this
# RLock directly; async paths run generation via run_in_executor under the same lock (see
# inference_router). (A never-used asyncio LLMRequestQueue was removed — nothing submitted to it;
# the single-lock model below is the whole concurrency story.)
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


# Task-priority constants (chat ahead of background) — used by the agent task scheduler and
# resource_manager to order queued autonomous runs, NOT for LLM-call serialization.
PRIORITY_CHAT = 0
PRIORITY_BACKGROUND = 1


class LLMTimeoutError(Exception):
    """Raised when an LLM request times out."""


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
    # Cancel any pending WHISPER idle unload — an active request means model is needed
    try:
        cancel_idle_unload()
    except Exception:
        pass
    import runtime_safety
    p = params or {}
    timeout_sec = runtime_safety.load_config().get("llm_timeout_seconds", 120)
    if cancel_event and cancel_event.is_set():
        raise asyncio.CancelledError("Request cancelled before submission")
    # Run the sync completion off the event loop. (Historically this referenced an
    # `llm_request_queue` that was never wired — an undefined-name latent bug; delegating
    # to run_completion via a thread is the correct, working async wrapper.)
    def _run() -> Any:
        return run_completion(
            prompt,
            max_tokens=int(p.get("max_tokens", 256) or 256),
            temperature=float(p.get("temperature", 0.2) or 0.2),
            stop=p.get("stop"),
            stream=False,
        )
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_sec)
    except asyncio.TimeoutError:
        raise LLMTimeoutError(f"LLM request timed out after {timeout_sec}s")


# Per-request model override: "default" | "coding" | "reasoning" | "chat" (for remote backends)
_model_override_var: ContextVar[str | None] = ContextVar("model_override", default=None)
# Per-request reasoning: "high" = use reasoning_budget from config for thinking models
_reasoning_effort_var: ContextVar[str | None] = ContextVar("reasoning_effort", default=None)
# Current completion prompt snippet: enables routing when model_override is unset (single source of truth in _effective_model_filename)
_routing_prompt_var: ContextVar[str | None] = ContextVar("routing_prompt", default=None)
# Active aspect id for this request: lets a per-aspect model override (aspect_model_overrides) win in _effective_model_filename.
_active_aspect_var: ContextVar[str | None] = ContextVar("active_aspect", default=None)


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


def set_active_aspect(aspect_id: str | None):
    """Set the active aspect for this request; returns the token for leak-safe reset."""
    return _active_aspect_var.set((aspect_id or "").strip() or None)


def reset_active_aspect(token) -> None:
    """Reset the active-aspect ContextVar using the token from set_active_aspect."""
    try:
        _active_aspect_var.reset(token)
    except Exception:
        pass


def get_active_aspect() -> str | None:
    """Get the active aspect id for the current request."""
    return _active_aspect_var.get(None)


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
        from services.infrastructure.dependency_recovery import missing_gguf_recovery

        cfg = runtime_safety.load_config()
        url = (cfg.get("llama_server_url") or "").strip()
        if url:
            return {"remote": True, "error": None}
        try:
            import llama_cpp  # noqa: F401
        except ImportError as e:
            from services.infrastructure.dependency_recovery import llama_cpp_import_recovery, merge_recovery_message

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
        from services.infrastructure.resource_manager import should_use_dual_models

        if should_use_dual_models():
            from services.llm.model_router import resolve_dual_model_basenames

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

    # Per-aspect model override: if the active aspect pins a model (aspect_model_overrides),
    # it wins over task-based routing. No-op when unset (the default for everyone).
    try:
        _aid = _active_aspect_var.get(None)
        if _aid:
            from services.llm.model_router import _resolve_aspect_model

            _asp_model, _ = _resolve_aspect_model(_aid)
            if _asp_model and str(_asp_model).strip():
                return str(_asp_model).strip()
    except Exception as _asp_e:
        logger.debug("aspect model override resolve failed: %s", _asp_e)

    task: str | None = override if override in ("coding", "reasoning", "chat") else None
    if task is None and rp and not _prompt_is_router_internal(rp):
        if cfg.get("tool_routing_enabled", True):
            try:
                from services.llm.model_router import classify_task_for_routing, is_routing_enabled

                if is_routing_enabled():
                    c = classify_task_for_routing(rp[:4000], "", cfg)
                    if c in ("coding", "reasoning", "chat"):
                        task = c
            except Exception:
                pass
    if task in ("coding", "reasoning", "chat"):
        try:
            from services.infrastructure.hardware_detect import detect_hardware
            from services.llm.model_router import route_model, select_model

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


def _apply_prompt_cache(inst, cache_mb: int) -> bool:
    """Attach a bounded LlamaRAMCache so the shared prompt prefix isn't re-prefilled (BL-108)."""
    try:
        from llama_cpp import LlamaRAMCache
    except Exception:
        try:
            from llama_cpp.llama_cache import LlamaRAMCache  # older layout
        except Exception:
            logger.debug("kv prompt cache: LlamaRAMCache unavailable")
            return False
    if not hasattr(inst, "set_cache"):
        return False
    capacity = max(1, int(cache_mb)) * 1024 * 1024
    try:
        inst.set_cache(LlamaRAMCache(capacity_bytes=capacity))
    except TypeError:
        inst.set_cache(LlamaRAMCache(capacity))
    logger.info("KV prompt-prefix cache enabled (%d MB)", cache_mb)
    return True


def _get_llm():
    global _llm
    try:
        from llama_cpp import Llama
    except ImportError as e:
        import runtime_safety
        from services.infrastructure.dependency_recovery import (
            ensure_feature,
            llama_cpp_import_recovery,
            merge_recovery_message,
        )

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

        # Apply hardware-probe defaults for any config key not explicitly set.
        # This makes Layla auto-configure optimally on any hardware without manual tuning.
        try:
            from services.infrastructure.hardware_detect import apply_to_config
            cfg = apply_to_config(cfg)
        except Exception as _hp_err:
            logger.debug("hardware_probe apply_to_config skipped: %s", _hp_err)

        n_ctx = max(512, _safe_int(cfg.get("n_ctx", 4096), 4096))
        n_batch = max(1, min(n_ctx, _safe_int(cfg.get("n_batch", 512), 512)))

        # Auto-detect thread counts if not in config
        auto_t = _auto_threads()
        n_threads = max(1, _safe_int(cfg["n_threads"], auto_t)) if cfg.get("n_threads") else auto_t
        # Dynamic governor: throttle threads when the user is active so a *background*
        # generation can't choke a low-end laptop. BUT an explicit n_threads is a deliberate
        # operator choice and must win — otherwise the foreground model the user is actively
        # waiting on gets silently halved (WHISPER = active user = *every* interactive turn),
        # which is the opposite of helpful. Only auto-throttle when n_threads was NOT pinned.
        if cfg.get("resource_governor_enabled", True) and not cfg.get("n_threads"):
            try:
                from services.infrastructure.resource_governor import get_governor
                n_threads = max(1, get_governor().get_inference_threads(auto_t))
            except Exception as _gov_e:
                logger.debug("governor inference-threads unavailable: %s", _gov_e)
        # Batch threads: more threads help here; use logical count capped at 2× physical
        n_threads_batch = (
            max(1, _safe_int(cfg["n_threads_batch"], n_threads)) if cfg.get("n_threads_batch")
            else min(n_threads * 2, (os.cpu_count() or n_threads))
        )

        # n_keep: pin this many tokens in KV cache during context-shifting.
        # Set to system prompt token estimate so the identity is never evicted.
        # ~1 token per 4 chars; system prompts are typically 500-2000 chars.
        n_keep = max(64, _safe_int(cfg.get("n_keep", 512), 512))

        # Flash attention gives no speedup on CPU in llama-cpp-python and (by enabling the
        # Q8_0 KV-quant below) actually SLOWS CPU attention — so default it OFF when running
        # CPU-only (n_gpu_layers == 0). GPU runs still default it on.
        _cpu_only = _safe_int(cfg.get("n_gpu_layers", -1), -1) == 0
        use_flash = bool(cfg.get("flash_attn", not _cpu_only))
        kwargs = {
            "model_path": str(model_path),
            "n_ctx": n_ctx,
            "n_gpu_layers": _safe_int(cfg.get("n_gpu_layers", -1), -1),  # -1 = full GPU offload when VRAM allows
            "n_batch": n_batch,
            "n_threads": n_threads,
            "n_threads_batch": n_threads_batch,
            "use_mlock": bool(cfg.get("use_mlock", False)),
            "use_mmap": bool(cfg.get("use_mmap", True)),
            "verbose": False,
            # Flash attention: dramatically reduces VRAM + speeds up long contexts
            "flash_attn": use_flash,
            # Pin system-prompt tokens in KV cache — never re-evaluated on context shift
            "n_keep": n_keep,
        }
        # KV-cache quantization: int8 halves VRAM for KV cache (safe quality tradeoff).
        # Requires flash_attn=True — llama.cpp rejects type_k/type_v != f16 without it.
        if use_flash:
            kwargs["type_k"] = int(cfg.get("type_k", 8))   # 8 = GGML_TYPE_Q8_0
            kwargs["type_v"] = int(cfg.get("type_v", 8))

        # Speculative decoding (prompt lookup) can significantly increase throughput.
        # Safe on older llama-cpp-python: unsupported kwargs are stripped by the TypeError fallback below.
        if cfg.get("speculative_decoding_enabled", False):
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

        # BL-108: KV-cache prompt-prefix reuse. Layla's system prompt is large and stable
        # across turns; a LlamaRAMCache lets llama.cpp skip re-prefilling the shared prefix,
        # cutting time-to-first-token on every follow-up. Opt-in (kv_prompt_cache_enabled),
        # bounded by kv_prompt_cache_mb. Best-effort — never block model load.
        try:
            if cfg.get("kv_prompt_cache_enabled"):
                _apply_prompt_cache(inst, int(cfg.get("kv_prompt_cache_mb", 512) or 512))
        except Exception as _kv:
            logger.debug("kv prompt cache setup skipped: %s", _kv)

        # F9: bound the resident-model cache before inserting so routing can't OOM.
        try:
            _evict_models_if_needed(int(cfg.get("max_resident_models", _DEFAULT_MAX_RESIDENT_MODELS)))
        except Exception as _ev:
            logger.debug("model eviction skipped: %s", _ev)
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
                from services.llm.model_benchmark import run_benchmark
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


# ── WHISPER idle unload with grace period ─────────────────────────────────
_idle_unload_timer: threading.Timer | None = None
_idle_timer_lock = threading.Lock()


def schedule_idle_unload(delay_seconds: int = 120) -> threading.Timer:
    """Schedule model unload after `delay_seconds` of idle.

    Returns the Timer so callers can cancel it (e.g. on mode change or new
    inference request).  If a timer is already pending it is replaced.
    """
    global _idle_unload_timer
    with _idle_timer_lock:
        if _idle_unload_timer is not None:
            _idle_unload_timer.cancel()

        def _do_unload():
            logger.info("WHISPER idle unload: releasing LLM after %ds idle", delay_seconds)
            invalidate_llm_cache()

        _idle_unload_timer = threading.Timer(delay_seconds, _do_unload)
        _idle_unload_timer.daemon = True
        _idle_unload_timer.name = "llm-idle-unload"
        _idle_unload_timer.start()
        return _idle_unload_timer


def cancel_idle_unload() -> None:
    """Cancel any pending idle unload (called when a new inference request arrives)."""
    global _idle_unload_timer
    with _idle_timer_lock:
        if _idle_unload_timer is not None:
            _idle_unload_timer.cancel()
            _idle_unload_timer = None


def get_stop_sequences():
    """Stop sequences so the model does not continue into the next turn."""
    import runtime_safety
    cfg = runtime_safety.load_config()
    stop = cfg.get("stop_sequences")
    if isinstance(stop, list) and stop:
        return [str(s) for s in stop if s]
    # Stop the model from echoing system-prompt section headers back into replies.
    # SmolLM2 and similar small models tend to repeat ## CONTEXT / ## TASK verbatim.
    return [
        "\nUser:", " User:", "\nYou:", " You:", "\nHuman:",
        "\n## ", "## CONTEXT", "## TASK", "## SCRATCHPAD", "## REPO",
        # Prevent fake multi-speaker roleplay (model echoes aspect names as dialogue tags)
        "\nMorrigan:", "\nNyx:", "\nEcho:", "\nEris:", "\nCassandra:", "\nLilith:",
        "Morrigan:", "Echo:", "Nyx:",  # also at position 0 if response starts with them
        # Prevent memory-artifact leakage
        "\nReplied.", "Snippet:", "\nSnippet:",
        "<|endoftext|>", "<|im_end|>",
    ]


def _count_tokens(text: str) -> int:
    """Count tokens — delegates to the canonical cached counter (services.llm.token_count).

    The previous local copy re-created the tiktoken encoding on EVERY call, which is
    wasteful on the per-chunk streaming hot path; count_tokens caches the encoding."""
    if not text:
        return 0
    from services.llm.token_count import count_tokens
    return count_tokens(text)


def _safe_int(val, default: int) -> int:
    """int() that degrades to a default instead of crashing model load on a garbage
    config value (e.g. n_keep="abc" in a hand-edited runtime_config.json)."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _add_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Add token counts to session totals and active per-turn trace."""
    with _token_usage_lock:
        _token_usage["prompt_tokens"] += prompt_tokens
        _token_usage["completion_tokens"] += completion_tokens
        _token_usage["total_tokens"] += prompt_tokens + completion_tokens
        _token_usage["request_count"] += 1
    # Per-turn trace: record tokens for this specific request.
    try:
        from services.observability.request_tracer import record_trace_tokens
        record_trace_tokens(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    except Exception:
        pass


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


def extract_litellm_cost(result: dict | None) -> dict:
    """Extract litellm cost metadata from a run_completion result, if present.

    Returns a dict with keys ``cost_usd``, ``provider``, ``model`` —
    all defaulting to zero / empty string when litellm wasn't used.
    """
    if not isinstance(result, dict):
        return {"cost_usd": 0.0, "provider": "", "model": ""}
    meta = result.get("_litellm") or {}
    return {
        "cost_usd": float(meta.get("cost_usd", 0.0)),
        "provider": str(meta.get("provider", "")),
        "model": str(meta.get("model", "")),
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
    # Cancel any pending WHISPER idle unload — active inference means model is needed
    try:
        cancel_idle_unload()
    except Exception:
        pass
    import runtime_safety
    from services.llm.inference_router import run_completion as _run

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
                from services.retrieval.completion_cache import get_cached

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

        # ── LiteLLM multi-provider gateway ────────────────────────────────
        # When litellm_enabled is true, delegate to litellm_gateway which
        # provides automatic failover across 100+ LLM providers. Only take this
        # path when a model is actually configured — otherwise litellm raises
        # "No model specified" on EVERY turn and falls back to local anyway,
        # burning a failed attempt + error-log spam on each request.
        _litellm_model_cfg = (model_override or cfg.get("litellm_default_model") or "").strip()
        if cfg.get("litellm_enabled", False) and _litellm_model_cfg:
            try:
                from services.llm.litellm_gateway import complete as _litellm_complete
                from services.llm.litellm_gateway import complete_stream as _litellm_stream
                from services.llm.litellm_gateway import is_available as _litellm_ok

                if _litellm_ok():
                    _litellm_messages = [{"role": "user", "content": prompt}]
                    _litellm_model = model_override or None

                    if stream:
                        def _litellm_stream_gen():
                            completion_tokens = 0
                            try:
                                for chunk in _litellm_stream(
                                    _litellm_messages,
                                    model=_litellm_model,
                                    max_tokens=max_tokens,
                                    temperature=temperature,
                                    stop=stop,
                                    timeout=timeout_seconds,
                                ):
                                    completion_tokens += _count_tokens(chunk)
                                    yield chunk
                            finally:
                                _add_usage(prompt_tokens, completion_tokens)
                                _routing_prompt_var.reset(routing_tok)
                        return _litellm_stream_gen()

                    # Non-streaming litellm completion
                    _litellm_result = _litellm_complete(
                        _litellm_messages,
                        model=_litellm_model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stop=stop,
                        timeout=timeout_seconds,
                    )
                    text = _litellm_result.get("content", "")
                    completion_tokens = _count_tokens(text)
                    _add_usage(prompt_tokens, completion_tokens)
                    # Convert to standard run_completion return format
                    out = {
                        "choices": [{"message": {"content": text}}],
                        "_litellm": {
                            "model": _litellm_result.get("model", ""),
                            "provider": _litellm_result.get("provider", ""),
                            "latency_ms": _litellm_result.get("latency_ms", 0),
                            "cost_usd": _litellm_result.get("cost_usd", 0),
                            "usage": _litellm_result.get("usage", {}),
                        },
                    }
                    if cfg.get("completion_cache_enabled") and isinstance(out, dict):
                        try:
                            from services.retrieval.completion_cache import set_cached
                            set_cached(prompt or "", routing_tag, cache_model_name or "litellm", float(temperature), int(max_tokens), out)
                        except Exception:
                            pass
                    return out
            except Exception as _litellm_exc:
                logger.warning("litellm_gateway failed, falling back to local: %s", _litellm_exc)
                # Fall through to standard inference path

        if stream:

            def _counting_gen():
                completion_tokens = 0
                try:
                    from services.observability.trace_export import maybe_span

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
        _llm_start_t = time.monotonic()
        from services.observability.trace_export import maybe_span

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
        # Phase 3: Prometheus LLM metrics (fire-and-forget)
        try:
            from services.observability.prom_metrics import record_llm_request as _record_llm
            _llm_dur = time.monotonic() - _llm_start_t
            _record_llm(cache_model_name or "default", "", _llm_dur)
        except Exception:
            pass
        if cfg.get("completion_cache_enabled") and isinstance(out, dict):
            try:
                from services.retrieval.completion_cache import set_cached

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

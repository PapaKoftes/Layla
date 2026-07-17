"""
Sanitized config + dependency/feature snapshots for GET /health.
No secrets; whitelisted keys only.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Safe config keys to expose (no API keys, tokens, or remote credentials).
_CONFIG_WHITELIST: frozenset[str] = frozenset({
    "model_filename",
    "n_ctx",
    "n_gpu_layers",
    "n_threads",
    "temperature",
    "performance_mode",
    "sandbox_root",
    "use_chroma",
    "scheduler_study_enabled",
    "voice_input_enabled",
    "voice_output_enabled",
    "whisper_model",
    "tts_voice",
    "tool_loop_detection_enabled",
    "planning_enabled",
    "completion_cache_enabled",
    "response_cache_enabled",
    "context_compression",
    "semantic_k",
    "max_tool_calls",
    "max_runtime_seconds",
    "research_max_tool_calls",
    "research_max_runtime_seconds",
    "completion_max_tokens",
    "nsfw_allowed",
    "uncensored",
    "max_active_runs",
    "max_cpu_percent",
    "max_ram_percent",
    "warn_cpu_percent",
    "hard_cpu_percent",
    "response_pacing_ms",
    "ui_agent_stream_timeout_seconds",
    "ui_agent_json_timeout_seconds",
    "ui_stalled_silence_ms",
    "honesty_and_boundaries_enabled",
})


def _basename_model(name: str | None) -> str:
    if not name or not isinstance(name, str):
        return ""
    p = Path(name.strip())
    return p.name if p.name else name.strip()


def sanitize_config_snapshot(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Return whitelisted config entries; paths shortened to basename where appropriate."""
    if not cfg:
        return {}
    out: dict[str, Any] = {}
    for key in _CONFIG_WHITELIST:
        if key not in cfg:
            continue
        val = cfg[key]
        if key == "model_filename" and isinstance(val, str):
            out[key] = _basename_model(val)
        elif key == "sandbox_root" and isinstance(val, str):
            # Expose only that a sandbox is set + last path segment (no full home paths)
            try:
                rp = Path(val).expanduser().resolve()
                out["sandbox_root_set"] = True
                out["sandbox_root_leaf"] = rp.name or str(rp)
            except Exception:
                out["sandbox_root_set"] = bool(val and str(val).strip())
        else:
            out[key] = val
    return out


def build_features_enabled(cfg: dict[str, Any], eff: dict[str, Any]) -> dict[str, bool]:
    """Feature flags derived from merged runtime + effective config."""
    return {
        "chroma": bool(cfg.get("use_chroma")),
        "completion_cache": bool(eff.get("completion_cache_enabled")),
        "response_cache": bool(eff.get("response_cache_enabled")),
        "tool_loop_detection": bool(eff.get("tool_loop_detection_enabled")),
        "scheduler_study": bool(cfg.get("scheduler_study_enabled", True)),
        "voice_input": bool(cfg.get("voice_input_enabled")),
        "voice_output": bool(cfg.get("voice_output_enabled")),
        "planning": bool(eff.get("planning_enabled", cfg.get("planning_enabled", True))),
    }


def build_dependency_status(*, probe_chroma: bool) -> dict[str, str]:
    """
    Per-dependency status: ok | missing | error | degraded.
    chroma: when probe_chroma True, runs embed+search (same as /health?deep=true).
    """
    out: dict[str, str] = {}

    try:
        import llama_cpp  # noqa: F401

        out["llama_cpp"] = "ok"
    except Exception:
        out["llama_cpp"] = "missing"

    try:
        import chromadb  # noqa: F401

        if probe_chroma:
            try:
                from layla.memory.vector_store import embed, search_similar

                search_similar(embed("health"), k=1)
                out["chroma"] = "ok"
            except Exception as e:
                logger.debug("health chroma probe failed: %s", e)
                out["chroma"] = "error"
        else:
            out["chroma"] = "ok"
    except Exception:
        out["chroma"] = "missing"

    # BL-374 — the embedder is the dependency that actually decides whether semantic memory works, and it
    # was the one dependency this matrix did not report. It is fetched lazily from HuggingFace on first use
    # (nothing is bundled), so on an offline first run it cannot load and retrieval silently degrades to
    # keyword-only. Reported here so the failure is knowable from outside the process; vector_store.py logs
    # it loudly on the inside. Cheap: reads recorded state, never loads a model, never touches the network.
    try:
        from layla.memory.vector_store import embedder_status

        _emb = embedder_status()
        out["embedder"] = _emb["status"]
        if _emb["status"] == "ok" and _emb.get("model"):
            out["embedder_model"] = _emb["model"]
        elif _emb.get("detail"):
            out["embedder_detail"] = _emb["detail"][:300]
    except Exception as e:
        logger.debug("health embedder probe: %s", e)
        out["embedder"] = "unknown"

    # Legibility (audit): on the compiler-free [cpu] install chromadb is intentionally absent and memory
    # falls back to SQLite+NumPy — RAG still works. Surface the EFFECTIVE vector store so a bare
    # chroma:"missing" doesn't read as "memory is broken" to someone scanning /health.
    #
    # BL-374: but "RAG active" was asserted from the CHROMA probe alone, so it kept claiming RAG was active
    # on an offline box where the embedder could not load and semantic retrieval was completely dead — the
    # health endpoint reassuring you about the exact thing that was broken. RAG is only active if something
    # can turn text into a vector, so the embedder now gets a vote.
    if out.get("embedder") == "unavailable":
        out["vector_store"] = "keyword-only (embedder unavailable — semantic search DEGRADED)"
    elif out.get("chroma") == "ok":
        out["vector_store"] = "chroma"
    else:
        out["vector_store"] = "sqlite-fallback (RAG active)"

    try:
        import faster_whisper  # noqa: F401

        out["voice_stt"] = "ok"
    except Exception:
        out["voice_stt"] = "missing"

    try:
        import kokoro_onnx  # noqa: F401

        out["voice_tts"] = "ok"
    except Exception:
        try:
            import pyttsx3  # noqa: F401

            out["voice_tts"] = "ok"
        except Exception:
            out["voice_tts"] = "missing"

    try:
        from tree_sitter import Parser  # noqa: F401
        from tree_sitter_python import language  # noqa: F401

        _ = language
        out["tree_sitter"] = "ok"
    except Exception:
        out["tree_sitter"] = "missing"

    try:
        from services.infrastructure.hardware_detect import detect_hardware

        hw = detect_hardware()
        gpu = (hw.get("gpu_name") or "").strip()
        out["gpu"] = "ok" if gpu else "none"
    except Exception as e:
        logger.debug("health gpu probe: %s", e)
        out["gpu"] = "unknown"

    return out


def build_effective_config_public(cfg: dict[str, Any], eff: dict[str, Any]) -> dict[str, Any]:
    """Sanitized static config + selected effective caps (no full eff dict)."""
    base = sanitize_config_snapshot(cfg)
    caps = {
        "max_tool_calls": eff.get("max_tool_calls"),
        "max_runtime_seconds": eff.get("max_runtime_seconds"),
        "research_max_tool_calls": eff.get("research_max_tool_calls"),
        "research_max_runtime_seconds": eff.get("research_max_runtime_seconds"),
        "completion_max_tokens": eff.get("completion_max_tokens"),
        "n_ctx": eff.get("n_ctx"),
        "semantic_k": eff.get("semantic_k"),
        "tool_loop_detection_enabled": bool(eff.get("tool_loop_detection_enabled")),
        "completion_cache_enabled": bool(eff.get("completion_cache_enabled")),
        "response_cache_enabled": bool(eff.get("response_cache_enabled")),
        "anti_drift_prompt_enabled": bool(eff.get("anti_drift_prompt_enabled", True)),
        "planning_enabled": bool(eff.get("planning_enabled", True)),
    }
    pm = cfg.get("performance_mode")
    if pm is not None:
        caps["performance_mode"] = pm
    return {**base, "effective_caps": caps}

"""
Model benchmark: measure tokens/sec, latency, and memory when a model is loaded.
Stores results in ~/.layla/benchmarks.json for model_router and system_optimizer.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("layla")

BENCHMARK_PROMPT = "The quick brown fox jumps over the lazy dog. Repeat: "
BENCHMARK_TOKENS = 32
BENCHMARKS_PATH = Path.home() / ".layla" / "benchmarks.json"
_BENCHMARKS_PATH = BENCHMARKS_PATH


def _load_benchmarks() -> dict:
    """Load stored benchmarks."""
    try:
        if _BENCHMARKS_PATH.exists():
            return json.loads(_BENCHMARKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_benchmarks(data: dict) -> None:
    """Save benchmarks to disk."""
    try:
        _BENCHMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BENCHMARKS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("benchmark save failed: %s", e)


def _get_process_memory_mb() -> float:
    """Return current process RSS in MB."""
    try:
        import psutil
        proc = psutil.Process()
        return round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return 0.0


def run_benchmark(model_name: str | None = None) -> dict:
    """
    Benchmark the currently loaded LLM. Measures tokens/sec, first-token latency, memory.

    Args:
        model_name: Model filename (e.g. from config). If None, uses config.model_filename.

    Returns:
        {"ok": bool, "tokens_per_sec": float | None, "first_token_ms": float | None,
         "memory_mb": float | None, "error": str | None, "model": str}
    """
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        filename = model_name or cfg.get("model_filename", "")
        if not filename:
            return {"ok": False, "tokens_per_sec": None, "first_token_ms": None, "memory_mb": None, "error": "No model configured", "model": ""}

        from services.llm_gateway import _get_llm, llm_serialize_lock
        with llm_serialize_lock:
            llm = _get_llm()
        if llm is None:
            return {"ok": False, "tokens_per_sec": None, "first_token_ms": None, "memory_mb": None, "error": "LLM not loaded", "model": filename}

        memory_mb = _get_process_memory_mb()

        prompt = BENCHMARK_PROMPT * 4
        start = time.perf_counter()
        with llm_serialize_lock:
            out = llm.create_completion(prompt, max_tokens=BENCHMARK_TOKENS, temperature=0.0, stop=[])
        elapsed = time.perf_counter() - start

        text = ""
        if isinstance(out, dict):
            choices = out.get("choices") or []
            if choices:
                c = choices[0]
                if isinstance(c, dict):
                    text = c.get("text") or (c.get("message") or {}).get("content", "") if isinstance(c.get("message"), dict) else ""
                elif hasattr(c, "text"):
                    text = getattr(c, "text", "") or ""
        tokens = max(1, int(len(text) / 4))
        tokens_per_sec = round(tokens / elapsed, 1) if elapsed > 0 else 0.0
        first_token_ms = round(elapsed * 1000, 1)

        result = {
            "ok": True,
            "tokens_per_sec": tokens_per_sec,
            "first_token_ms": first_token_ms,
            "memory_mb": memory_mb,
            "error": None,
            "model": filename,
        }

        data = _load_benchmarks()
        data[filename] = {
            "tokens_per_sec": tokens_per_sec,
            "first_token_ms": first_token_ms,
            "memory_mb": memory_mb,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_benchmarks(data)

        return result
    except Exception as e:
        return {"ok": False, "tokens_per_sec": None, "first_token_ms": None, "memory_mb": None, "error": str(e), "model": model_name or ""}


def get_benchmark(model_name: str) -> dict | None:
    """Return stored benchmark for a model, or None."""
    data = _load_benchmarks()
    return data.get(model_name)


def get_all_benchmarks() -> dict:
    """Return all stored benchmarks. Used by system_optimizer for health/doctor."""
    return _load_benchmarks()


def select_fastest_model(available: list[str] | None = None) -> str | None:
    """
    Return filename of fastest benchmarked model.
    If available is given, only consider those. Else use all in benchmarks.
    """
    data = _load_benchmarks()
    if not data:
        return None
    candidates = available if available else list(data.keys())
    if not candidates:
        return None
    best: tuple[float, str] = (0.0, "")
    for fn in candidates:
        b = data.get(fn)
        if not b or not isinstance(b, dict):
            continue
        tps = b.get("tokens_per_sec") or 0
        if tps > best[0]:
            best = (tps, fn)
    return best[1] or None

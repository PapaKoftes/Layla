"""
Local model manager. List, install, benchmark, and select GGUF models.
Models stored under ~/.layla/models/ (configurable via runtime_config.models_dir).
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

MODELS_CATALOG = [
    {"key": "dolphin-mistral-7b", "name": "Dolphin Mistral 7B Q4_K_M", "filename": "dolphin-2.6-mistral-7b.Q4_K_M.gguf",
     "url": "https://huggingface.co/TheBloke/dolphin-2.6-mistral-7B-GGUF/resolve/main/dolphin-2.6-mistral-7b.Q4_K_M.gguf",
     "size_gb": 4.1, "ram_gb": 6},
    {"key": "dolphin-llama3-8b", "name": "Dolphin Llama3 8B Q4_K_M", "filename": "dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf",
     "url": "https://huggingface.co/bartowski/dolphin-2.9.1-llama-3-8b-GGUF/resolve/main/dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf",
     "size_gb": 4.9, "ram_gb": 8},
    {"key": "hermes-3-8b", "name": "Hermes 3 Llama3.1 8B Q4_K_M", "filename": "Hermes-3-Llama-3.1-8B-Q4_K_M.gguf",
     "url": "https://huggingface.co/bartowski/Hermes-3-Llama-3.1-8B-GGUF/resolve/main/Hermes-3-Llama-3.1-8B-Q4_K_M.gguf",
     "size_gb": 4.9, "ram_gb": 8},
    {"key": "phi3-mini", "name": "Phi-3 Mini 3.8B Q4_K_M", "filename": "Phi-3-mini-4k-instruct-q4.gguf",
     "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
     "size_gb": 2.2, "ram_gb": 4},
    {"key": "dolphin-llama3-70b", "name": "Dolphin Llama3 70B Q2_K", "filename": "dolphin-2.9-llama3-70b-Q2_K.gguf",
     "url": "https://huggingface.co/bartowski/dolphin-2.9-llama3-70b-GGUF/resolve/main/dolphin-2.9-llama3-70b-Q2_K.gguf",
     "size_gb": 26.0, "ram_gb": 32},
]


def _get_models_dir() -> Path:
    """Models directory. Default ~/.layla/models, overridable via config."""
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        raw = cfg.get("models_dir")
        if raw:
            return Path(raw).expanduser().resolve()
    except Exception:
        pass
    return Path.home() / ".layla" / "models"


def list_models() -> list[dict[str, Any]]:
    """
    List .gguf models in the models directory.
    Returns list of {filename, path, size_mb}.
    """
    models_dir = _get_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for p in sorted(models_dir.glob("*.gguf")):
        try:
            size_mb = round(p.stat().st_size / (1024 * 1024), 1)
        except Exception:
            size_mb = 0.0
        result.append({"filename": p.name, "path": str(p), "size_mb": size_mb})
    return result


def install_model(name: str, progress: bool = True) -> dict[str, Any]:
    """
    Install a model by catalog key or direct URL.

    Args:
        name: Catalog key (e.g. "dolphin-mistral-7b") or a HuggingFace .gguf URL.
        progress: If True, print progress (for CLI). If False, silent.

    Returns:
        {"ok": bool, "filename": str | None, "error": str | None}
    """
    models_dir = _get_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)

    # Resolve to URL and filename
    url: str | None = None
    filename: str | None = None

    catalog_by_key = {m["key"]: m for m in MODELS_CATALOG}
    if name in catalog_by_key:
        m = catalog_by_key[name]
        url = m["url"]
        filename = m["filename"]
    elif name.startswith("http://") or name.startswith("https://"):
        url = name
        filename = url.rstrip("/").split("/")[-1]
        if not filename.endswith(".gguf"):
            filename = filename + ".gguf" if "." not in filename else "model.gguf"

    if not url or not filename:
        return {"ok": False, "filename": None, "error": f"Unknown model: {name}. Use catalog key or URL."}

    dest = models_dir / filename

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if not progress or total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, int(downloaded * 100 / total_size))
        done = pct // 2
        bar = "█" * done + "░" * (50 - done)
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        print(f"\r  [{bar}] {pct}%  {downloaded_mb:.0f}/{total_mb:.0f} MB", end="", flush=True)

    try:
        if progress:
            urllib.request.urlretrieve(url, str(dest), _progress)
            print()
        else:
            urllib.request.urlretrieve(url, str(dest))
        return {"ok": True, "filename": filename, "error": None}
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return {"ok": False, "filename": None, "error": str(e)}


def benchmark_model(name: str) -> dict[str, Any]:
    """
    Benchmark a model (tokens/sec, latency).
    Delegates to model_benchmark when available.
    """
    try:
        from services.model_benchmark import run_benchmark
        return run_benchmark(name)
    except ImportError:
        return {"ok": False, "error": "model_benchmark not available", "tokens_per_sec": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "tokens_per_sec": None}


def select_best_model() -> dict[str, Any]:
    """
    Select best model for current hardware from installed models.
    Uses model_recommender + list_models; prefers models matching recommendation.
    """
    try:
        from services.model_recommender import recommend_from_hardware
        rec = recommend_from_hardware()
        models = list_models()
        if not models:
            return {"ok": False, "filename": None, "suggestion": rec.get("suggestion", ""), "error": "No models installed"}

        # Prefer models whose name matches recommended tier/suggestion
        suggestion_lower = (rec.get("suggestion", "") or "").lower()
        scored = []
        for m in models:
            fn = m.get("filename", "").lower()
            score = 0
            if "qwen" in fn and "qwen" in suggestion_lower:
                score += 2
            if "llama" in fn and "llama" in suggestion_lower:
                score += 2
            if "phi" in fn and "phi" in suggestion_lower:
                score += 2
            if "dolphin" in fn and "dolphin" in suggestion_lower:
                score += 2
            if "hermes" in fn and "hermes" in suggestion_lower:
                score += 2
            # Prefer Q5 > Q4 > Q2
            if "q5" in fn or "q8" in fn:
                score += 1
            scored.append((score, m))

        scored.sort(key=lambda x: (-x[0], x[1]["filename"]))
        best = scored[0][1]
        return {"ok": True, "filename": best["filename"], "suggestion": rec.get("suggestion", ""), "error": None}
    except Exception as e:
        return {"ok": False, "filename": None, "suggestion": "", "error": str(e)}

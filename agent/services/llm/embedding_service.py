"""
Unified embedding API for memory, code workspace index, and tools.

Routes to local sentence-transformers (layla.memory.vector_store) by default,
or to Ollama HTTP /api/embeddings when embed_backend is ollama.

Env: LAYLA_EMBED_BACKEND=local|ollama
Config: embed_backend, ollama_base_url, ollama_embed_model (or remote_embed_model)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

import numpy as np

logger = logging.getLogger("layla")


def _load_cfg() -> dict[str, Any]:
    try:
        import runtime_safety

        return runtime_safety.load_config()
    except Exception:
        return {}


def embed_backend() -> str:
    e = (os.environ.get("LAYLA_EMBED_BACKEND") or "").strip().lower()
    if e in ("local", "ollama"):
        return e
    cfg = _load_cfg()
    raw = str(cfg.get("embed_backend") or "local").strip().lower()
    return raw if raw in ("local", "ollama") else "local"


def _ollama_base_and_model(cfg: dict[str, Any]) -> tuple[str, str]:
    base = (cfg.get("ollama_base_url") or cfg.get("llama_server_url") or "").strip().rstrip("/")
    model = (
        cfg.get("ollama_embed_model")
        or cfg.get("remote_embed_model")
        or "nomic-embed-text"
    )
    model = str(model).strip()
    return base, model


def _ollama_embed_one(text: str, base: str, model: str) -> list[float]:
    url = f"{base}/api/embeddings"
    body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    emb = data.get("embedding")
    if not isinstance(emb, list):
        raise ValueError("ollama embeddings response missing embedding array")
    return [float(x) for x in emb]


def embed_text(text: str) -> np.ndarray:
    """Single normalized float32 embedding vector."""
    vecs = embed_batch([(text or "").strip() or " "])
    return vecs[0]


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    """Batch embeddings as float32 numpy vectors (normalized when local)."""
    if not texts:
        return []
    if embed_backend() == "ollama":
        return _embed_batch_ollama(texts)
    from layla.memory.vector_store import embed_batch as _local_batch

    return _local_batch(texts)


def _embed_batch_ollama(texts: list[str]) -> list[np.ndarray]:
    cfg = _load_cfg()
    base, model = _ollama_base_and_model(cfg)
    if not base:
        logger.warning("embedding_service: ollama backend selected but no ollama_base_url; using local embedder")
        from layla.memory.vector_store import embed_batch as _local_batch

        return _local_batch(texts)
    out: list[np.ndarray] = []
    for t in texts:
        try:
            vec = _ollama_embed_one(t, base, model)
            arr = np.array(vec, dtype=np.float32)
            n = float(np.linalg.norm(arr))
            if n > 1e-8:
                arr = arr / n
            out.append(arr.astype(np.float32))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError, OSError) as e:
            logger.warning("embedding_service: ollama embed failed (%s); falling back to local for one chunk", e)
            from layla.memory.vector_store import embed as _local_embed

            out.append(_local_embed(t))
    return out

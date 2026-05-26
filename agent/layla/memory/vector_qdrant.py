"""Qdrant vector store adapter (alternative to ChromaDB).

Config-gated via ``vector_backend: "qdrant"`` in runtime_safety config.
All public functions degrade gracefully when ``qdrant-client`` is not installed.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

_client = None
_client_lock = None


def _try_import_qdrant():
    try:
        import qdrant_client  # noqa: F401
        return True
    except ImportError:
        return False


def is_available(cfg: dict) -> bool:
    if not _try_import_qdrant():
        return False
    url = cfg.get("qdrant_url", "http://localhost:6333")
    try:
        from qdrant_client import QdrantClient
        c = QdrantClient(url=url, timeout=3)
        c.get_collections()
        return True
    except Exception:
        return False


def get_client(cfg: dict) -> Any | None:
    global _client, _client_lock
    if not _try_import_qdrant():
        return None
    if _client is not None:
        return _client
    if _client_lock is None:
        import threading
        _client_lock = threading.Lock()
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from qdrant_client import QdrantClient
            url = cfg.get("qdrant_url", "http://localhost:6333")
            api_key = cfg.get("qdrant_api_key")
            _client = QdrantClient(url=url, api_key=api_key, timeout=10)
            return _client
        except Exception as exc:
            logger.debug("vector_qdrant: get_client failed: %s", exc)
            return None


def ensure_collection(cfg: dict) -> bool:
    client = get_client(cfg)
    if client is None:
        return False
    name = cfg.get("qdrant_collection", "layla-memories")
    try:
        from qdrant_client.models import Distance, VectorParams
        collections = [c.name for c in client.get_collections().collections]
        if name not in collections:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
        return True
    except Exception as exc:
        logger.debug("vector_qdrant: ensure_collection failed: %s", exc)
        return False


def add_memories(cfg: dict, memories: list[dict]) -> dict:
    if not memories:
        return {"ok": True, "count": 0}
    client = get_client(cfg)
    if client is None:
        return {"ok": False, "count": 0, "error": "qdrant unavailable"}
    name = cfg.get("qdrant_collection", "layla-memories")
    try:
        from qdrant_client.models import PointStruct
        if not ensure_collection(cfg):
            return {"ok": False, "count": 0, "error": "collection setup failed"}
        points = []
        for m in memories:
            points.append(PointStruct(
                id=m["id"],
                vector=m["embedding"],
                payload={"text": m.get("text", ""), "metadata": m.get("metadata", {})},
            ))
        client.upsert(collection_name=name, points=points)
        return {"ok": True, "count": len(points)}
    except Exception as exc:
        logger.debug("vector_qdrant: add_memories failed: %s", exc)
        return {"ok": False, "count": 0, "error": str(exc)}


def search_memories(cfg: dict, embedding: list[float], k: int = 5) -> list[dict]:
    client = get_client(cfg)
    if client is None:
        return []
    name = cfg.get("qdrant_collection", "layla-memories")
    if not ensure_collection(cfg):
        return []
    try:
        hits = client.search(collection_name=name, query_vector=embedding, limit=k)
        return [
            {"id": str(h.id), "score": h.score, **h.payload}
            for h in hits
        ]
    except Exception as exc:
        logger.debug("vector_qdrant: search_memories failed: %s", exc)
        return []


def delete_memories(cfg: dict, ids: list[str]) -> dict:
    client = get_client(cfg)
    if client is None:
        return {"ok": False, "error": "qdrant unavailable"}
    name = cfg.get("qdrant_collection", "layla-memories")
    try:
        from qdrant_client.models import PointIdsList
        client.delete(collection_name=name, points_selector=PointIdsList(points=ids))
        return {"ok": True, "deleted": len(ids)}
    except Exception as exc:
        logger.debug("vector_qdrant: delete_memories failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def get_stats(cfg: dict) -> dict:
    client = get_client(cfg)
    if client is None:
        return {"available": False}
    name = cfg.get("qdrant_collection", "layla-memories")
    try:
        info = client.get_collection(collection_name=name)
        return {
            "available": True,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
        }
    except Exception as exc:
        logger.debug("vector_qdrant: get_stats failed: %s", exc)
        return {"available": False, "error": str(exc)}

"""
Meilisearch adapter for Layla — lightweight alternative to Elasticsearch.

Same interface as elasticsearch_bridge.py: index_learning(), search_learnings().
Meilisearch is a 50MB binary with zero config (vs JVM-heavy Elasticsearch).

Config keys (runtime_safety.py):
  meilisearch_enabled: bool
  meilisearch_url: str         — default "http://localhost:7700"
  meilisearch_api_key: str     — optional master key
  meilisearch_index: str       — default "layla-learnings"
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

_WARNED: set[str] = set()
_client_cache: Any = None


def _warn_once(key: str, msg: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(msg)


def client_from_config(cfg: dict[str, Any]) -> Any | None:
    """Get or create a Meilisearch client from config."""
    global _client_cache
    if not cfg.get("meilisearch_enabled"):
        return None
    url = str(cfg.get("meilisearch_url") or "http://localhost:7700").strip()
    if not url:
        _warn_once("ms_no_url", "meilisearch_enabled but no URL configured")
        return None
    try:
        import meilisearch  # type: ignore
    except ImportError:
        _warn_once(
            "ms_no_pkg",
            "meilisearch_enabled but meilisearch package not installed; run: pip install meilisearch",
        )
        return None
    api_key = cfg.get("meilisearch_api_key")
    key = str(api_key).strip() if api_key else None
    try:
        client = meilisearch.Client(url, key)
        return client
    except Exception as e:
        _warn_once("ms_connect", f"Failed to create Meilisearch client: {e}")
        return None


def _get_index(cfg: dict[str, Any]):
    """Get or create the learnings index."""
    client = client_from_config(cfg)
    if client is None:
        return None
    index_name = str(cfg.get("meilisearch_index") or "layla-learnings").strip()
    try:
        # Create index if it doesn't exist (idempotent)
        client.create_index(index_name, {"primaryKey": "id"})
    except Exception:
        pass  # Index might already exist
    return client.index(index_name)


def is_available(cfg: dict[str, Any]) -> bool:
    """Check if Meilisearch is reachable."""
    client = client_from_config(cfg)
    if client is None:
        return False
    try:
        health = client.health()
        return health.get("status") == "available"
    except Exception:
        return False


def index_learning(
    cfg: dict[str, Any],
    *,
    rid: int,
    text: str,
    tags: str | None = None,
    source: str | None = None,
) -> None:
    """Index a learning document into Meilisearch."""
    if not cfg.get("meilisearch_enabled"):
        return
    index = _get_index(cfg)
    if index is None:
        return
    doc = {
        "id": rid,
        "text": text or "",
        "tags": tags or "",
        "source": source or "learning",
    }
    try:
        index.add_documents([doc])
    except Exception as e:
        logger.warning("meilisearch index failed for learning id=%s: %s", rid, e)


def search_learnings(cfg: dict[str, Any], q: str, limit: int = 20) -> dict[str, Any]:
    """Search learnings in Meilisearch."""
    if not cfg.get("meilisearch_enabled"):
        return {"ok": False, "error": "meilisearch_disabled", "hits": []}
    index = _get_index(cfg)
    if index is None:
        return {"ok": False, "error": "meilisearch_unavailable", "hits": []}
    lim = max(1, min(int(limit or 20), 100))
    try:
        result = index.search(q, {"limit": lim})
        hits = []
        for h in result.get("hits", []):
            hits.append({
                "id": h.get("id"),
                "text": (h.get("text") or "")[:2000],
                "tags": h.get("tags"),
                "score": h.get("_rankingScore"),
            })
        return {"ok": True, "hits": hits}
    except Exception as e:
        logger.warning("meilisearch search failed: %s", e)
        return {"ok": False, "error": str(e), "hits": []}


def delete_learning(cfg: dict[str, Any], rid: int) -> None:
    """Delete a learning from Meilisearch by ID."""
    if not cfg.get("meilisearch_enabled"):
        return
    index = _get_index(cfg)
    if index is None:
        return
    try:
        index.delete_document(rid)
    except Exception as e:
        logger.warning("meilisearch delete failed for id=%s: %s", rid, e)


def get_stats(cfg: dict[str, Any]) -> dict[str, Any]:
    """Get index statistics from Meilisearch."""
    index = _get_index(cfg)
    if index is None:
        return {"available": False}
    try:
        stats = index.get_stats()
        return {
            "available": True,
            "number_of_documents": stats.get("numberOfDocuments", 0),
            "is_indexing": stats.get("isIndexing", False),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}

"""
Unified search router — routes full-text search to the best available backend.

Priority: Meilisearch → Elasticsearch → SQLite FTS5 (always available).

Auto-failover: if the configured backend is unreachable, falls back to the next
healthy backend. SQLite FTS5 is always the last resort (no external dependency).

Config keys:
  search_backend: "auto" | "meilisearch" | "elasticsearch" | "sqlite_fts"
  meilisearch_enabled: bool
  elasticsearch_enabled: bool
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla")

_BACKENDS = ("meilisearch", "elasticsearch", "sqlite_fts")


def _detect_backend(cfg: dict) -> str:
    """Detect which search backend to use."""
    explicit = str(cfg.get("search_backend", "auto")).strip().lower()
    if explicit in _BACKENDS:
        return explicit

    # Auto-detect: prefer Meilisearch → Elasticsearch → SQLite
    if cfg.get("meilisearch_enabled"):
        return "meilisearch"
    if cfg.get("elasticsearch_enabled"):
        return "elasticsearch"
    return "sqlite_fts"


def _search_meilisearch(cfg: dict, query: str, limit: int) -> dict[str, Any]:
    """Search via Meilisearch."""
    from services.meilisearch_bridge import search_learnings
    return search_learnings(cfg, query, limit=limit)


def _search_elasticsearch(cfg: dict, query: str, limit: int) -> dict[str, Any]:
    """Search via Elasticsearch."""
    from services.elasticsearch_bridge import search_learnings
    return search_learnings(cfg, query, limit=limit)


def _search_sqlite_fts(cfg: dict, query: str, limit: int) -> dict[str, Any]:
    """Search via SQLite FTS5 (always available, no external deps)."""
    try:
        from layla.memory.db import search_learnings_fts
        results = search_learnings_fts(query, limit=limit)
        return {"ok": True, "hits": results, "backend": "sqlite_fts"}
    except ImportError:
        # FTS function not available — fallback to LIKE search
        return _search_sqlite_like(cfg, query, limit)
    except Exception as e:
        return _search_sqlite_like(cfg, query, limit)


def _search_sqlite_like(cfg: dict, query: str, limit: int) -> dict[str, Any]:
    """Fallback: simple LIKE search on SQLite learnings table."""
    try:
        from layla.memory.db import get_db
        db = get_db()
        if db is None:
            return {"ok": False, "error": "no database", "hits": []}
        # Sanitize query for LIKE
        safe_q = query.replace("%", "").replace("_", "").strip()
        if not safe_q:
            return {"ok": True, "hits": []}
        cursor = db.execute(
            "SELECT rowid, content, tags FROM learnings WHERE content LIKE ? LIMIT ?",
            (f"%{safe_q}%", limit),
        )
        hits = []
        for row in cursor:
            hits.append({
                "id": row[0],
                "text": (row[1] or "")[:2000],
                "tags": row[2] or "",
                "score": None,
            })
        return {"ok": True, "hits": hits, "backend": "sqlite_like"}
    except Exception as e:
        return {"ok": False, "error": str(e), "hits": []}


def search(
    query: str,
    *,
    limit: int = 20,
    cfg: dict | None = None,
    backend_override: str | None = None,
) -> dict[str, Any]:
    """
    Search learnings using the best available backend.

    Returns: {"ok": bool, "hits": list, "backend": str, "error"?: str}
    """
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}

    backend = backend_override or _detect_backend(cfg)

    # Try primary backend
    result = _try_backend(backend, cfg, query, limit)
    if result["ok"]:
        result["backend"] = backend
        return result

    # Failover: try remaining backends in priority order
    tried = {backend}
    for fallback in _BACKENDS:
        if fallback in tried:
            continue
        tried.add(fallback)
        logger.info("search_router: %s failed, trying %s", backend, fallback)
        result = _try_backend(fallback, cfg, query, limit)
        if result["ok"]:
            result["backend"] = fallback
            result["failover"] = True
            return result

    # All failed
    return {"ok": False, "error": "All search backends failed", "hits": [], "backend": "none"}


def _try_backend(backend: str, cfg: dict, query: str, limit: int) -> dict[str, Any]:
    """Try a specific search backend. Returns result dict."""
    try:
        if backend == "meilisearch":
            return _search_meilisearch(cfg, query, limit)
        elif backend == "elasticsearch":
            return _search_elasticsearch(cfg, query, limit)
        else:
            return _search_sqlite_fts(cfg, query, limit)
    except Exception as e:
        return {"ok": False, "error": str(e), "hits": []}


def get_search_status(cfg: dict | None = None) -> dict[str, Any]:
    """Get status of all search backends."""
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}

    status = {
        "active_backend": _detect_backend(cfg),
        "backends": {},
    }

    # Meilisearch
    if cfg.get("meilisearch_enabled"):
        try:
            from services.meilisearch_bridge import is_available, get_stats
            status["backends"]["meilisearch"] = {
                "enabled": True,
                "available": is_available(cfg),
                "stats": get_stats(cfg),
            }
        except Exception as e:
            status["backends"]["meilisearch"] = {"enabled": True, "available": False, "error": str(e)}
    else:
        status["backends"]["meilisearch"] = {"enabled": False}

    # Elasticsearch
    if cfg.get("elasticsearch_enabled"):
        try:
            from services.elasticsearch_bridge import client_from_config
            client = client_from_config(cfg)
            status["backends"]["elasticsearch"] = {
                "enabled": True,
                "available": client is not None,
            }
        except Exception as e:
            status["backends"]["elasticsearch"] = {"enabled": True, "available": False, "error": str(e)}
    else:
        status["backends"]["elasticsearch"] = {"enabled": False}

    # SQLite FTS (always available)
    status["backends"]["sqlite_fts"] = {"enabled": True, "available": True}

    return status


def index_learning(
    cfg: dict,
    *,
    rid: int,
    text: str,
    tags: str | None = None,
    source: str | None = None,
) -> None:
    """Index a learning to all enabled backends (fan-out)."""
    if cfg.get("meilisearch_enabled"):
        try:
            from services.meilisearch_bridge import index_learning as ms_index
            ms_index(cfg, rid=rid, text=text, tags=tags, source=source)
        except Exception as e:
            logger.debug("search_router: meilisearch index failed: %s", e)

    if cfg.get("elasticsearch_enabled"):
        try:
            from services.elasticsearch_bridge import index_learning as es_index
            es_index(cfg, rid=rid, text=text, tags=tags, source=source)
        except Exception as e:
            logger.debug("search_router: elasticsearch index failed: %s", e)

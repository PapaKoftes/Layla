"""Optional Elasticsearch mirror for learnings (keyword search / ELK)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

_ES_WARNED: set[str] = set()


def _warn_es_once(key: str, msg: str) -> None:
    if key in _ES_WARNED:
        return
    _ES_WARNED.add(key)
    logger.warning(msg)


def client_from_config(cfg: dict[str, Any]) -> Any | None:
    if not cfg.get("elasticsearch_enabled"):
        return None
    url = str(cfg.get("elasticsearch_url") or "").strip()
    if not url:
        _warn_es_once(
            "es_no_url",
            "elasticsearch_enabled is true but elasticsearch_url is empty; ES indexing and search are disabled.",
        )
        return None
    try:
        from elasticsearch import Elasticsearch  # type: ignore
    except ImportError:
        _warn_es_once(
            "es_no_pkg",
            "elasticsearch_enabled is true but the elasticsearch package is not installed; run: pip install elasticsearch",
        )
        return None
    api_key = cfg.get("elasticsearch_api_key")
    ak = str(api_key).strip() if api_key else None
    kwargs: dict[str, Any] = {"hosts": [url]}
    if ak:
        kwargs["api_key"] = ak
    return Elasticsearch(**kwargs)


def index_learning(
    cfg: dict[str, Any],
    *,
    rid: int,
    text: str,
    tags: str | None = None,
    source: str | None = None,
) -> None:
    if not cfg.get("elasticsearch_enabled"):
        return
    es = client_from_config(cfg)
    if es is None:
        return
    prefix = str(cfg.get("elasticsearch_index_prefix") or "layla").strip() or "layla"
    index = f"{prefix}-learnings"
    doc = {
        "id": rid,
        "text": text or "",
        "tags": tags or "",
        "source": source or "learning",
    }
    try:
        es.index(index=index, id=str(rid), document=doc, refresh=False)
    except Exception as e:
        logger.warning("elasticsearch index failed for learning id=%s (SQLite/Chroma unchanged): %s", rid, e)


def search_learnings(cfg: dict[str, Any], q: str, limit: int = 20) -> dict[str, Any]:
    if not cfg.get("elasticsearch_enabled"):
        return {"ok": False, "error": "elasticsearch_disabled", "hits": []}
    es = client_from_config(cfg)
    if es is None:
        return {"ok": False, "error": "elasticsearch_unavailable", "hits": []}
    prefix = str(cfg.get("elasticsearch_index_prefix") or "layla").strip() or "layla"
    index = f"{prefix}-learnings"
    lim = max(1, min(int(limit or 20), 100))
    try:
        query = {
            "multi_match": {
                "query": q,
                "fields": ["text", "tags"],
            }
        }
        try:
            resp = es.search(index=index, query=query, size=lim)
        except TypeError:
            resp = es.search(index=index, body={"query": query, "size": lim})
        hits = []
        for h in resp.get("hits", {}).get("hits", []) or []:
            src = h.get("_source") or {}
            hits.append(
                {
                    "id": src.get("id"),
                    "text": (src.get("text") or "")[:2000],
                    "tags": src.get("tags"),
                    "score": h.get("_score"),
                }
            )
        return {"ok": True, "hits": hits}
    except Exception as e:
        logger.warning("elasticsearch search failed: %s", e)
        return {"ok": False, "error": str(e), "hits": []}

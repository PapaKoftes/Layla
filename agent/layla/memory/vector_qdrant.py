"""
Qdrant vector store adapter -- alternative to ChromaDB.

Better filtering, persistence, and scaling. Uses qdrant-client SDK.

Config keys:
  vector_backend: "chroma" | "qdrant" (default "chroma")
  qdrant_url: str (default "http://localhost:6333")
  qdrant_api_key: str (optional)
  qdrant_collection: str (default "layla-memories")
"""

import logging
import threading
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Module-level cached client (thread-safe)
# ---------------------------------------------------------------------------
_client: Any | None = None
_client_lock = threading.Lock()

_DEFAULT_URL = "http://localhost:6333"
_DEFAULT_COLLECTION = "layla-memories"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_url(cfg: dict | None) -> str:
    """Extract the Qdrant URL from config, falling back to the default."""
    return str((cfg or {}).get("qdrant_url") or _DEFAULT_URL).strip()


def _cfg_collection(cfg: dict | None) -> str:
    """Extract the collection name from config, falling back to the default."""
    return str((cfg or {}).get("qdrant_collection") or _DEFAULT_COLLECTION).strip()


def _cfg_api_key(cfg: dict | None) -> str | None:
    """Extract the optional API key from config."""
    key = (cfg or {}).get("qdrant_api_key")
    if key and str(key).strip():
        return str(key).strip()
    return None


# ---------------------------------------------------------------------------
# 1. is_available
# ---------------------------------------------------------------------------

def is_available(cfg: dict | None = None) -> bool:
    """Check whether qdrant-client is importable AND the server is reachable.

    Returns ``True`` only when both conditions are met; ``False`` otherwise.
    Never raises.
    """
    try:
        from qdrant_client import QdrantClient  # noqa: F401
    except ImportError:
        logger.debug("vector_qdrant: qdrant-client package not installed")
        return False

    try:
        url = _cfg_url(cfg)
        probe = QdrantClient(url=url, api_key=_cfg_api_key(cfg), timeout=5)
        # A lightweight RPC that confirms the server is alive
        probe.get_collections()
        return True
    except Exception as exc:
        logger.debug("vector_qdrant: server unreachable at %s -- %s", _cfg_url(cfg), exc)
        return False


# ---------------------------------------------------------------------------
# 2. get_client
# ---------------------------------------------------------------------------

def get_client(cfg: dict) -> Any | None:
    """Create or return a cached ``QdrantClient`` instance.

    The client is stored at module level and protected by a lock so that
    concurrent callers share the same connection.  Returns ``None`` if the
    SDK is not importable or the client cannot be created.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        # Double-check after acquiring the lock
        if _client is not None:
            return _client
        try:
            from qdrant_client import QdrantClient

            url = _cfg_url(cfg)
            api_key = _cfg_api_key(cfg)
            _client = QdrantClient(url=url, api_key=api_key)
            logger.info("vector_qdrant: connected to %s", url)
            return _client
        except ImportError:
            logger.warning("vector_qdrant: qdrant-client is not installed")
            return None
        except Exception as exc:
            logger.warning("vector_qdrant: failed to create client -- %s", exc)
            return None


# ---------------------------------------------------------------------------
# 3. ensure_collection
# ---------------------------------------------------------------------------

def ensure_collection(cfg: dict, vector_size: int = 384) -> bool:
    """Create the target collection if it does not already exist (idempotent).

    Uses cosine distance as the similarity metric.  Returns ``True`` when the
    collection exists (either pre-existing or freshly created), ``False`` on
    any error.
    """
    try:
        from qdrant_client.models import Distance, VectorParams

        client = get_client(cfg)
        if client is None:
            return False

        collection_name = _cfg_collection(cfg)
        existing = [c.name for c in client.get_collections().collections]
        if collection_name in existing:
            logger.debug("vector_qdrant: collection '%s' already exists", collection_name)
            return True

        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        logger.info(
            "vector_qdrant: created collection '%s' (dim=%d, cosine)",
            collection_name,
            vector_size,
        )
        return True
    except Exception as exc:
        logger.warning("vector_qdrant: ensure_collection failed -- %s", exc)
        return False


# ---------------------------------------------------------------------------
# 4. add_memories
# ---------------------------------------------------------------------------

def add_memories(cfg: dict, memories: list[dict]) -> dict:
    """Upsert a batch of memories into the Qdrant collection.

    Each element of *memories* must contain:
      - ``id``        (str)         -- unique point identifier
      - ``text``      (str)         -- the text payload
      - ``embedding`` (list[float]) -- the vector
      - ``metadata``  (dict)        -- arbitrary key/value metadata

    Returns ``{"ok": True, "count": N}`` on success, or
    ``{"ok": False, "count": 0, "error": "..."}`` on failure.
    """
    if not memories:
        return {"ok": True, "count": 0}

    try:
        from qdrant_client.models import PointStruct

        client = get_client(cfg)
        if client is None:
            return {"ok": False, "count": 0, "error": "client unavailable"}

        collection_name = _cfg_collection(cfg)

        points = []
        for mem in memories:
            mid = mem.get("id")
            text = mem.get("text", "")
            embedding = mem.get("embedding")
            metadata = mem.get("metadata") or {}

            if mid is None or embedding is None:
                logger.debug("vector_qdrant: skipping memory with missing id or embedding")
                continue

            payload = dict(metadata)
            payload["text"] = text

            points.append(
                PointStruct(
                    id=mid,
                    vector=list(embedding),
                    payload=payload,
                )
            )

        if not points:
            return {"ok": True, "count": 0}

        client.upsert(collection_name=collection_name, points=points)
        logger.debug("vector_qdrant: upserted %d points into '%s'", len(points), collection_name)
        return {"ok": True, "count": len(points)}

    except Exception as exc:
        logger.warning("vector_qdrant: add_memories failed -- %s", exc)
        return {"ok": False, "count": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# 5. search_memories
# ---------------------------------------------------------------------------

def search_memories(
    cfg: dict,
    embedding: list[float],
    *,
    limit: int = 10,
    filters: dict | None = None,
) -> list[dict]:
    """Search for the nearest memories by vector similarity.

    Parameters
    ----------
    cfg : dict
        Runtime configuration (qdrant_url, qdrant_collection, etc.).
    embedding : list[float]
        The query vector.
    limit : int
        Maximum number of results to return (default 10).
    filters : dict | None
        Optional metadata filter.  Keys are metadata field names and values
        are the required match values.  All conditions are AND-ed together.
        Example: ``{"type": "fact", "domain": "coding"}``

    Returns
    -------
    list[dict]
        Each element: ``{"id": str, "text": str, "score": float, "metadata": dict}``
        Sorted by descending score.  Returns ``[]`` on any error.
    """
    try:
        client = get_client(cfg)
        if client is None:
            return []

        collection_name = _cfg_collection(cfg)

        query_filter = None
        if filters:
            try:
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                    if v is not None
                ]
                if conditions:
                    query_filter = Filter(must=conditions)
            except Exception as fexc:
                logger.debug("vector_qdrant: filter construction failed -- %s", fexc)

        results = client.search(
            collection_name=collection_name,
            query_vector=list(embedding),
            limit=limit,
            query_filter=query_filter,
        )

        out: list[dict] = []
        for hit in results:
            payload = hit.payload or {}
            text = payload.pop("text", "")
            out.append({
                "id": str(hit.id),
                "text": text,
                "score": float(hit.score),
                "metadata": payload,
            })
        return out

    except Exception as exc:
        logger.warning("vector_qdrant: search_memories failed -- %s", exc)
        return []


# ---------------------------------------------------------------------------
# 6. delete_memories
# ---------------------------------------------------------------------------

def delete_memories(cfg: dict, ids: list[str]) -> dict:
    """Delete points by their IDs.

    Returns ``{"ok": True, "count": N}`` where *N* is the number of IDs
    that were requested for deletion, or ``{"ok": False, "count": 0}`` on
    error.
    """
    if not ids:
        return {"ok": True, "count": 0}

    try:
        from qdrant_client.models import PointIdsList

        client = get_client(cfg)
        if client is None:
            return {"ok": False, "count": 0}

        collection_name = _cfg_collection(cfg)

        client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=list(ids)),
        )
        logger.debug("vector_qdrant: deleted %d points from '%s'", len(ids), collection_name)
        return {"ok": True, "count": len(ids)}

    except Exception as exc:
        logger.warning("vector_qdrant: delete_memories failed -- %s", exc)
        return {"ok": False, "count": 0}


# ---------------------------------------------------------------------------
# 7. get_stats
# ---------------------------------------------------------------------------

def get_stats(cfg: dict) -> dict:
    """Return basic statistics about the Qdrant collection.

    Returns a dict with keys:
      - ``available``     (bool) -- whether the collection is reachable
      - ``collection``    (str)  -- the collection name
      - ``vectors_count`` (int)  -- number of vectors stored
      - ``points_count``  (int)  -- number of points stored
    """
    collection_name = _cfg_collection(cfg)
    base = {
        "available": False,
        "collection": collection_name,
        "vectors_count": 0,
        "points_count": 0,
    }
    try:
        client = get_client(cfg)
        if client is None:
            return base

        info = client.get_collection(collection_name=collection_name)
        base["available"] = True
        base["vectors_count"] = int(info.vectors_count or 0)
        base["points_count"] = int(info.points_count or 0)
        return base

    except Exception as exc:
        logger.debug("vector_qdrant: get_stats failed -- %s", exc)
        return base

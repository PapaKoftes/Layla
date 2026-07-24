"""
graph.py — READ-ONLY REST API over the personal knowledge graph.

The graph itself is `layla/memory/memory_graph.py`: a NetworkX DiGraph persisted to
`knowledge_graph.graphml`. `add_node()` writes an entity (label + JSON metadata +
created_at) and auto-links it to semantically similar existing entities with a
`similar_to` edge; `add_edge()` writes an explicit typed relationship. Everything
written there was invisible to the user — nothing served it. This router is that
missing read path.

Exposes:
  /graph/stats             GET — counts, relation histogram, most-connected + newest entities
  /graph/entities          GET — paged, searchable entity list (newest first)
  /graph/entity/{id}       GET — one entity plus its incoming/outgoing relationships

NO MUTATION ENDPOINTS. Entities are created by the memory pipeline (learnings,
consolidation, conversation entity extraction), not by the viewer. A write path here
would let the UI plant facts that then re-enter the prompt as if Layla had learned
them — the exact failure mode `.planning` calls "planted test data".
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")
router = APIRouter(prefix="/graph", tags=["graph"])

# The store keeps the whole graph in one GraphML file, so every read is a full parse.
# Cap what a single request can ask for rather than letting a client stream the lot.
_MAX_LIMIT = 200
_MAX_QUERY = 200

_UNLABELLED = "(unlabelled)"


def _unavailable(what: str) -> JSONResponse:
    """A generic 500. Never echo the exception — main.py's handler is sanitized for the
    same reason (a traceback / internal path in the body is info disclosure)."""
    logger.exception("graph %s failed", what)
    return JSONResponse(
        {"ok": False, "error": "knowledge graph unavailable", "detail": None},
        status_code=500,
    )


def _parse_metadata(raw: Any) -> dict[str, Any]:
    """GraphML stores node metadata as a JSON *string*. Return it as a dict, never raise."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {}


def _snapshot() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """(nodes_by_id, edges) read from the live graph.

    Node ids are returned as STRINGS because that is what the GraphML store actually
    holds — `load_graph()` coerces them to ints and falls back to a positional index for
    non-numeric ids, which would hand out ids that do not round-trip back to an entity.
    """
    from layla.memory.memory_graph import _get_graph

    graph = _get_graph()
    nodes: dict[str, dict[str, Any]] = {}
    for nid in graph.nodes():
        data = graph.nodes.get(nid, {}) or {}
        key = str(nid)
        nodes[key] = {
            "id": key,
            "label": str(data.get("label") or ""),
            "metadata": _parse_metadata(data.get("metadata")),
            "created_at": str(data.get("created_at") or ""),
        }
    edges: list[dict[str, Any]] = []
    for src, dst, attrs in graph.edges(data=True):
        edges.append({
            "src": str(src),
            "dst": str(dst),
            "relation": str((attrs or {}).get("relation") or ""),
        })
    return nodes, edges


def _degrees(edges: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in edges:
        out[e["src"]] = out.get(e["src"], 0) + 1
        out[e["dst"]] = out.get(e["dst"], 0) + 1
    return out


def _newest_first(node: dict[str, Any]) -> tuple[str, int]:
    """Sort key: created_at desc, then numeric id desc. Nodes migrated from the legacy
    JSON store carry no created_at, so the id is the tie-break that keeps order stable."""
    nid = node["id"]
    return (node["created_at"], int(nid) if nid.isdigit() else 0)


def _matches(node: dict[str, Any], needle: str) -> bool:
    if node["label"].lower().find(needle) >= 0:
        return True
    for key, value in (node["metadata"] or {}).items():
        if str(key).lower().find(needle) >= 0 or str(value).lower().find(needle) >= 0:
            return True
    return False


# ── /graph/stats ──────────────────────────────────────────────────────────────

@router.get("/stats")
def graph_stats(top: int = Query(10, ge=1, le=50, description="How many entities per top-list")):
    """
    Summary of the whole knowledge graph: entity/relationship counts, how many
    relationships of each type exist, which entities are most connected, and which
    were learned most recently. `isolated_count` is the number of entities with no
    relationship at all — a high value means the auto-linker is not connecting.
    """
    try:
        nodes, edges = _snapshot()
        degrees = _degrees(edges)

        relation_counts: dict[str, int] = {}
        for e in edges:
            key = e["relation"] or _UNLABELLED
            relation_counts[key] = relation_counts.get(key, 0) + 1

        by_degree = sorted(
            nodes.values(),
            key=lambda n: (degrees.get(n["id"], 0), _newest_first(n)),
            reverse=True,
        )
        newest = sorted(nodes.values(), key=_newest_first, reverse=True)

        return {
            "ok": True,
            "entity_count": len(nodes),
            "relationship_count": len(edges),
            "isolated_count": sum(1 for nid in nodes if degrees.get(nid, 0) == 0),
            "relation_counts": [
                {"relation": r, "count": c}
                for r, c in sorted(relation_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "most_connected": [
                {"id": n["id"], "label": n["label"], "degree": degrees.get(n["id"], 0)}
                for n in by_degree[:top]
                if degrees.get(n["id"], 0) > 0
            ],
            "newest": [
                {"id": n["id"], "label": n["label"], "created_at": n["created_at"]}
                for n in newest[:top]
            ],
        }
    except Exception:
        return _unavailable("stats")


# ── /graph/entities ───────────────────────────────────────────────────────────

@router.get("/entities")
def graph_entities(
    q: str = Query("", description="Case-insensitive substring match over label and metadata"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """
    Paged list of entities, newest first. `total` is the size of the whole graph;
    `matched` is how many survived the `q` filter (so the client can page through
    search results without re-counting).
    """
    try:
        nodes, edges = _snapshot()
        degrees = _degrees(edges)

        relations_by_node: dict[str, list[str]] = {}
        for e in edges:
            rel = e["relation"] or _UNLABELLED
            for side in (e["src"], e["dst"]):
                bucket = relations_by_node.setdefault(side, [])
                if rel not in bucket:
                    bucket.append(rel)

        needle = (q or "").strip().lower()[:_MAX_QUERY]
        selected = [n for n in nodes.values() if not needle or _matches(n, needle)]
        selected.sort(key=_newest_first, reverse=True)
        page = selected[offset: offset + limit]

        return {
            "ok": True,
            "total": len(nodes),
            "matched": len(selected),
            "limit": limit,
            "offset": offset,
            "query": needle,
            "entities": [
                {
                    "id": n["id"],
                    "label": n["label"],
                    "created_at": n["created_at"],
                    "metadata": n["metadata"],
                    "degree": degrees.get(n["id"], 0),
                    "relations": relations_by_node.get(n["id"], []),
                }
                for n in page
            ],
        }
    except Exception:
        return _unavailable("entities")


# ── /graph/entity/{entity_id} ─────────────────────────────────────────────────

@router.get("/entity/{entity_id}")
def graph_entity(entity_id: str):
    """
    One entity with every relationship it takes part in, split by direction.
    404 when the id is not in the graph — an unknown id is a client error, not an
    empty result (returning `{}` here is how a dead link stays invisible).
    """
    try:
        nodes, edges = _snapshot()
        node = nodes.get(str(entity_id))
        if node is None:
            raise HTTPException(status_code=404, detail=f"entity {entity_id} not found")

        outgoing: list[dict[str, Any]] = []
        incoming: list[dict[str, Any]] = []
        for e in edges:
            if e["src"] == node["id"]:
                other = nodes.get(e["dst"])
                outgoing.append({
                    "id": e["dst"],
                    "label": (other or {}).get("label", ""),
                    "relation": e["relation"],
                })
            if e["dst"] == node["id"]:
                other = nodes.get(e["src"])
                incoming.append({
                    "id": e["src"],
                    "label": (other or {}).get("label", ""),
                    "relation": e["relation"],
                })

        return {
            "ok": True,
            "entity": node,
            "outgoing": outgoing,
            "incoming": incoming,
            "relationship_count": len(outgoing) + len(incoming),
            "neighbor_count": len({r["id"] for r in outgoing + incoming}),
        }
    except HTTPException:
        raise
    except Exception:
        return _unavailable("entity detail")

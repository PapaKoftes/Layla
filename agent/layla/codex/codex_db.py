"""
codex_db.py — CRUD operations for the personal knowledge codex.

Wraps the existing SQLite entity/relationship tables (created by
layla/memory/migrations.py) behind a clean functional API.

All DB access goes through `layla.memory.db_connection._conn()`.
For entity upsert with merge semantics, delegates to
`services.memory_router.upsert_entity` to avoid duplicating logic.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("layla.codex")


# ── helpers ──────────────────────────────────────────────────────────────────

def _conn():
    """Lazy import of the shared SQLite connection factory."""
    from layla.memory.db_connection import _conn as conn_factory
    return conn_factory()


def _ensure_tables():
    """Run migrations if they haven't been applied yet in this process."""
    try:
        from layla.memory.migrations import migrate
        migrate()
    except Exception:
        pass  # Tables may already exist; queries will fail clearly if not.


def _row_to_entity_dict(row) -> dict:
    """Convert a sqlite3.Row from the entities table to a plain dict,
    deserialising JSON columns."""
    d = dict(row)
    for col in ("aliases", "tags", "attributes"):
        raw = d.get(col)
        if isinstance(raw, str):
            try:
                d[col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[col] = []
    return d


def _row_to_rel_dict(row) -> dict:
    """Convert a sqlite3.Row from the relationships table to a plain dict."""
    d = dict(row)
    d["bidirectional"] = bool(d.get("bidirectional", 0))
    return d


# ── Entity CRUD ──────────────────────────────────────────────────────────────

def upsert_entity(
    entity_type: str,
    canonical_name: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
    confidence: float = 0.5,
    source: str = "",
    aliases: list[str] | None = None,
) -> dict:
    """
    Create or update an entity in the codex.

    Delegates to ``services.memory_router.upsert_entity`` for merge semantics
    (union aliases/tags, keep higher-confidence description).

    Returns the entity dict as stored, or an empty dict on failure.
    """
    _ensure_tables()

    from schemas.entity import Entity

    canonical = canonical_name.strip().lower()
    entity = Entity(
        type=entity_type,
        canonical_name=canonical,
        description=description,
        tags=tags or [],
        confidence=confidence,
        source=source,
        aliases=aliases if aliases is not None else [canonical_name.strip()],
    )

    from services.memory_router import upsert_entity as _router_upsert
    ok = _router_upsert(entity)
    if not ok:
        return {}

    # Read back the stored record to return the merged state.
    return get_entity(entity.id) or entity.to_dict()


def get_entity(entity_id: str) -> dict | None:
    """Retrieve an entity by its ID. Returns None if not found."""
    _ensure_tables()
    try:
        with _conn() as db:
            row = db.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if row:
                return _row_to_entity_dict(row)
    except Exception as exc:
        logger.debug("codex_db.get_entity failed: %s", exc)
    return None


def search_entities(
    query: str,
    *,
    entity_type: str | None = None,
    min_confidence: float = 0.3,
    limit: int = 20,
) -> list[dict]:
    """
    Search entities by name, description, or alias text.

    Performs a case-insensitive LIKE search on canonical_name, description,
    and the serialised aliases JSON column.
    """
    _ensure_tables()
    results: list[dict] = []
    try:
        pattern = f"%{query.strip().lower()}%"
        sql = """
            SELECT * FROM entities
            WHERE (LOWER(canonical_name) LIKE ?
                   OR LOWER(description) LIKE ?
                   OR LOWER(aliases) LIKE ?)
              AND confidence >= ?
        """
        params: list[Any] = [pattern, pattern, pattern, min_confidence]

        if entity_type:
            sql += " AND type = ?"
            params.append(entity_type)

        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        with _conn() as db:
            rows = db.execute(sql, params).fetchall()
            results = [_row_to_entity_dict(r) for r in rows]
    except Exception as exc:
        logger.debug("codex_db.search_entities failed: %s", exc)
    return results


def get_entity_graph(entity_id: str, depth: int = 2) -> dict:
    """
    Return the N-hop neighbourhood of an entity as a graph dict:
        {"nodes": [...], "edges": [...]}

    Each node is an entity dict; each edge is a relationship dict.
    BFS expands outward from *entity_id* up to *depth* hops.
    """
    _ensure_tables()
    nodes_map: dict[str, dict] = {}
    edges: list[dict] = []
    frontier = {entity_id}
    visited: set[str] = set()

    try:
        with _conn() as db:
            for _ in range(depth):
                if not frontier:
                    break
                next_frontier: set[str] = set()
                for eid in frontier:
                    if eid in visited:
                        continue
                    visited.add(eid)

                    # Fetch the node itself
                    if eid not in nodes_map:
                        row = db.execute(
                            "SELECT * FROM entities WHERE id = ?", (eid,)
                        ).fetchone()
                        if row:
                            nodes_map[eid] = _row_to_entity_dict(row)

                    # Fetch relationships
                    rels = db.execute("""
                        SELECT * FROM relationships
                        WHERE from_entity = ? OR to_entity = ?
                    """, (eid, eid)).fetchall()

                    for rel in rels:
                        edge = _row_to_rel_dict(rel)
                        edges.append(edge)
                        # Expand to the other end
                        other = edge["to_entity"] if edge["from_entity"] == eid else edge["from_entity"]
                        if other not in visited:
                            next_frontier.add(other)

                frontier = next_frontier

            # Load nodes discovered in the final frontier (neighbours of
            # the last expanded ring) so the graph includes them even
            # though they themselves were not expanded.
            for nid in frontier | visited:
                if nid not in nodes_map:
                    row = db.execute(
                        "SELECT * FROM entities WHERE id = ?", (nid,)
                    ).fetchone()
                    if row:
                        nodes_map[nid] = _row_to_entity_dict(row)

    except Exception as exc:
        logger.debug("codex_db.get_entity_graph failed: %s", exc)

    # Deduplicate edges by id
    seen_edge_ids: set[str] = set()
    unique_edges: list[dict] = []
    for e in edges:
        eid = e.get("id", "")
        if eid not in seen_edge_ids:
            seen_edge_ids.add(eid)
            unique_edges.append(e)

    return {"nodes": list(nodes_map.values()), "edges": unique_edges}


# ── Relationship CRUD ────────────────────────────────────────────────────────

def link_entities(
    from_id: str,
    to_id: str,
    rel_type: str,
    *,
    weight: float = 0.5,
    evidence: str = "",
) -> dict:
    """
    Create or replace a relationship between two entities.

    Delegates to ``services.memory_router.upsert_relationship`` for
    consistent write-path handling.

    Returns the relationship dict, or empty dict on failure.
    """
    _ensure_tables()

    from schemas.entity import Relationship
    from services.memory_router import upsert_relationship as _router_upsert_rel

    rel = Relationship(
        from_entity=from_id,
        to_entity=to_id,
        type=rel_type,
        weight=weight,
        evidence=evidence,
    )
    ok = _router_upsert_rel(rel)
    if not ok:
        return {}
    return rel.to_dict()


def get_entity_relationships(entity_id: str) -> list[dict]:
    """
    Return all relationships where *entity_id* appears as either endpoint.

    Delegates to ``services.memory_router.get_entity_relationships`` which
    already joins entity names for readability.
    """
    _ensure_tables()
    from services.memory_router import get_entity_relationships as _router_get_rels
    return _router_get_rels(entity_id)


# ── Aggregates ───────────────────────────────────────────────────────────────

def count_entities(entity_type: str | None = None) -> int:
    """Count entities in the codex, optionally filtered by type."""
    _ensure_tables()
    try:
        with _conn() as db:
            if entity_type:
                row = db.execute(
                    "SELECT COUNT(*) FROM entities WHERE type = ?",
                    (entity_type,),
                ).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) FROM entities").fetchone()
            return row[0] if row else 0
    except Exception as exc:
        logger.debug("codex_db.count_entities failed: %s", exc)
        return 0


def list_entity_types() -> list[str]:
    """Return the distinct entity types currently stored in the codex."""
    _ensure_tables()
    try:
        with _conn() as db:
            rows = db.execute(
                "SELECT DISTINCT type FROM entities ORDER BY type"
            ).fetchall()
            return [r[0] for r in rows]
    except Exception as exc:
        logger.debug("codex_db.list_entity_types failed: %s", exc)
        return []

"""
memory_router.py — Single interface for all Layla memory operations.

THE MEMORY ROUTER IS THE GATEKEEPER.
All reads and writes to any memory store go through here.
This prevents fragmentation, ensures deduplication, and maintains coherence.

Stores managed:
  SQLite (structured)  — entities, relationships, learnings, conversations
  ChromaDB (semantic)  — embeddings for semantic/fuzzy recall
  NetworkX (graph)     — entity relationships for graph traversal
  Knowledge/ dir       — KB articles (JSON/Markdown files)

Query routing logic:
  factual/exact → SQLite entities table
  semantic/fuzzy → ChromaDB vector search
  relational → NetworkX graph traversal
  recent/episodic → SQLite conversations
  document-level → knowledge/_generated/_index.json

Write routing:
  Always write to ALL relevant stores simultaneously.
  Use entity ID as cross-store key to enable deduplication.

Config:
  memory_router_enabled    bool   (default true)
  memory_router_log_writes bool   (default false; set true to audit every write)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from schemas.entity import Entity, Relationship

logger = logging.getLogger("layla")

_AGENT_DIR = Path(__file__).resolve().parent.parent


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class MemoryResult:
    """Unified result from any memory store."""
    id: str
    content: str
    type: str           # entity type or "learning" or "conversation" or "article"
    score: float        # Relevance score 0.0-1.0
    source: str         # Which store this came from
    metadata: dict      # Original record data


# ── Config ─────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    # Delegates to services.config_cache for mtime-invalidated single-source loader.
    try:
        from services.infrastructure.config_cache import get_config
        return get_config()
    except Exception:
        return {}


# ── Pass-through write helpers ────────────────────────────────────────────────
# These exist so all writers can import memory_router as the canonical write
# chokepoint. Internally they delegate to the same SQLite helpers writers used
# directly before; the router becomes the registered chokepoint that
# scripts/check_wiring.py asserts against.

def save_learning(content: str, kind: str = "general", **kwargs: Any) -> int:
    """Pass-through to layla.memory.db.save_learning (canonical write path).

    Returns the learning row id on success, or -1 if filtered/rate-limited.
    """
    from layla.memory.db import save_learning as _save_learning
    try:
        from services.observability.prom_metrics import record_memory_op
        record_memory_op("episodic", "save_learning")
    except Exception:
        pass
    return _save_learning(content=content, kind=kind, **kwargs)


def save_aspect_memory(aspect_id: str, content: str, **kwargs: Any) -> Any:
    """Pass-through to layla.memory.db.save_aspect_memory."""
    from layla.memory.db import save_aspect_memory as _sam
    return _sam(aspect_id, content, **kwargs)


def save_outcome(content: str, **kwargs: Any) -> int:
    """Pass-through write for outcome-style learnings.

    Returns the learning row id on success, or -1 if filtered/rate-limited.
    """
    return save_learning(content=content, kind="outcome", **kwargs)


def _enabled() -> bool:
    return bool(_cfg().get("memory_router_enabled", True))


# ── Read helpers (Phase 3 — canonical read paths) ─────────────────────────────
# These wrap the most commonly used db read functions so callers can import
# from memory_router instead of bypassing to layla.memory.db directly.

def get_recent_learnings(n: int = 20, **kwargs: Any) -> list[dict]:
    """Read the N most recent learnings (newest first)."""
    try:
        from layla.memory.db import get_recent_learnings as _grl
        return _grl(n=n, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: get_recent_learnings failed: %s", exc)
        return []


def search_learnings_fts(query: str, limit: int = 20, **kwargs: Any) -> list[dict]:
    """Full-text search over learnings."""
    try:
        from layla.memory.db import search_learnings_fts as _slf
        return _slf(query, limit=limit, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: search_learnings_fts failed: %s", exc)
        return []


def count_learnings(**kwargs: Any) -> int:
    """Return total number of learnings."""
    try:
        from layla.memory.db import count_learnings as _cl
        return _cl(**kwargs)
    except Exception as exc:
        logger.debug("memory_router: count_learnings failed: %s", exc)
        return 0


def get_aspect_memories(aspect_id: str, n: int = 10, **kwargs: Any) -> list[dict]:
    """Read aspect-specific memories."""
    try:
        from layla.memory.db import get_aspect_memories as _gam
        return _gam(aspect_id, n, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: get_aspect_memories failed: %s", exc)
        return []


def get_user_identity(key: str) -> Any:
    """Read a user identity key."""
    try:
        from layla.memory.db import get_user_identity as _gui
        return _gui(key)
    except Exception as exc:
        logger.debug("memory_router: get_user_identity failed: %s", exc)
        return None


def set_user_identity(key: str, value: str, **kwargs: Any) -> None:
    """Write a user identity key."""
    try:
        from layla.memory.db import set_user_identity as _sui
        _sui(key, value, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: set_user_identity failed: %s", exc)


def get_all_user_identity() -> dict[str, Any]:
    """Read all user identity key-value pairs."""
    try:
        from layla.memory.db import get_all_user_identity as _gaui
        return _gaui()
    except Exception as exc:
        logger.debug("memory_router: get_all_user_identity failed: %s", exc)
        return {}


def delete_learnings_by_id(ids: list[int]) -> int:
    """Delete learnings by their IDs. Returns count deleted."""
    try:
        from layla.memory.db import delete_learnings_by_id as _dli
        return _dli(ids)
    except Exception as exc:
        logger.debug("memory_router: delete_learnings_by_id failed: %s", exc)
        return 0


# ── Conversation helpers ────────────────────────────────────────────────────────

def create_conversation(conversation_id: str = "", title: str = "", **kwargs: Any) -> str:
    """Create a new conversation record. Returns conversation_id."""
    try:
        from layla.memory.db import create_conversation as _cc
        return _cc(conversation_id=conversation_id, title=title, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: create_conversation failed: %s", exc)
        return conversation_id or ""


def append_conversation_message(
    conversation_id: str, role: str, content: str, **kwargs: Any,
) -> None:
    """Append a message to a conversation."""
    try:
        from layla.memory.db import append_conversation_message as _acm
        _acm(conversation_id, role, content, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: append_conversation_message failed: %s", exc)


def get_conversation_messages(
    conversation_id: str, limit: int = 50, **kwargs: Any,
) -> list[dict]:
    """Read messages for a conversation."""
    try:
        from layla.memory.db import get_conversation_messages as _gcm
        return _gcm(conversation_id, limit=limit, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: get_conversation_messages failed: %s", exc)
        return []


def get_conversation(conversation_id: str, **kwargs: Any) -> dict | None:
    """Read a conversation record by ID."""
    try:
        from layla.memory.db import get_conversation as _gc
        return _gc(conversation_id, **kwargs)
    except Exception as exc:
        logger.debug("memory_router: get_conversation failed: %s", exc)
        return None


# ── Entity CRUD ────────────────────────────────────────────────────────────────

# ── BL-020: encrypt sensitive entity descriptions at rest ────────────────────
# Same contract as learnings: encrypt() is idempotent (no-op on already-ciphertext,
# so merges are safe) and decrypt() is a transparent no-op on plaintext (legacy rows).
def _enc_desc(text, privacy_level) -> str:
    if not text:
        return text
    try:
        from services.memory.memory_encryption import maybe_encrypt
        return maybe_encrypt(text, privacy_level, _cfg())
    except Exception:
        return text


def _dec_entity(d):
    """Decrypt an entity dict's description in place (no-op for plaintext)."""
    try:
        from services.memory.memory_encryption import decrypt
        if isinstance(d, dict) and d.get("description"):
            d["description"] = decrypt(d["description"])
    except Exception:
        pass
    return d


def upsert_entity(entity: Entity) -> bool:
    """
    Write an entity to SQLite. If an entity with the same ID already exists,
    merge the records (union aliases/tags, keep higher confidence description).
    Returns True if written, False if skipped/failed.
    A `sensitive` privacy_level + the encryption flag → the description is stored
    encrypted at rest (BL-020); reads decrypt transparently.
    """
    try:
        from schemas.entity import validate_entity
        errors = validate_entity(entity)
        if errors:
            logger.warning("memory_router: entity validation failed: %s", errors)
            return False

        from layla.memory.db_connection import _conn
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with _conn() as db:
            existing = db.execute(
                "SELECT * FROM entities WHERE id = ?", (entity.id,)
            ).fetchone()

            if existing:
                # Merge: union aliases/tags, keep higher confidence
                ex_aliases = json.loads(existing["aliases"] or "[]")
                ex_tags = json.loads(existing["tags"] or "[]")
                merged_aliases = sorted(set(ex_aliases + entity.aliases))
                merged_tags = sorted(set(ex_tags + entity.tags))
                new_conf = max(float(existing["confidence"] or 0.0), entity.confidence)
                new_desc = entity.description if entity.confidence >= float(existing["confidence"] or 0.0) \
                    else (existing["description"] or entity.description)
                # Privacy from the incoming entity, falling back to the stored level.
                try:
                    _ex_priv = existing["privacy_level"] if "privacy_level" in existing.keys() else "public"
                except Exception:
                    _ex_priv = "public"
                _u_priv = getattr(entity, "privacy_level", None) or _ex_priv or "public"

                db.execute("""
                    UPDATE entities SET
                        aliases = ?, tags = ?, confidence = ?,
                        description = ?, updated_at = ?, last_seen_at = ?, privacy_level = ?
                    WHERE id = ?
                """, (
                    json.dumps(merged_aliases), json.dumps(merged_tags),
                    new_conf, _enc_desc(new_desc, _u_priv), now, now, _u_priv, entity.id,
                ))
            else:
                _priv = getattr(entity, "privacy_level", "public") or "public"
                db.execute("""
                    INSERT INTO entities
                        (id, type, canonical_name, aliases, description, tags,
                         confidence, source, evidence, created_at, updated_at, last_seen_at, attributes,
                         privacy_level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entity.id, entity.type, entity.canonical_name,
                    json.dumps(entity.aliases), _enc_desc(entity.description, _priv),
                    json.dumps(entity.tags), entity.confidence,
                    entity.source, entity.evidence,
                    entity.created_at, entity.updated_at, entity.last_seen_at,
                    json.dumps(entity.attributes),
                    _priv,
                ))
            db.commit()

        if _cfg().get("memory_router_log_writes"):
            logger.info("memory_router: upsert entity [%s] %s (conf=%.2f)",
                        entity.type, entity.canonical_name, entity.confidence)
        return True

    except Exception as exc:
        logger.warning("memory_router: upsert_entity failed: %s", exc)
        return False


def upsert_relationship(rel: Relationship) -> bool:
    """Write a relationship to SQLite. Upserts by ID."""
    try:
        from schemas.entity import validate_relationship
        errors = validate_relationship(rel)
        if errors:
            logger.warning("memory_router: relationship validation failed: %s", errors)
            return False

        from layla.memory.db_connection import _conn
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with _conn() as db:
            db.execute("""
                INSERT OR REPLACE INTO relationships
                    (id, from_entity, to_entity, type, weight, evidence, source, bidirectional, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rel.id, rel.from_entity, rel.to_entity, rel.type,
                rel.weight, rel.evidence, rel.source,
                1 if rel.bidirectional else 0,
                rel.created_at, now,
            ))
            db.commit()
        return True

    except Exception as exc:
        logger.warning("memory_router: upsert_relationship failed: %s", exc)
        return False


def get_entity(entity_id: str) -> dict | None:
    """Retrieve an entity by ID from SQLite."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            row = db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if row:
                return _dec_entity(dict(row))  # BL-020: decrypt sensitive description
    except Exception as exc:
        logger.debug("memory_router: get_entity failed: %s", exc)
    return None


def get_entity_relationships(entity_id: str) -> list[dict]:
    """Get all relationships involving an entity."""
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            rows = db.execute("""
                SELECT r.*,
                       ef.canonical_name AS from_name, ef.type AS from_type,
                       et.canonical_name AS to_name, et.type AS to_type
                FROM relationships r
                LEFT JOIN entities ef ON r.from_entity = ef.id
                LEFT JOIN entities et ON r.to_entity = et.id
                WHERE r.from_entity = ? OR r.to_entity = ?
                ORDER BY r.weight DESC
                LIMIT 50
            """, (entity_id, entity_id)).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("memory_router: get_entity_relationships failed: %s", exc)
        return []


# ── Query routing ──────────────────────────────────────────────────────────────

def _max_privacy_from_config() -> str:
    """Read the max retrieval privacy level from config; defaults to 'personal' (excludes sensitive)."""
    try:
        return str(_cfg().get("privacy_max_retrieval_level", "personal"))
    except Exception:
        return "personal"


def query(
    text: str,
    *,
    query_type: str = "auto",
    limit: int = 10,
    min_confidence: float = 0.3,
    max_privacy: str | None = None,
) -> list[MemoryResult]:
    """
    Route a memory query to the appropriate store(s) and return merged results.

    query_type:
      "auto"       — auto-detect based on query characteristics
      "factual"    — structured lookup in entities table
      "semantic"   — vector search in ChromaDB
      "relational" — graph traversal in NetworkX
      "recent"     — recent conversations
      "document"   — KB articles

    max_privacy:
      Maximum privacy level to include in results.
      Defaults to config `privacy_max_retrieval_level` (default: "personal").
      Set to "sensitive" to include all data, "public" for exports.
    """
    if not _enabled():
        return []

    _privacy = max_privacy or _max_privacy_from_config()
    results: list[MemoryResult] = []

    if query_type == "auto":
        # Heuristic: short exact-match queries → factual, longer queries → semantic
        if len(text.split()) <= 4:
            query_type = "factual"
        else:
            query_type = "semantic"

    if query_type in ("factual", "auto"):
        results.extend(_query_sqlite_entities(text, limit=limit, min_confidence=min_confidence, max_privacy=_privacy))

    if query_type in ("semantic", "auto"):
        results.extend(_query_chromadb(text, limit=limit))

    if query_type == "relational":
        results.extend(_query_graph(text, limit=limit))

    if query_type == "recent":
        results.extend(_query_recent_conversations(text, limit=limit))

    if query_type == "document":
        results.extend(_query_kb_articles(text, limit=limit))

    # Post-filter: apply privacy level to all results that carry metadata with privacy_level
    try:
        from schemas.entity import privacy_allows
        results = [
            r for r in results
            if privacy_allows(r.metadata.get("privacy_level", "public"), _privacy)
        ]
    except Exception:
        pass  # If import fails, skip filtering (fail-open for compat)

    # Deduplicate by id (prefer higher score)
    seen: dict[str, MemoryResult] = {}
    for r in results:
        if r.id not in seen or r.score > seen[r.id].score:
            seen[r.id] = r

    return sorted(seen.values(), key=lambda r: -r.score)[:limit]


def _query_sqlite_entities(text: str, *, limit: int = 10, min_confidence: float = 0.3,
                           max_privacy: str = "personal") -> list[MemoryResult]:
    """Search entities table by name/description with privacy filtering."""
    results = []
    try:
        from layla.memory.db_connection import _conn
        from schemas.entity import _PRIVACY_RANK, PrivacyLevel
        t = f"%{text.lower()}%"
        # Build list of allowed privacy levels
        try:
            max_idx = _PRIVACY_RANK.index(PrivacyLevel(max_privacy))
            allowed = [pl.value for pl in _PRIVACY_RANK[: max_idx + 1]]
        except (ValueError, KeyError):
            allowed = [pl.value for pl in _PRIVACY_RANK]  # Allow all on unknown level
        placeholders = ", ".join("?" for _ in allowed)
        with _conn() as db:
            # Check if privacy_level column exists
            cols = {r[1] for r in db.execute("PRAGMA table_info(entities)").fetchall()}
            if "privacy_level" in cols:
                rows = db.execute(f"""
                    SELECT * FROM entities
                    WHERE (LOWER(canonical_name) LIKE ? OR LOWER(description) LIKE ?)
                      AND confidence >= ?
                      AND COALESCE(privacy_level, 'public') IN ({placeholders})
                    ORDER BY confidence DESC, updated_at DESC
                    LIMIT ?
                """, (t, t, min_confidence, *allowed, limit)).fetchall()
            else:
                rows = db.execute("""
                    SELECT * FROM entities
                    WHERE (LOWER(canonical_name) LIKE ? OR LOWER(description) LIKE ?)
                      AND confidence >= ?
                    ORDER BY confidence DESC, updated_at DESC
                    LIMIT ?
                """, (t, t, min_confidence, limit)).fetchall()
            for row in rows:
                d = _dec_entity(dict(row))  # BL-020: decrypt sensitive description
                results.append(MemoryResult(
                    id=d["id"],
                    content=f"{d['canonical_name']}: {d['description']}",
                    type=d["type"],
                    score=float(d.get("confidence", 0.5)),
                    source="sqlite_entities",
                    metadata=d,
                ))
    except Exception as exc:
        logger.debug("memory_router: sqlite entity query failed: %s", exc)
    return results


def _query_chromadb(text: str, *, limit: int = 10) -> list[MemoryResult]:
    """Semantic search via ChromaDB."""
    results = []
    try:
        from layla.memory.vector_store import semantic_search
        hits = semantic_search(text, k=limit)
        for hit in hits:
            results.append(MemoryResult(
                id=f"chroma_{hit.get('id', '')}",
                content=hit.get("content", "") or hit.get("text", ""),
                type="semantic",
                score=float(hit.get("score", 0.5)),
                source="chromadb",
                metadata=hit,
            ))
    except Exception as exc:
        logger.debug("memory_router: chromadb query failed: %s", exc)
    return results


def _query_graph(text: str, *, limit: int = 10) -> list[MemoryResult]:
    """Graph-based entity lookup via NetworkX."""
    results = []
    try:
        from services.memory.personal_knowledge_graph import get_related_entities
        entities = get_related_entities(text, k=limit)
        for ent in entities:
            results.append(MemoryResult(
                id=f"graph_{ent.get('id', '')}",
                content=str(ent.get("name", "")),
                type=ent.get("type", "unknown"),
                score=float(ent.get("relevance", 0.5)),
                source="networkx_graph",
                metadata=ent,
            ))
    except Exception as exc:
        logger.debug("memory_router: graph query failed: %s", exc)
    return results


def _query_recent_conversations(text: str, *, limit: int = 10) -> list[MemoryResult]:
    """Search recent conversation history using FTS5 (full-text search) with substring fallback."""
    results = []
    # Primary: FTS5 search (much better than naive substring)
    try:
        from layla.memory.db import search_learnings_fts
        fts_hits = search_learnings_fts(text, limit=limit)
        if fts_hits:
            for l in fts_hits:
                content = (l.get("content") or "")
                results.append(MemoryResult(
                    id=f"learning_{l.get('id', '')}",
                    content=content[:300],
                    type="learning",
                    score=0.7,
                    source="sqlite_learnings_fts",
                    metadata=l,
                ))
            return results[:limit]
    except Exception as exc:
        logger.debug("memory_router: FTS5 search failed, falling back: %s", exc)

    # Fallback: keyword overlap scoring (better than t[:20] substring)
    try:
        from layla.memory.db import get_recent_learnings
        learnings = get_recent_learnings(n=limit * 3)
        query_words = set(w.lower() for w in text.split() if len(w) > 2)
        if not query_words:
            return results
        scored: list[tuple[float, dict]] = []
        for l in learnings:
            content = (l.get("content") or "").lower()
            if not content:
                continue
            overlap = sum(1 for w in query_words if w in content)
            if overlap > 0:
                score = min(0.9, 0.3 + (overlap / len(query_words)) * 0.6)
                scored.append((score, l))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, l in scored[:limit]:
            content = (l.get("content") or "")
            results.append(MemoryResult(
                id=f"learning_{l.get('id', '')}",
                content=content[:300],
                type="learning",
                score=score,
                source="sqlite_learnings",
                metadata=l,
            ))
    except Exception as exc:
        logger.debug("memory_router: recent query failed: %s", exc)
    return results


def _query_kb_articles(text: str, *, limit: int = 10) -> list[MemoryResult]:
    """Search KB article index using keyword overlap scoring."""
    results = []
    try:
        from services.workspace.kb_builder import _kb_output_dir
        idx_path = _kb_output_dir() / "_index.json"
        if not idx_path.exists():
            return results
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        query_words = set(w.lower() for w in text.split() if len(w) > 2)
        if not query_words:
            return results
        scored: list[tuple[float, dict]] = []
        for art in idx.get("articles", []):
            title = (art.get("title") or "").lower()
            summary = (art.get("summary") or "").lower()
            combined = title + " " + summary
            overlap = sum(1 for w in query_words if w in combined)
            if overlap > 0:
                # Title matches score higher than summary-only
                title_overlap = sum(1 for w in query_words if w in title)
                score = min(0.9, 0.4 + (overlap / len(query_words)) * 0.4 + (title_overlap * 0.1))
                scored.append((score, art))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, art in scored[:limit]:
            results.append(MemoryResult(
                id=f"kb_{art.get('id', '')}",
                content=f"{art.get('title', '')}: {art.get('summary', '')}",
                type="article",
                score=score,
                source="kb_articles",
                metadata=art,
            ))
    except Exception as exc:
        logger.debug("memory_router: kb query failed: %s", exc)
    return results


# ── Batch entity discovery ─────────────────────────────────────────────────────

def discover_and_store_entities(text: str, source: str = "") -> int:
    """
    Run entity extraction on text and store all discovered entities.
    Returns number of entities stored.
    """
    try:
        from schemas.entity import Entity, EntityType, make_entity_id
        from services.workspace.kb_builder import extract_entities_from_text

        raw_entities = extract_entities_from_text(text)
        stored = 0

        # Map kb_builder category → EntityType
        _TYPE_MAP = {
            "language": EntityType.TECHNOLOGY,
            "library": EntityType.TECHNOLOGY,
            "database": EntityType.TECHNOLOGY,
            "infrastructure": EntityType.TECHNOLOGY,
            "protocol": EntityType.CONCEPT,
            "ai_concept": EntityType.CONCEPT,
            "concept": EntityType.CONCEPT,
            "error": EntityType.ERROR,
            "class_name": EntityType.CLASS,
            "identifier": EntityType.FUNCTION,
        }

        for category, names in raw_entities.items():
            ent_type = _TYPE_MAP.get(category, EntityType.TECHNOLOGY)
            for name in names:
                if len(name) < 2:
                    continue
                entity = Entity(
                    type=ent_type.value,
                    canonical_name=name.lower().strip(),
                    aliases=[name.strip()],
                    confidence=0.7,
                    source=source,
                    tags=[category],
                )
                if upsert_entity(entity):
                    stored += 1

        return stored
    except Exception as exc:
        logger.debug("memory_router: discover_and_store_entities failed: %s", exc)
        return 0


# ── Coherence check ────────────────────────────────────────────────────────────

def check_coherence() -> dict:
    """
    Run a coherence check across all memory stores.
    Returns a report dict with: conflicts, duplicates, orphaned_relationships.
    Used by scripts/check_memory_coherence.py.
    """
    report = {
        "entities_total": 0,
        "relationships_total": 0,
        "orphaned_relationships": 0,
        "low_confidence_entities": 0,
        "duplicate_names": [],
        "conflicts": [],
    }
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            report["entities_total"] = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            report["relationships_total"] = db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
            report["orphaned_relationships"] = db.execute("""
                SELECT COUNT(*) FROM relationships r
                WHERE NOT EXISTS (SELECT 1 FROM entities WHERE id = r.from_entity)
                   OR NOT EXISTS (SELECT 1 FROM entities WHERE id = r.to_entity)
            """).fetchone()[0]
            report["low_confidence_entities"] = db.execute(
                "SELECT COUNT(*) FROM entities WHERE confidence < 0.3"
            ).fetchone()[0]
            # Find duplicate canonical names with different types
            dupes = db.execute("""
                SELECT canonical_name, GROUP_CONCAT(type) AS types, COUNT(*) AS cnt
                FROM entities
                GROUP BY canonical_name
                HAVING cnt > 1
                LIMIT 20
            """).fetchall()
            report["duplicate_names"] = [
                {"name": r[0], "types": r[1], "count": r[2]} for r in dupes
            ]
    except Exception as exc:
        report["error"] = str(exc)
    return report

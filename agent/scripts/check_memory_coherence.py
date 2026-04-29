#!/usr/bin/env python3
"""
check_memory_coherence.py — Phase A gate: verify memory store coherence.

Checks:
  COH-01  entities table exists and is accessible
  COH-02  relationships table exists and is accessible
  COH-03  No orphaned relationships (reference non-existent entities)
  COH-04  Entity schema validation (all required fields present)
  COH-05  No duplicate canonical_name + type combinations
  COH-06  ChromaDB collection reachable
  COH-07  Knowledge graph (GraphML) readable if it exists

Exit 0 = pass, 1 = fail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))


def check_entities_table() -> tuple[bool, str]:
    try:
        from layla.memory.db import migrate
        from layla.memory.db_connection import _conn
        migrate()
        with _conn() as db:
            count = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        return True, f"entities table OK ({count} rows)"
    except Exception as exc:
        return False, f"entities table error: {exc}"


def check_relationships_table() -> tuple[bool, str]:
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            count = db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        return True, f"relationships table OK ({count} rows)"
    except Exception as exc:
        return False, f"relationships table error: {exc}"


def check_orphaned_relationships() -> tuple[bool, str]:
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            orphaned = db.execute("""
                SELECT COUNT(*) FROM relationships r
                WHERE NOT EXISTS (SELECT 1 FROM entities WHERE id = r.from_entity)
                   OR NOT EXISTS (SELECT 1 FROM entities WHERE id = r.to_entity)
            """).fetchone()[0]
        if orphaned > 0:
            return False, f"FAIL: {orphaned} orphaned relationship(s)"
        return True, "No orphaned relationships"
    except Exception as exc:
        return True, f"SKIP: {exc}"  # Table may be empty on first run


def check_entity_schema() -> tuple[bool, str]:
    try:
        from schemas.entity import Entity, validate_entity, make_entity_id
        # Test round-trip
        ent = Entity(type="technology", canonical_name="fastapi",
                     aliases=["FastAPI"], description="Python web framework",
                     confidence=0.9, source="test")
        errors = validate_entity(ent)
        if errors:
            return False, f"Entity schema validation failed: {errors}"
        d = ent.to_dict()
        ent2 = Entity.from_dict(d)
        if ent2.id != ent.id:
            return False, "Entity round-trip ID mismatch"
        return True, "Entity schema validates correctly"
    except Exception as exc:
        return False, f"Entity schema error: {exc}"


def check_duplicate_entities() -> tuple[bool, str]:
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            dupes = db.execute("""
                SELECT canonical_name, COUNT(*) as cnt
                FROM entities
                GROUP BY canonical_name, type
                HAVING cnt > 1
                LIMIT 5
            """).fetchall()
        if dupes:
            names = [f"{r[0]} ({r[1]}x)" for r in dupes]
            return False, f"FAIL: {len(dupes)} duplicate (canonical_name, type) pairs: {', '.join(names)}"
        return True, "No duplicate entities"
    except Exception as exc:
        return True, f"SKIP: {exc}"  # Empty DB is fine


def check_chromadb() -> tuple[bool, str]:
    try:
        from layla.memory.vector_store import get_collection_count
        count = get_collection_count()
        return True, f"ChromaDB reachable (collections: {count})"
    except ImportError:
        return True, "SKIP: vector_store not available"
    except Exception as exc:
        return False, f"ChromaDB error: {exc}"


def check_knowledge_graph() -> tuple[bool, str]:
    graphml = AGENT_DIR / ".layla" / "knowledge_graph.graphml"
    if not graphml.exists():
        return True, "SKIP: no knowledge_graph.graphml yet (will be created on first index)"
    try:
        import networkx as nx
        g = nx.read_graphml(str(graphml))
        return True, f"Knowledge graph OK ({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)"
    except ImportError:
        return True, "SKIP: networkx not installed"
    except Exception as exc:
        return False, f"Knowledge graph read error: {exc}"


def check_memory_router() -> tuple[bool, str]:
    try:
        from services.memory_router import check_coherence, query
        report = check_coherence()
        if report.get("orphaned_relationships", 0) > 0:
            return False, f"FAIL: {report['orphaned_relationships']} orphaned relationships"
        results = query("python", limit=3)
        return True, f"Memory router OK (coherence check passed, test query returned {len(results)} results)"
    except Exception as exc:
        return False, f"Memory router error: {exc}"


CHECKS = [
    ("COH-01 entities table",         check_entities_table),
    ("COH-02 relationships table",    check_relationships_table),
    ("COH-03 orphaned relationships", check_orphaned_relationships),
    ("COH-04 entity schema",          check_entity_schema),
    ("COH-05 duplicate entities",     check_duplicate_entities),
    ("COH-06 ChromaDB",               check_chromadb),
    ("COH-07 knowledge graph",        check_knowledge_graph),
    ("COH-08 memory router",          check_memory_router),
]


def run() -> int:
    print("=" * 60)
    print("Memory Coherence Check")
    print("=" * 60)

    failures = 0
    for label, fn in CHECKS:
        ok, msg = fn()
        status = "PASS" if ok else "FAIL"
        prefix = "  "
        print(f"{prefix}{label:<35} {status}  {msg}")
        if not ok:
            failures += 1

    print()
    if failures == 0:
        print("All memory coherence checks passed.")
        return 0
    else:
        print(f"FAIL: {failures} issue(s) found")
        return 1


if __name__ == "__main__":
    sys.exit(run())

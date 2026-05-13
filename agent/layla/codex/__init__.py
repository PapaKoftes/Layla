"""Personal knowledge codex — structured entities and relationships."""
from layla.codex.codex_db import (
    upsert_entity, search_entities, get_entity, get_entity_graph,
    link_entities, get_entity_relationships,
    count_entities, list_entity_types,
)
from layla.codex.linker import auto_link_learning

__all__ = [
    "upsert_entity", "search_entities", "get_entity", "get_entity_graph",
    "link_entities", "get_entity_relationships",
    "count_entities", "list_entity_types",
    "auto_link_learning",
]

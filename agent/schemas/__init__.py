"""
Layla canonical data schemas — the single source of truth for all entities
stored anywhere in the system (SQLite, ChromaDB, knowledge graph, KB articles).

Import from here to ensure schema consistency across all services.
"""
from schemas.entity import Entity, EntityType, Relationship, RelationshipType

__all__ = ["Entity", "Relationship", "EntityType", "RelationshipType"]

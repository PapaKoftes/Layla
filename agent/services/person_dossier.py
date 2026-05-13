# -*- coding: utf-8 -*-
"""
person_dossier.py -- Aggregated person profiles from the codex.

When Layla learns about a person (through conversation, research, or explicit
codex entries), this module aggregates all known information into a structured
dossier -- like a videogame character entry in a codex/journal.

Dossier fields:
  - Basic: name, aliases, first met, last interaction
  - Relationship: quality score, interaction count
  - Context: associated projects, key facts/learnings mentioning them
  - Communication: inferred communication style, preferences
  - Notable: quotes, memorable interactions

Auto-updates when the person is mentioned in conversation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from layla.time_utils import utcnow

logger = logging.getLogger("layla")


@dataclass
class PersonDossier:
    """Full aggregated profile for a person entity."""
    entity_id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "person"
    description: str = ""
    confidence: float = 0.5

    # Timeline
    first_seen: str = ""
    last_seen: str = ""
    interaction_count: int = 0

    # Relationships
    relationship_quality: float = 0.5  # 0.0-1.0
    associated_projects: list[str] = field(default_factory=list)
    associated_concepts: list[str] = field(default_factory=list)

    # Knowledge
    key_facts: list[str] = field(default_factory=list)
    communication_style: str = ""
    notable_quotes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Attributes (free-form from codex)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "aliases": self.aliases,
            "entity_type": self.entity_type,
            "description": self.description,
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "interaction_count": self.interaction_count,
            "relationship_quality": self.relationship_quality,
            "associated_projects": self.associated_projects,
            "associated_concepts": self.associated_concepts,
            "key_facts": self.key_facts,
            "communication_style": self.communication_style,
            "notable_quotes": self.notable_quotes,
            "tags": self.tags,
            "attributes": self.attributes,
        }

    def summary_for_prompt(self, max_chars: int = 400) -> str:
        """Compact summary for injection into system prompt context."""
        parts = [f"Person: {self.name}"]
        if self.description:
            parts.append(f"  {self.description[:100]}")
        if self.communication_style:
            parts.append(f"  Communication: {self.communication_style[:80]}")
        if self.associated_projects:
            parts.append(f"  Projects: {', '.join(self.associated_projects[:5])}")
        if self.key_facts:
            for fact in self.key_facts[:3]:
                parts.append(f"  - {fact[:80]}")
        text = "\n".join(parts)
        return text[:max_chars]


def build_dossier(name: str) -> PersonDossier:
    """
    Build a complete person dossier by aggregating data from:
    1. Codex entities table (canonical record)
    2. Relationships table (associated projects/concepts)
    3. Learnings table (facts mentioning this person)
    4. Conversation messages (interaction count, quotes)
    """
    dossier = PersonDossier(name=name)

    try:
        from layla.codex.codex_db import search_entities, get_entity_graph

        # Find the person entity
        matches = search_entities(name, entity_type="person", limit=3)
        if not matches:
            # Try broader search (maybe stored as different type)
            matches = search_entities(name, limit=5)
            matches = [m for m in matches if m.get("canonical_name", "").lower() == name.strip().lower()
                       or name.strip().lower() in [a.lower() for a in (m.get("aliases") or [])]]

        if not matches:
            return dossier  # Person not in codex yet

        entity = matches[0]
        dossier.entity_id = entity.get("id", "")
        dossier.name = entity.get("canonical_name", name)
        dossier.aliases = entity.get("aliases", [])
        dossier.entity_type = entity.get("type", "person")
        dossier.description = entity.get("description", "")
        dossier.confidence = entity.get("confidence", 0.5)
        dossier.first_seen = entity.get("created_at", "")
        dossier.last_seen = entity.get("last_seen_at", "") or entity.get("updated_at", "")
        dossier.tags = entity.get("tags", [])
        dossier.attributes = entity.get("attributes", {})

        # Extract communication style from attributes if stored
        attrs = dossier.attributes
        if isinstance(attrs, dict):
            dossier.communication_style = str(attrs.get("communication_style", ""))

        # Get graph neighbourhood for associated entities
        if dossier.entity_id:
            graph = get_entity_graph(dossier.entity_id, depth=1)
            for node in graph.get("nodes", []):
                if node.get("id") == dossier.entity_id:
                    continue
                node_type = node.get("type", "")
                node_name = node.get("canonical_name", "")
                if node_type == "project":
                    dossier.associated_projects.append(node_name)
                elif node_type in ("concept", "technology", "topic"):
                    dossier.associated_concepts.append(node_name)

    except Exception as exc:
        logger.debug("person_dossier: entity lookup failed: %s", exc)

    # Gather learnings mentioning this person
    try:
        from layla.memory.db import search_learnings_fts

        search_name = name.strip()
        learnings = search_learnings_fts(search_name, limit=20)
        for learning in (learnings or []):
            content = learning.get("content", "")
            if content and len(content) > 20:
                dossier.key_facts.append(content[:200])
        dossier.key_facts = dossier.key_facts[:10]  # Cap at 10
    except Exception as exc:
        logger.debug("person_dossier: learnings search failed: %s", exc)

    # Count conversation mentions
    try:
        from layla.memory.db_connection import _conn
        with _conn() as db:
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM conversation_messages WHERE LOWER(content) LIKE ?",
                (f"%{name.strip().lower()}%",),
            ).fetchone()
            if row:
                dossier.interaction_count = row["cnt"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.debug("person_dossier: interaction count failed: %s", exc)

    return dossier


def get_dossier_for_prompt(name: str, max_chars: int = 400) -> str:
    """Build a dossier and return a compact prompt-ready summary."""
    dossier = build_dossier(name)
    if not dossier.entity_id:
        return ""
    return dossier.summary_for_prompt(max_chars)


def update_person_mention(
    name: str,
    *,
    context: str = "",
    source: str = "conversation",
) -> None:
    """
    Update a person's codex entry when they are mentioned.
    Creates the entity if it doesn't exist. Updates last_seen_at.
    """
    try:
        from layla.codex.codex_db import upsert_entity, search_entities
        from layla.memory.db_connection import _conn

        # Check if entity exists
        matches = search_entities(name, entity_type="person", limit=1)

        if matches:
            # Update last_seen_at
            eid = matches[0].get("id", "")
            if eid:
                now = utcnow()
                with _conn() as db:
                    db.execute(
                        "UPDATE entities SET last_seen_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, eid),
                    )
        else:
            # Create new person entity with low confidence (auto-discovered)
            upsert_entity(
                entity_type="person",
                canonical_name=name.strip(),
                description=context[:200] if context else "",
                confidence=0.4,
                source=source,
            )
    except Exception as exc:
        logger.debug("person_dossier: update_person_mention failed: %s", exc)

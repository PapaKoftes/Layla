"""
entity.py — Canonical entity and relationship schema for Layla's memory system.

THIS IS THE SINGLE SOURCE OF TRUTH.
Every entity stored in any layer (SQLite, ChromaDB, NetworkX, KB articles,
codex entries) MUST use this schema. No exceptions.

Why this matters:
- Prevents contradictions when the same concept appears in multiple stores
- Enables deduplication (same entity_id → same entity everywhere)
- Enables memory coherence checking (`scripts/check_memory_coherence.py`)
- Enables the memory router to merge results from different stores

Design decisions:
- Dataclasses (not Pydantic) — no external dependency, simpler serialisation
- confidence: float — every fact is uncertain; track how certain we are
- source: str — always know where information came from
- SHA256-based ID — deterministic, cross-system, content-addressed
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ── Type enumerations ─────────────────────────────────────────────────────────

class EntityType(str, Enum):
    """Canonical entity types used across all memory layers."""
    PERSON       = "person"        # Real people (user, colleagues, experts)
    CONCEPT      = "concept"       # Abstract ideas, theories, principles
    TECHNOLOGY   = "technology"    # Languages, frameworks, tools, libraries
    PROJECT      = "project"       # Software projects, initiatives, codebases
    FILE         = "file"          # Code files, documents, configs
    FUNCTION     = "function"      # Code functions/methods
    CLASS        = "class_"        # Code classes/types (trailing _ avoids Python clash)
    MODULE       = "module"        # Python/JS modules, packages
    ERROR        = "error"         # Error types, exception patterns
    API_ROUTE    = "api_route"     # HTTP endpoints
    TOPIC        = "topic"         # Knowledge topics (for KB articles)
    EVENT        = "event"         # Time-stamped occurrences
    ORGANISATION = "organisation"  # Companies, teams, communities
    SKILL        = "skill"         # User skills, competencies
    UNKNOWN      = "unknown"       # Fallback when type can't be determined


class PrivacyLevel(str, Enum):
    """Privacy classification for entities and memory items.

    Levels (ascending sensitivity):
      public     — safe to display in UI, export, share
      workspace  — tied to a specific project; visible within that workspace
      personal   — personal info about the user; never exported without consent
      sensitive  — passwords, tokens, health data, NSFW; encrypted at rest ideally

    Retrieval filters by max allowed level: a query with max_privacy=workspace
    will return public + workspace entities but not personal or sensitive.
    """
    PUBLIC    = "public"
    WORKSPACE = "workspace"
    PERSONAL  = "personal"
    SENSITIVE = "sensitive"


# Ordered list for comparison (lower index = less sensitive)
_PRIVACY_RANK = [PrivacyLevel.PUBLIC, PrivacyLevel.WORKSPACE, PrivacyLevel.PERSONAL, PrivacyLevel.SENSITIVE]


def privacy_allows(item_level: str, max_level: str) -> bool:
    """Return True if item_level is at or below max_level in sensitivity."""
    try:
        item_rank = _PRIVACY_RANK.index(PrivacyLevel(item_level))
        max_rank = _PRIVACY_RANK.index(PrivacyLevel(max_level))
        return item_rank <= max_rank
    except (ValueError, KeyError):
        return True  # Unknown levels are treated as allowed (fail-open for compat)


class RelationshipType(str, Enum):
    """Canonical relationship types between entities."""
    USES         = "uses"          # A uses B (technology A uses library B)
    DEPENDS_ON   = "depends_on"    # A depends on B (module A imports module B)
    IS_PART_OF   = "is_part_of"    # A is part of B (function A is in module B)
    CREATED_BY   = "created_by"    # A was created by B (file A by person B)
    KNOWS        = "knows"         # Person A knows person B
    WORKED_ON    = "worked_on"     # Person A worked on project B
    MENTIONS     = "mentions"      # Document A mentions entity B
    SUPERSEDES   = "supersedes"    # A replaces/supersedes B
    SIMILAR_TO   = "similar_to"    # A is similar to B (concept similarity)
    CALLS        = "calls"         # Function A calls function B
    IMPORTS      = "imports"       # Module A imports module B
    RELATES_TO   = "relates_to"    # Generic weak relationship


# ── Core schemas ─────────────────────────────────────────────────────────────

@dataclass
class Entity:
    """
    Canonical entity record. Used in:
    - SQLite entities table
    - ChromaDB metadata
    - NetworkX node attributes
    - KB article metadata
    - Codex entries

    The `id` is a deterministic SHA256 hash of (type + canonical_name),
    ensuring the same entity always gets the same ID regardless of which
    service created it.
    """
    # Identity
    type: str                          # EntityType value
    canonical_name: str                # Normalised name (lowercase, stripped)
    id: str = ""                       # Auto-computed from type+canonical_name if empty

    # Descriptive
    aliases: list[str] = field(default_factory=list)   # Other names for this entity
    description: str = ""             # One-line summary
    tags: list[str] = field(default_factory=list)       # Free-form categorisation tags

    # Quality
    confidence: float = 0.5           # 0.0 (guess) → 1.0 (verified)
    source: str = ""                  # Where this came from (file path, URL, conversation ID)
    evidence: str = ""                # Specific text that established this entity

    # Privacy
    privacy_level: str = "public"     # PrivacyLevel value: public/workspace/personal/sensitive

    # Temporal
    created_at: str = ""              # ISO 8601 datetime
    updated_at: str = ""              # ISO 8601 datetime
    last_seen_at: str = ""            # Last time this entity appeared in context

    # Extended attributes (flexible, schema-free)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.id:
            self.id = make_entity_id(self.type, self.canonical_name)
        # Normalise canonical_name
        self.canonical_name = self.canonical_name.strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        # Handle old records that might not have all fields
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    def merge(self, other: "Entity") -> "Entity":
        """
        Merge another entity record into this one.
        Higher-confidence record wins for description/type.
        Aliases, tags, and attributes are unioned.
        """
        if other.confidence > self.confidence:
            self.description = other.description or self.description
            self.type = other.type if other.type != EntityType.UNKNOWN.value else self.type
            self.confidence = other.confidence
        self.aliases = sorted(set(self.aliases + other.aliases))
        self.tags = sorted(set(self.tags + other.tags))
        self.attributes.update({k: v for k, v in other.attributes.items() if k not in self.attributes})
        if other.source and other.source not in self.source:
            self.source = self.source + "; " + other.source if self.source else other.source
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return self


@dataclass
class Relationship:
    """
    Canonical relationship between two entities. Used in:
    - SQLite relationships table
    - NetworkX edges
    - KB article links
    """
    from_entity: str               # Entity.id
    to_entity: str                 # Entity.id
    type: str                      # RelationshipType value
    id: str = ""                   # Auto-computed

    weight: float = 0.5            # 0.0 (weak) → 1.0 (strong/certain)
    evidence: str = ""             # Text excerpt that established this relationship
    source: str = ""               # Origin (file, conversation, URL)
    bidirectional: bool = False    # True if the relationship goes both ways

    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.id:
            self.id = make_relationship_id(self.from_entity, self.to_entity, self.type)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ── ID factories ──────────────────────────────────────────────────────────────

def make_entity_id(entity_type: str, canonical_name: str) -> str:
    """
    Deterministic entity ID — same type+name always produces the same ID.
    Uses SHA256 first 16 hex chars for brevity.
    """
    raw = f"{entity_type}::{canonical_name.strip().lower()}"
    return "ent_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_relationship_id(from_id: str, to_id: str, rel_type: str) -> str:
    """Deterministic relationship ID."""
    raw = f"{from_id}::{rel_type}::{to_id}"
    return "rel_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Convenience constructors ──────────────────────────────────────────────────

def person(name: str, *, description: str = "", tags: list[str] | None = None,
           confidence: float = 0.5, source: str = "",
           privacy_level: str = "personal") -> Entity:
    return Entity(
        type=EntityType.PERSON.value,
        canonical_name=name.lower().strip(),
        aliases=[name.strip()],
        description=description,
        tags=tags or [],
        confidence=confidence,
        source=source,
        privacy_level=privacy_level,
    )


def technology(name: str, *, description: str = "", tags: list[str] | None = None,
               confidence: float = 0.8, source: str = "",
               privacy_level: str = "public") -> Entity:
    return Entity(
        type=EntityType.TECHNOLOGY.value,
        canonical_name=name.lower().strip(),
        aliases=[name.strip()],
        description=description,
        tags=tags or ["technology"],
        confidence=confidence,
        source=source,
        privacy_level=privacy_level,
    )


def concept(name: str, *, description: str = "", tags: list[str] | None = None,
            confidence: float = 0.7, source: str = "",
            privacy_level: str = "public") -> Entity:
    return Entity(
        type=EntityType.CONCEPT.value,
        canonical_name=name.lower().strip(),
        aliases=[name.strip()],
        description=description,
        tags=tags or [],
        confidence=confidence,
        source=source,
        privacy_level=privacy_level,
    )


def code_function(name: str, *, module: str = "", description: str = "",
                  confidence: float = 0.9, source: str = "",
                  privacy_level: str = "workspace") -> Entity:
    canonical = f"{module}.{name}" if module else name
    return Entity(
        type=EntityType.FUNCTION.value,
        canonical_name=canonical.lower().strip(),
        aliases=[name, canonical],
        description=description,
        tags=["code", "function"],
        confidence=confidence,
        source=source,
        privacy_level=privacy_level,
        attributes={"module": module, "function_name": name},
    )


# ── Validation ────────────────────────────────────────────────────────────────

def validate_entity(entity: Entity) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []
    if not entity.canonical_name:
        errors.append("canonical_name must not be empty")
    if not entity.type:
        errors.append("type must not be empty")
    if not (0.0 <= entity.confidence <= 1.0):
        errors.append(f"confidence must be 0.0-1.0, got {entity.confidence}")
    if entity.id and not entity.id.startswith("ent_"):
        errors.append(f"entity id should start with 'ent_', got '{entity.id}'")
    valid_privacy = {pl.value for pl in PrivacyLevel}
    if entity.privacy_level and entity.privacy_level not in valid_privacy:
        errors.append(f"privacy_level must be one of {valid_privacy}, got '{entity.privacy_level}'")
    return errors


def validate_relationship(rel: Relationship) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []
    if not rel.from_entity:
        errors.append("from_entity must not be empty")
    if not rel.to_entity:
        errors.append("to_entity must not be empty")
    if not rel.type:
        errors.append("type must not be empty")
    if not (0.0 <= rel.weight <= 1.0):
        errors.append(f"weight must be 0.0-1.0, got {rel.weight}")
    return errors

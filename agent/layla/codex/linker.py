"""
linker.py — Auto-link new learnings to existing codex entities.

Given a piece of learning content, this module:
1. Extracts entity mentions (via enricher.extract_entities)
2. Fuzzy-matches each mention against the existing codex
3. Creates "mentions" relationships between the learning's
   source entities and matched codex entries
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla.codex")


# ── Public API ───────────────────────────────────────────────────────────────

def auto_link_learning(learning_content: str, learning_id: int) -> list[dict]:
    """
    Extract entity mentions from *learning_content*, fuzzy-match against
    the existing codex, and create ``mentions`` relationships.

    For each matched entity, a relationship is created from the entity to
    itself (with evidence pointing back to the learning). If the extracted
    entity is new, it is upserted into the codex first.

    Returns a list of dicts describing each link created:
        [{"entity_id": str, "entity_name": str, "rel_type": str, "new": bool}, ...]
    """
    from layla.codex.codex_db import (
        link_entities,
        search_entities,
    )
    from layla.codex.codex_db import (
        upsert_entity as codex_upsert,
    )
    from layla.codex.enricher import extract_entities
    from schemas.entity import make_entity_id

    if not learning_content or not learning_content.strip():
        return []

    extracted = extract_entities(learning_content)
    if not extracted:
        return []

    links_created: list[dict] = []
    source_label = f"learning:{learning_id}"

    for ent in extracted:
        name = ent.get("name", "").strip()
        etype = ent.get("type", "concept")
        conf = float(ent.get("confidence", 0.5))

        if not name or len(name) < 2:
            continue

        # Try to find an existing codex match
        match = find_best_codex_match(name, entity_type=etype)

        if match:
            matched_id = match["id"]
            is_new = False
        else:
            # Upsert the new entity
            result = codex_upsert(
                entity_type=etype,
                canonical_name=name,
                confidence=min(conf, 0.6),  # New auto-discovered entities get capped confidence
                source=source_label,
            )
            if not result:
                continue
            matched_id = result.get("id", "")
            is_new = True

        if not matched_id:
            continue

        # Create a "mentions" relationship from a synthetic learning-entity
        # to the matched codex entity.
        # Ensure the learning pseudo-entity exists (type must match the ID we use)
        learning_ent = codex_upsert(
            entity_type="topic",
            canonical_name=f"learning_{learning_id}",
            description=learning_content[:200],
            confidence=0.5,
            source=source_label,
        )
        learning_entity_id = (learning_ent or {}).get("id") or make_entity_id("topic", f"learning_{learning_id}")

        rel = link_entities(
            from_id=learning_entity_id,
            to_id=matched_id,
            rel_type="mentions",
            weight=conf,
            evidence=learning_content[:300],
        )

        if rel:
            links_created.append({
                "entity_id": matched_id,
                "entity_name": name,
                "rel_type": "mentions",
                "new": is_new,
            })

    return links_created


def find_best_codex_match(
    name: str,
    entity_type: str = "",
) -> dict | None:
    """
    Find the best matching entity in the codex by name similarity.

    Matching strategy (in priority order):
    1. Exact canonical_name match
    2. Substring / prefix match in canonical_name or aliases
    3. Token-based Jaccard similarity >= 0.5

    Returns the entity dict of the best match, or None.
    """
    from layla.codex.codex_db import search_entities

    norm = _normalize(name)
    if not norm:
        return None

    # Search broadly — the DB LIKE query will get candidates
    candidates = search_entities(
        norm,
        entity_type=entity_type if entity_type else None,
        min_confidence=0.0,
        limit=30,
    )

    if not candidates:
        return None

    best: dict | None = None
    best_score = 0.0

    for cand in candidates:
        cname = _normalize(cand.get("canonical_name", ""))
        aliases_raw = cand.get("aliases", [])
        if isinstance(aliases_raw, str):
            try:
                import json
                aliases_raw = json.loads(aliases_raw)
            except Exception:
                aliases_raw = []
        alias_norms = [_normalize(a) for a in aliases_raw if a]

        score = 0.0

        # Exact match on canonical name
        if cname == norm:
            score = 1.0
        # Exact match on any alias
        elif norm in alias_norms:
            score = 0.95
        # Substring/prefix match
        elif norm in cname or cname in norm:
            overlap = min(len(norm), len(cname)) / max(len(norm), len(cname), 1)
            score = 0.6 + 0.2 * overlap
        elif any(norm in a or a in norm for a in alias_norms):
            score = 0.65
        else:
            # Token Jaccard
            score = _jaccard(norm, cname)

        if score > best_score:
            best_score = score
            best = cand

    # Require a minimum match quality
    if best_score >= 0.5:
        return best
    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    s = name.strip().lower()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two normalised strings."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)

# -*- coding: utf-8 -*-
"""
conversation_entity_extractor.py -- Extract entities from every conversation exchange.

Runs as a post-response hook in agent_loop. After each exchange:
1. Extract entities from user message + assistant response
2. Auto-upsert to codex via memory_router
3. Auto-link entities to current conversation
4. Track mention counts for heat-map/frequency analysis

Design constraints:
  - Max 200ms per extraction (fast path; skip if slow)
  - Max 5 new entities per exchange (avoid flooding)
  - Throttle: max 20 entities per minute
  - Uses codex enricher (spaCy/regex fallback)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from layla.time_utils import utcnow

logger = logging.getLogger("layla")

# Rate limiting
_entity_count_lock = threading.Lock()
_entity_timestamps: list[float] = []
_MAX_ENTITIES_PER_MINUTE = 20
_MAX_ENTITIES_PER_EXCHANGE = 5


def _rate_check() -> bool:
    """Return True if we can still create entities (under rate limit)."""
    now = time.monotonic()
    with _entity_count_lock:
        # Prune old timestamps
        cutoff = now - 60.0
        while _entity_timestamps and _entity_timestamps[0] < cutoff:
            _entity_timestamps.pop(0)
        return len(_entity_timestamps) < _MAX_ENTITIES_PER_MINUTE


def _record_entity_creation(count: int = 1) -> None:
    """Record that entities were created."""
    now = time.monotonic()
    with _entity_count_lock:
        for _ in range(count):
            _entity_timestamps.append(now)


def extract_and_store(
    user_message: str,
    assistant_response: str,
    *,
    conversation_id: str = "",
    aspect_id: str = "",
) -> dict[str, Any]:
    """
    Extract entities from a conversation exchange and store them in the codex.

    Returns summary dict with entity_count and entity_names.
    """
    result = {"entity_count": 0, "entity_names": [], "ok": True}

    if not _rate_check():
        logger.debug("conversation_entity_extractor: rate limited")
        return result

    t0 = time.monotonic()

    # Combine both sides for extraction
    combined_text = f"{user_message}\n{assistant_response}"
    if len(combined_text) < 20:
        return result

    # Extract entities using codex enricher
    try:
        from layla.codex.enricher import extract_entities

        raw_entities = extract_entities(combined_text)
        if not raw_entities:
            return result

        # Deduplicate by lowercase name
        seen: set[str] = set()
        unique_entities: list[dict] = []
        for ent in raw_entities:
            name = (ent.get("name") or ent.get("text") or "").strip()
            if not name or len(name) < 2 or name.lower() in seen:
                continue
            seen.add(name.lower())
            unique_entities.append(ent)

        # Cap at max per exchange
        unique_entities = unique_entities[:_MAX_ENTITIES_PER_EXCHANGE]

        # Upsert each entity
        created = 0
        for ent in unique_entities:
            # Bail if taking too long (200ms budget)
            if (time.monotonic() - t0) > 0.2:
                logger.debug("conversation_entity_extractor: time budget exceeded")
                break

            name = (ent.get("name") or ent.get("text") or "").strip()
            ent_type = (ent.get("type") or ent.get("label") or "unknown").strip().lower()

            # Map spaCy labels to our entity types
            type_map = {
                "person": "person", "per": "person",
                "org": "organisation", "organization": "organisation",
                "gpe": "concept",  # geopolitical entity
                "loc": "concept",
                "product": "technology",
                "language": "technology",
                "library": "technology",
                "framework": "technology",
                "database": "technology",
                "protocol": "technology",
                "error": "error",
                "ai_concept": "concept",
            }
            mapped_type = type_map.get(ent_type, ent_type)
            if mapped_type not in (
                "person", "concept", "technology", "project", "file", "function",
                "class_", "module", "error", "api_route", "topic", "event",
                "organisation", "skill", "unknown",
            ):
                mapped_type = "concept"

            try:
                from layla.codex.codex_db import upsert_entity

                upsert_entity(
                    entity_type=mapped_type,
                    canonical_name=name,
                    confidence=0.4,  # Auto-discovered = lower confidence
                    source=f"conversation:{conversation_id}" if conversation_id else "conversation",
                )
                created += 1
                result["entity_names"].append(name)
            except Exception as exc:
                logger.debug("conversation_entity_extractor: upsert failed for '%s': %s", name, exc)
                continue

        if created > 0:
            _record_entity_creation(created)
            result["entity_count"] = created

        # Update person mentions specifically (updates last_seen_at, builds dossier data)
        for ent in unique_entities[:created]:
            name = (ent.get("name") or ent.get("text") or "").strip()
            ent_type = (ent.get("type") or ent.get("label") or "").strip().lower()
            if ent_type in ("person", "per"):
                try:
                    from services.person_dossier import update_person_mention
                    update_person_mention(name, context=user_message[:200], source="conversation")
                except Exception:
                    pass

    except Exception as exc:
        logger.debug("conversation_entity_extractor: extraction failed: %s", exc)
        result["ok"] = False

    elapsed_ms = (time.monotonic() - t0) * 1000
    if result["entity_count"] > 0:
        logger.info(
            "conversation_entity_extractor: extracted %d entities in %.0fms",
            result["entity_count"], elapsed_ms,
        )

    return result


def extract_in_background(
    user_message: str,
    assistant_response: str,
    *,
    conversation_id: str = "",
    aspect_id: str = "",
) -> None:
    """
    Fire-and-forget background extraction. Called from agent_loop post-response.
    """
    def _run():
        try:
            extract_and_store(
                user_message,
                assistant_response,
                conversation_id=conversation_id,
                aspect_id=aspect_id,
            )
        except Exception as exc:
            logger.debug("conversation_entity_extractor background: %s", exc)

    t = threading.Thread(target=_run, daemon=True, name="conv_entity_extract")
    t.start()

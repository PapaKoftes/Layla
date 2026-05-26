# -*- coding: utf-8 -*-
"""
people_codex.py — Extract and manage people entities from conversations.

Scans conversation history for people mentions, extracts names/relationships/
communication patterns, and stores as codex entities (type="person").

Config keys:
    people_codex_enabled   bool  (default true)
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger("layla")

# Common name patterns (simple heuristic — not NER)
_NAME_PATTERN = re.compile(
    r"\b(?:my (?:friend|colleague|boss|partner|wife|husband|brother|sister|"
    r"mom|dad|teacher|manager|mentor|coworker)|"
    r"(?:talk(?:ed|ing)? to|met with|email(?:ed)? (?:from)?|message from|"
    r"call(?:ed)? (?:from)?|meeting with))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    re.MULTILINE,
)

# Direct name mention after "called" or "named"
_CALLED_PATTERN = re.compile(
    r"(?:called|named|known as)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)

# "@name" mention pattern (common in chat)
_AT_PATTERN = re.compile(r"@([A-Za-z][A-Za-z0-9_]+)")

# Common false positives to filter
_FALSE_POSITIVES = frozenset({
    "Python", "Java", "JavaScript", "TypeScript", "Rust", "Docker",
    "Linux", "Windows", "MacOS", "Chrome", "Firefox", "GitHub",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Google", "Microsoft", "Apple", "Amazon", "Facebook", "Meta",
    "Hello", "Thanks", "Please", "Sorry", "Sure", "True", "False", "None",
    "Layla", "Morrigan", "Nyx", "Echo", "Eris", "Cassandra", "Lilith",
})


def extract_people_from_text(text: str) -> list[dict[str, str]]:
    """
    Extract people mentions from text.

    Returns list of dicts: {"name": str, "context": str, "relationship": str}
    """
    if not text:
        return []

    people: list[dict[str, str]] = []
    seen_names: set[str] = set()

    # Pattern 1: "my friend/colleague/etc NAME"
    for match in _NAME_PATTERN.finditer(text):
        name = match.group(1).strip()
        if name not in _FALSE_POSITIVES and name not in seen_names:
            # Extract relationship from prefix
            prefix = match.group(0).split(name)[0].strip().lower()
            relationship = _classify_relationship(prefix)
            context = text[max(0, match.start() - 40):match.end() + 40].strip()
            people.append({"name": name, "context": context, "relationship": relationship})
            seen_names.add(name)

    # Pattern 2: "called/named NAME"
    for match in _CALLED_PATTERN.finditer(text):
        name = match.group(1).strip()
        if name not in _FALSE_POSITIVES and name not in seen_names:
            context = text[max(0, match.start() - 40):match.end() + 40].strip()
            people.append({"name": name, "context": context, "relationship": "known"})
            seen_names.add(name)

    return people


def _classify_relationship(prefix: str) -> str:
    """Classify relationship from mention prefix."""
    if any(w in prefix for w in ("friend",)):
        return "friend"
    if any(w in prefix for w in ("colleague", "coworker", "manager", "boss")):
        return "work"
    if any(w in prefix for w in ("wife", "husband", "partner", "brother", "sister", "mom", "dad")):
        return "family"
    if any(w in prefix for w in ("teacher", "mentor")):
        return "mentor"
    if any(w in prefix for w in ("meeting", "email", "talk", "call", "message")):
        return "contact"
    return "known"


def scan_conversations_for_people(limit: int = 100) -> list[dict]:
    """
    Scan recent conversations for people mentions.

    Returns aggregated people list with mention counts.
    """
    people_counter: Counter = Counter()
    people_data: dict[str, dict] = {}

    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()
        with _conn() as db:
            # Search user messages for people mentions
            rows = db.execute(
                "SELECT content FROM messages WHERE role = 'user' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        for row in rows:
            content = str(row[0] or "")
            for person in extract_people_from_text(content):
                name = person["name"]
                people_counter[name] += 1
                if name not in people_data:
                    people_data[name] = person
    except Exception as exc:
        logger.debug("scan_conversations_for_people failed: %s", exc)

    # Build result with counts
    results = []
    for name, count in people_counter.most_common(50):
        data = people_data.get(name, {"name": name, "context": "", "relationship": "known"})
        data["mention_count"] = count
        results.append(data)

    return results


def save_people_to_codex(people: list[dict]) -> int:
    """
    Save extracted people to the codex as person entities.

    Returns count of new entities created.
    """
    created = 0
    for person in people:
        try:
            from layla.codex.codex_db import upsert_entity
            entity = {
                "name": person["name"],
                "type": "person",
                "attributes": {
                    "relationship": person.get("relationship", "known"),
                    "context": person.get("context", "")[:200],
                    "mention_count": person.get("mention_count", 1),
                },
            }
            upsert_entity(entity)
            created += 1
        except Exception as exc:
            logger.debug("save_people_to_codex failed for %s: %s", person.get("name"), exc)
    return created


def get_people() -> list[dict]:
    """Get all person entities from the codex."""
    try:
        from layla.codex.codex_db import get_entities_by_type
        return get_entities_by_type("person")
    except Exception as exc:
        logger.debug("get_people failed: %s", exc)
        return []

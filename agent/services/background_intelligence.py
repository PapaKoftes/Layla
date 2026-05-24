"""
background_intelligence.py -- Scheduled intelligence jobs for autonomous learning.

These jobs run periodically (on startup + every 30 min when idle) to:
1. Enrich low-confidence entities with additional context
2. Auto-build KB articles when enough learnings accumulate on a topic
3. Process spaced-repetition review queue
4. Discover relationships between co-occurring entities
5. Scan strategy stats for patterns

All jobs are non-destructive and best-effort. Failures are logged but never block.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def run_reflection_scan() -> dict[str, Any]:
    """Scan recent strategy stats; identify success/failure patterns."""
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        with _conn() as db:
            rows = db.execute(
                "SELECT task_type, strategy, success_count, fail_count FROM strategy_stats "
                "ORDER BY last_updated_at DESC LIMIT 30"
            ).fetchall()
        hits = [dict(r) for r in rows] if rows else []

        # Identify strategies with high failure rates
        warnings = []
        for row in hits:
            total = (row.get("success_count", 0) or 0) + (row.get("fail_count", 0) or 0)
            if total >= 3 and (row.get("fail_count", 0) or 0) / total > 0.5:
                warnings.append(f"{row.get('strategy', '?')} for {row.get('task_type', '?')}: {row.get('fail_count', 0)} failures")

        if warnings:
            logger.info("background_reflection: %d high-failure strategies: %s", len(warnings), "; ".join(warnings[:5]))

        return {"ok": True, "rows": len(hits), "warnings": warnings}
    except Exception as e:
        logger.debug("reflection_scan: %s", e)
        return {"ok": False, "error": str(e)}


def run_codex_entity_nudge() -> dict[str, Any]:
    """
    Enrich codex entities from recent conversation summaries.
    Extracts entities from summaries that aren't yet in the codex.
    """
    try:
        from layla.memory.db import get_recent_conversation_summaries

        sums = get_recent_conversation_summaries(n=5)
        if not sums:
            return {"ok": True, "summaries_seen": 0, "entities_created": 0}

        entities_created = 0
        for summary in sums:
            content = summary.get("summary", "") if isinstance(summary, dict) else str(summary)
            if not content or len(content) < 30:
                continue

            try:
                from layla.codex.codex_db import search_entities, upsert_entity
                from layla.codex.enricher import extract_entities

                raw_entities = extract_entities(content)
                for ent in (raw_entities or [])[:3]:  # Max 3 per summary
                    name = (ent.get("name") or ent.get("text") or "").strip()
                    if not name or len(name) < 3:
                        continue
                    # Skip if already exists with reasonable confidence
                    existing = search_entities(name, limit=1)
                    if existing and existing[0].get("confidence", 0) >= 0.4:
                        continue
                    ent_type = (ent.get("type") or ent.get("label") or "concept").strip().lower()
                    if ent_type not in ("person", "concept", "technology", "project", "organisation", "topic"):
                        ent_type = "concept"
                    upsert_entity(
                        entity_type=ent_type,
                        canonical_name=name,
                        confidence=0.35,
                        source="background_enrichment",
                    )
                    entities_created += 1
            except Exception as exc:
                logger.debug("codex_entity_nudge: extraction failed: %s", exc)
                continue

        return {"ok": True, "summaries_seen": len(sums), "entities_created": entities_created}
    except Exception as e:
        return {"ok": False, "error": str(e)}


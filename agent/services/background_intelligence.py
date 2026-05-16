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
import time
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


def run_codex_relationship_discovery() -> dict[str, Any]:
    """
    Find entities that co-occur in learnings but lack explicit relationships.
    Creates 'co_occurs' relationships when entities are mentioned together.
    """
    try:
        from layla.codex.codex_db import link_entities, search_entities
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        relationships_created = 0

        with _conn() as db:
            # Get recent learnings
            rows = db.execute(
                "SELECT id, content FROM learnings ORDER BY id DESC LIMIT 50"
            ).fetchall()

        if not rows:
            return {"ok": True, "relationships_created": 0}

        # Get all entity names for matching
        all_entities = search_entities("", min_confidence=0.3, limit=200)
        entity_names: dict[str, dict] = {}
        for ent in all_entities:
            name = (ent.get("canonical_name") or "").strip().lower()
            if name and len(name) >= 3:
                entity_names[name] = ent

        # Find co-occurrences in learnings
        for row in rows:
            content = (row["content"] if isinstance(row, dict) else row[1] or "").lower()
            if len(content) < 30:
                continue

            mentioned = []
            for name, ent in entity_names.items():
                if name in content:
                    mentioned.append(ent)

            # Create relationships for co-occurring pairs
            if len(mentioned) >= 2:
                for i in range(min(len(mentioned), 3)):
                    for j in range(i + 1, min(len(mentioned), 3)):
                        ent_a = mentioned[i]
                        ent_b = mentioned[j]
                        try:
                            link_entities(
                                ent_a["id"],
                                ent_b["id"],
                                "co_occurs",
                                weight=0.3,
                                evidence="co-occurred in learning",
                            )
                            relationships_created += 1
                        except Exception:
                            continue

            if relationships_created >= 10:
                break  # Cap per run

        if relationships_created > 0:
            logger.info("background_intelligence: created %d co-occurrence relationships", relationships_created)

        return {"ok": True, "relationships_created": relationships_created}
    except Exception as e:
        logger.debug("codex_relationship_discovery: %s", e)
        return {"ok": False, "error": str(e)}


def run_spaced_repetition_review() -> dict[str, Any]:
    """
    Process learnings due for spaced repetition review.
    Bumps importance_score for reviewed items, schedules next review.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        from layla.time_utils import utcnow

        migrate()
        now = utcnow()

        with _conn() as db:
            # Find learnings due for review
            due = db.execute(
                "SELECT id, content, importance_score, next_review_at FROM learnings "
                "WHERE next_review_at IS NOT NULL AND next_review_at <= ? "
                "ORDER BY importance_score DESC LIMIT 10",
                (now,),
            ).fetchall()

            if not due:
                return {"ok": True, "reviewed": 0}

            reviewed = 0
            for row in due:
                row_id = row["id"] if isinstance(row, dict) else row[0]
                importance = float((row["importance_score"] if isinstance(row, dict) else row[2]) or 0.5)

                # SM-2 simplified: increase interval by 2x each review, bump importance
                new_importance = min(1.0, importance + 0.05)
                # Next review in: 1 day, 3 days, 7 days, 14 days, 30 days (based on importance)
                days_until_next = int(2 ** (new_importance * 5))  # 1-32 days
                days_until_next = max(1, min(90, days_until_next))

                import datetime
                next_review = (datetime.datetime.fromisoformat(now) + datetime.timedelta(days=days_until_next)).isoformat()

                db.execute(
                    "UPDATE learnings SET importance_score = ?, next_review_at = ? WHERE id = ?",
                    (new_importance, next_review, row_id),
                )
                reviewed += 1

        if reviewed > 0:
            logger.info("background_intelligence: reviewed %d spaced-repetition items", reviewed)

        return {"ok": True, "reviewed": reviewed}
    except Exception as e:
        logger.debug("spaced_repetition_review: %s", e)
        return {"ok": False, "error": str(e)}


def run_kb_synthesis_check() -> dict[str, Any]:
    """
    Check if any topics have accumulated enough learnings for a KB article.
    When a topic has 10+ learnings and no KB article, auto-build one.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()

        with _conn() as db:
            # Count learnings by tag
            rows = db.execute(
                "SELECT tags, COUNT(*) as cnt FROM learnings "
                "WHERE tags != '' GROUP BY tags HAVING cnt >= 8 "
                "ORDER BY cnt DESC LIMIT 5"
            ).fetchall()

        if not rows:
            return {"ok": True, "candidates": 0}

        candidates = []
        for row in rows:
            tags = (row["tags"] if isinstance(row, dict) else row[0]) or ""
            count = int((row["cnt"] if isinstance(row, dict) else row[1]) or 0)
            if tags and count >= 8:
                candidates.append({"tags": tags, "count": count})

        # Don't auto-build yet -- just flag candidates for future processing
        if candidates:
            logger.info(
                "background_intelligence: %d topics have 8+ learnings (KB synthesis candidates): %s",
                len(candidates),
                ", ".join(c["tags"] for c in candidates[:3]),
            )

        return {"ok": True, "candidates": len(candidates), "topics": candidates[:5]}
    except Exception as e:
        logger.debug("kb_synthesis_check: %s", e)
        return {"ok": False, "error": str(e)}


def run_all_jobs() -> dict[str, Any]:
    """Run all background intelligence jobs. Returns summary of results."""
    t0 = time.monotonic()
    results = {}

    for name, func in [
        ("reflection_scan", run_reflection_scan),
        ("codex_entity_nudge", run_codex_entity_nudge),
        ("codex_relationship_discovery", run_codex_relationship_discovery),
        ("spaced_repetition_review", run_spaced_repetition_review),
        ("kb_synthesis_check", run_kb_synthesis_check),
    ]:
        try:
            results[name] = func()
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
            logger.debug("background_intelligence.%s failed: %s", name, e)

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info("background_intelligence: all jobs completed in %.0fms", elapsed_ms)
    return {"ok": True, "elapsed_ms": elapsed_ms, "jobs": results}

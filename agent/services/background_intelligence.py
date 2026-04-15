"""Lightweight scheduled intelligence jobs (reflection hints, codex nudges)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def run_reflection_scan() -> dict[str, Any]:
    """Scan recent strategy stats; log summary for operators / future UI."""
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
        if hits:
            logger.info("background_reflection: strategy_rows=%d", len(hits))
        return {"ok": True, "rows": len(hits)}
    except Exception as e:
        logger.debug("reflection_scan: %s", e)
        return {"ok": False, "error": str(e)}


def run_codex_entity_nudge() -> dict[str, Any]:
    """Placeholder hook for codex enrichment from summaries (non-destructive)."""
    try:
        from layla.memory.db import get_recent_conversation_summaries

        sums = get_recent_conversation_summaries(n=2)
        return {"ok": True, "summaries_seen": len(sums or [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}

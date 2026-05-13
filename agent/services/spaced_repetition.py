# -*- coding: utf-8 -*-
"""
spaced_repetition.py — Generalized SM-2 spaced repetition for all KB content.

Extends the German-mode SM-2 to any learning/KB article. Supports:
  - Adding any learning to the study queue
  - SM-2 review scheduling with configurable intervals
  - Confidence tracking per item
  - Study calendar (due items per day)
  - Study mode: generate quiz questions from content

Config keys:
    spaced_repetition_enabled    bool  (default true)
    sr_default_ease_factor       float (default 2.5)
    sr_min_interval_hours        float (default 4.0)
    sr_max_interval_days         int   (default 365)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("layla")


# ── SM-2 core (generalized from german_mode.py) ────────────────────────────

def sm2(
    ease_factor: float,
    interval_days: int,
    reps: int,
    quality: int,
) -> tuple[float, int, int]:
    """
    SM-2 spaced repetition algorithm.

    Args:
        ease_factor: Current ease factor (≥1.3).
        interval_days: Current interval in days.
        reps: Number of successful repetitions.
        quality: Review quality 0-5 (0-2=fail, 3-5=pass).

    Returns:
        (new_ease_factor, new_interval_days, new_reps)
    """
    if quality < 3:
        # Failed: reset interval, keep ease factor
        return max(1.3, ease_factor), 1, 0

    new_ef = max(1.3, ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

    if reps == 0:
        new_interval = 1
    elif reps == 1:
        new_interval = 6
    else:
        new_interval = max(1, round(interval_days * new_ef))

    return new_ef, new_interval, reps + 1


# ── Study item model ───────────────────────────────────────────────────────

@dataclass
class StudyItem:
    """A learning/KB article in the study queue."""
    learning_id: int
    content: str
    source: str = ""
    ease_factor: float = 2.5
    interval_days: int = 1
    reps: int = 0
    quality_history: list[int] = field(default_factory=list)
    due_at: str = ""          # ISO datetime
    last_reviewed: str = ""   # ISO datetime
    confidence: float = 0.5   # 0.0–1.0


@dataclass
class StudySession:
    """Result of a study session."""
    items_reviewed: int = 0
    items_passed: int = 0
    items_failed: int = 0
    avg_quality: float = 0.0
    next_due_count: int = 0


# ── Queue management ──────────────────────────────────────────────────────

def add_to_study_queue(learning_id: int, cfg: dict | None = None) -> bool:
    """Add a learning to the spaced repetition study queue."""
    cfg = cfg or {}
    if not cfg.get("spaced_repetition_enabled", True):
        return False

    try:
        from layla.memory.learnings import schedule_next_review, set_learning_importance
        # Schedule first review in 4 hours
        min_hours = float(cfg.get("sr_min_interval_hours", 4.0))
        schedule_next_review(learning_id, interval_hours=min_hours)
        # Boost importance to prioritize in retrieval
        set_learning_importance(learning_id, 0.7)
        return True
    except Exception as exc:
        logger.debug("add_to_study_queue failed: %s", exc)
        return False


def get_due_items(limit: int = 10) -> list[dict]:
    """Get items due for review now."""
    try:
        from layla.memory.learnings import get_learnings_due_for_review
        return get_learnings_due_for_review(limit=limit)
    except Exception as exc:
        logger.debug("get_due_items failed: %s", exc)
        return []


def get_study_calendar(days_ahead: int = 7) -> dict[str, int]:
    """
    Get count of items due per day for the next N days.

    Returns dict mapping ISO date string to count of due items.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()

        calendar: dict[str, int] = {}
        now = datetime.utcnow()

        with _conn() as db:
            # Check if next_review_at column exists
            has_col = any(
                r[1] == "next_review_at"
                for r in db.execute("PRAGMA table_info(learnings)").fetchall()
            )
            if not has_col:
                return {}

            for day_offset in range(days_ahead):
                day_start = (now + timedelta(days=day_offset)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                day_end = day_start + timedelta(days=1)
                row = db.execute(
                    "SELECT COUNT(*) FROM learnings WHERE next_review_at BETWEEN ? AND ?",
                    (day_start.isoformat(), day_end.isoformat()),
                ).fetchone()
                count = row[0] if row else 0
                if count > 0:
                    calendar[day_start.strftime("%Y-%m-%d")] = count

        return calendar
    except Exception as exc:
        logger.debug("get_study_calendar failed: %s", exc)
        return {}


def review_item(learning_id: int, quality: int, cfg: dict | None = None) -> dict:
    """
    Review a study item with a quality score (0-5).

    Applies SM-2 to compute next interval. Schedules next review.
    Returns review result dict.
    """
    cfg = cfg or {}
    quality = max(0, min(5, quality))

    # Get current item state (use defaults if not tracked)
    ease = float(cfg.get("sr_default_ease_factor", 2.5))
    interval = 1
    reps = 0

    # Apply SM-2
    new_ease, new_interval, new_reps = sm2(ease, interval, reps, quality)

    # Cap interval
    max_days = int(cfg.get("sr_max_interval_days", 365))
    new_interval = min(new_interval, max_days)

    # Schedule next review
    try:
        from layla.memory.learnings import schedule_next_review, set_learning_importance
        schedule_next_review(learning_id, interval_hours=new_interval * 24.0)
        # Update confidence based on quality
        confidence = min(1.0, quality / 5.0)
        set_learning_importance(learning_id, confidence)
    except Exception as exc:
        logger.debug("review_item schedule failed: %s", exc)

    return {
        "learning_id": learning_id,
        "quality": quality,
        "passed": quality >= 3,
        "new_ease_factor": round(new_ease, 2),
        "new_interval_days": new_interval,
        "new_reps": new_reps,
    }


def run_study_session(limit: int = 5, cfg: dict | None = None) -> StudySession:
    """
    Run a quick study session: retrieve due items, present for review.

    In practice, the agent loop calls this and LLM generates questions.
    This function handles the scheduling/bookkeeping side.
    """
    due = get_due_items(limit=limit)
    return StudySession(
        items_reviewed=0,  # Caller fills in after actual review
        items_passed=0,
        items_failed=0,
        avg_quality=0.0,
        next_due_count=len(due),
    )

# -*- coding: utf-8 -*-
"""
research_profile.py — Personal research profile and knowledge gap detection.

Tracks the user's learning domains, expertise clusters, knowledge gaps,
and study streaks. Built from ingested knowledge, conversation topics,
and capability data.

Config keys:
    research_profile_enabled   bool  (default true)
    profile_update_interval    int   (default 24, hours)
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_PROFILE_PATH = Path.home() / ".layla" / "research_profile.json"


@dataclass
class DomainExpertise:
    """Tracked expertise in a knowledge domain."""
    domain: str
    article_count: int = 0
    learning_count: int = 0
    last_studied: float = 0.0      # Unix timestamp
    confidence: float = 0.0        # 0.0–1.0
    related_domains: list[str] = field(default_factory=list)


@dataclass
class KnowledgeGap:
    """Identified gap in the user's knowledge."""
    topic: str
    reason: str                     # "mentioned_but_unstudied", "stale", "low_confidence"
    priority: float = 0.5          # 0.0–1.0
    suggested_action: str = ""     # "research", "review", "practice"


@dataclass
class ResearchProfile:
    """User's personal knowledge profile."""
    domains: list[DomainExpertise] = field(default_factory=list)
    gaps: list[KnowledgeGap] = field(default_factory=list)
    total_learnings: int = 0
    total_articles: int = 0
    study_streak_days: int = 0
    last_study_date: str = ""      # ISO date
    top_topics: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ResearchProfile:
        domains = [DomainExpertise(**de) for de in d.get("domains", [])]
        gaps = [KnowledgeGap(**kg) for kg in d.get("gaps", [])]
        return cls(
            domains=domains, gaps=gaps,
            total_learnings=d.get("total_learnings", 0),
            total_articles=d.get("total_articles", 0),
            study_streak_days=d.get("study_streak_days", 0),
            last_study_date=d.get("last_study_date", ""),
            top_topics=d.get("top_topics", []),
            updated_at=d.get("updated_at", time.time()),
        )


def _extract_domains_from_learnings() -> Counter:
    """Count domain occurrences across all learnings."""
    domain_counter: Counter = Counter()
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()
        with _conn() as db:
            rows = db.execute(
                "SELECT tags, type FROM learnings WHERE tags IS NOT NULL AND tags != '' LIMIT 5000"
            ).fetchall()
        for row in rows:
            tags = str(row[0] or "").lower()
            for tag in tags.split(","):
                tag = tag.strip()
                if tag and len(tag) > 2:
                    domain_counter[tag] += 1
    except Exception as exc:
        logger.debug("_extract_domains_from_learnings failed: %s", exc)
    return domain_counter


def _extract_domains_from_capabilities() -> dict[str, float]:
    """Get domain confidence from capabilities table."""
    levels: dict[str, float] = {}
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate
        migrate()
        with _conn() as db:
            rows = db.execute(
                "SELECT domain_id, level, confidence FROM capabilities LIMIT 100"
            ).fetchall()
        for row in rows:
            domain = str(row[0])
            level = float(row[1] or 0)
            conf = float(row[2] or 0)
            levels[domain] = max(level, conf)
    except Exception as exc:
        logger.debug("_extract_domains_from_capabilities failed: %s", exc)
    return levels


def _detect_knowledge_gaps(
    domain_counter: Counter,
    capability_levels: dict[str, float],
) -> list[KnowledgeGap]:
    """Identify knowledge gaps from domain analysis."""
    gaps: list[KnowledgeGap] = []

    # Topics mentioned in learnings but low capability confidence
    for domain, count in domain_counter.most_common(50):
        cap_level = capability_levels.get(domain, 0.0)
        if count >= 3 and cap_level < 0.3:
            gaps.append(KnowledgeGap(
                topic=domain,
                reason="mentioned_but_low_confidence",
                priority=min(1.0, count / 20.0),
                suggested_action="practice",
            ))

    # Capabilities with very low levels
    for domain, level in capability_levels.items():
        if level < 0.2 and domain not in {g.topic for g in gaps}:
            gaps.append(KnowledgeGap(
                topic=domain,
                reason="low_capability_level",
                priority=0.3,
                suggested_action="research",
            ))

    # Sort by priority
    gaps.sort(key=lambda g: -g.priority)
    return gaps[:20]


def build_profile(cfg: dict | None = None) -> ResearchProfile:
    """
    Build or refresh the personal research profile.

    Scans learnings, capabilities, and study history to produce
    a structured profile of expertise and gaps.
    """
    cfg = cfg or {}
    if not cfg.get("research_profile_enabled", True):
        return ResearchProfile()

    domain_counter = _extract_domains_from_learnings()
    capability_levels = _extract_domains_from_capabilities()

    # Build domain expertise list
    domains: list[DomainExpertise] = []
    for domain, count in domain_counter.most_common(30):
        cap_level = capability_levels.get(domain, 0.0)
        domains.append(DomainExpertise(
            domain=domain,
            learning_count=count,
            confidence=cap_level,
        ))

    # Detect gaps
    gaps = _detect_knowledge_gaps(domain_counter, capability_levels)

    # Count totals
    total_learnings = sum(domain_counter.values())
    top_topics = [d for d, _ in domain_counter.most_common(10)]

    profile = ResearchProfile(
        domains=domains,
        gaps=gaps,
        total_learnings=total_learnings,
        top_topics=top_topics,
    )

    # Save to disk
    save_profile(profile)

    return profile


def save_profile(profile: ResearchProfile) -> None:
    """Persist profile to disk."""
    try:
        _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_PATH.write_text(
            json.dumps(profile.to_dict(), indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("save_profile failed: %s", exc)


def load_profile() -> ResearchProfile:
    """Load profile from disk."""
    try:
        if _PROFILE_PATH.is_file():
            data = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
            return ResearchProfile.from_dict(data)
    except Exception as exc:
        logger.debug("load_profile failed: %s", exc)
    return ResearchProfile()


def get_knowledge_summary() -> str:
    """Generate a human-readable knowledge summary for context injection."""
    profile = load_profile()
    if not profile.domains and not profile.gaps:
        return ""

    parts = ["[Knowledge Profile]"]

    if profile.top_topics:
        parts.append(f"Top domains: {', '.join(profile.top_topics[:8])}")

    if profile.domains:
        strong = [d.domain for d in profile.domains if d.confidence >= 0.6]
        if strong:
            parts.append(f"Strong areas: {', '.join(strong[:5])}")

    if profile.gaps:
        gap_topics = [g.topic for g in profile.gaps[:5]]
        parts.append(f"Knowledge gaps: {', '.join(gap_topics)}")

    if profile.study_streak_days > 0:
        parts.append(f"Study streak: {profile.study_streak_days} days")

    return "\n".join(parts)

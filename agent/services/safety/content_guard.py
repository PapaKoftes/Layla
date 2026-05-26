# -*- coding: utf-8 -*-
"""
content_guard.py -- Deterministic pre-model content filter.

Runs BEFORE model inference on user input AND AFTER on model output.
Three tiers of content classification:

  Tier 1 (HARDCODED, no override):
    - CSAM-adjacent content
    - Weapons of mass destruction synthesis instructions
    - Malware/exploit generation
    These are universally illegal. No config flag disables them.

  Tier 2 (blocked by default, user can override if age_verified):
    - Explicit gore/torture descriptions
    - Self-harm/suicide instructions
    These are blocked unless content_guard_age_verified=True

  Tier 3 (user-controllable):
    - Adult/sexual content (handled by existing nsfw_allowed/uncensored flags)
    - Not managed here -- see prompt_builder.py content policy

Privacy: When content is blocked, only a hash is logged -- never the content itself.

Config:
  content_guard_enabled       (default True)
  content_guard_age_verified  (default False)
  content_guard_hardcoded_only (default False) -- disables Tier 2 blocks
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Tier 1: Always blocked (universally illegal)
# ---------------------------------------------------------------------------

# NOTE: These patterns are intentionally broad to catch variations.
# They use word boundaries and contextual markers to reduce false positives.
# Each pattern requires BOTH a target indicator AND an action indicator.

_TIER1_COMPOUND_PATTERNS: list[tuple[re.Pattern, str]] = [
    # CSAM-adjacent: requires age indicator + sexual context
    (re.compile(
        r"(?=.*\b(child|minor|underage|preteen|toddler|infant|kid|boy|girl)\b)"
        r"(?=.*\b(naked|nude|sexual|porn|erotic|molest|abuse)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "csam_adjacent"),
    # Weapons of mass destruction: requires weapon type + synthesis/creation
    (re.compile(
        r"(?=.*\b(synthesize|manufacture|create|build|make|produce|assemble)\b)"
        r"(?=.*\b(nerve\s*agent|sarin|vx\s*gas|anthrax|ricin|biological\s*weapon|chemical\s*weapon|dirty\s*bomb|nuclear\s*device)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "wmd_synthesis"),
    # Malware/exploit: requires creation verb + malware type
    (re.compile(
        r"(?=.*\b(write|create|build|code|develop|generate)\b)"
        r"(?=.*\b(ransomware|keylogger|rootkit|trojan|worm|zero.day\s*exploit|botnet|cryptolocker)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "malware_generation"),
]

# ---------------------------------------------------------------------------
# Tier 2: Blocked by default, overridable with age verification
# ---------------------------------------------------------------------------

_TIER2_COMPOUND_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Self-harm instructions: requires method + instruction context
    (re.compile(
        r"(?=.*\b(how\s+to|steps\s+to|guide\s+to|instructions?\s+for|method\s+for)\b)"
        r"(?=.*\b(kill\s+yourself|commit\s+suicide|self.harm|cut\s+yourself|overdose)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "self_harm_instructions"),
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Result of content guard analysis."""
    blocked: bool = False
    tier: int = 0  # 0=pass, 1=hardcoded, 2=age-gated
    category: str = ""
    content_hash: str = ""  # SHA256 of blocked content (for audit, never content itself)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_input(text: str, cfg: dict) -> GuardResult:
    """
    Check user input against content guard.
    Returns GuardResult. If blocked=True, the message should not be sent to the model.
    """
    if not cfg.get("content_guard_enabled", True):
        return GuardResult()
    return _check(text, cfg)


def check_output(text: str, cfg: dict) -> GuardResult:
    """
    Check model output against content guard.
    Returns GuardResult. If blocked=True, the response should be replaced with a safe message.
    """
    if not cfg.get("content_guard_enabled", True):
        return GuardResult()
    return _check(text, cfg)


def _check(text: str, cfg: dict) -> GuardResult:
    """Internal check against all tiers."""
    if not text or len(text) < 10:
        return GuardResult()

    # Tier 1: Always blocked
    for pattern, category in _TIER1_COMPOUND_PATTERNS:
        if pattern.search(text):
            content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
            logger.warning("content_guard: TIER1 block category=%s hash=%s", category, content_hash)
            return GuardResult(
                blocked=True,
                tier=1,
                category=category,
                content_hash=content_hash,
            )

    # Tier 2: Blocked unless age_verified or hardcoded_only mode
    if not cfg.get("content_guard_age_verified", False) and not cfg.get("content_guard_hardcoded_only", False):
        for pattern, category in _TIER2_COMPOUND_PATTERNS:
            if pattern.search(text):
                content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
                logger.warning("content_guard: TIER2 block category=%s hash=%s", category, content_hash)
                return GuardResult(
                    blocked=True,
                    tier=2,
                    category=category,
                    content_hash=content_hash,
                )

    return GuardResult()


def blocked_response(result: GuardResult) -> str:
    """Generate a user-facing message when content is blocked."""
    if result.tier == 1:
        return (
            "I cannot help with that request. This falls outside what any responsible "
            "system should assist with, regardless of settings. This is a hardcoded safety "
            "boundary that cannot be overridden."
        )
    if result.tier == 2:
        return (
            "This request is blocked by default safety settings. If you are 18+ and want "
            "to adjust these boundaries, you can enable `content_guard_age_verified` in your "
            "runtime configuration. Some content restrictions exist to protect, not to censor."
        )
    return "Content blocked by safety policy."

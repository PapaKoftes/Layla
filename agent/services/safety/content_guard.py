# -*- coding: utf-8 -*-
"""
content_guard.py -- Deterministic pre-model content filter.

Runs BEFORE model inference on user input AND AFTER on model output.
Three tiers of content classification:

  Tier 1 (no per-tier override):
    - CSAM-adjacent content
    - Weapons of mass destruction synthesis instructions
    - Malware/exploit generation
    No PER-TIER flag disables Tier 1 (unlike Tier 2). NOTE: content_guard_enabled=False disables
    the ENTIRE guard, Tier 1 included.

  LIMITATIONS (do not oversell this): detection is deterministic keyword / co-occurrence matching,
  NOT a semantic classifier -- paraphrase, translation, or synonyms can pass it. Treat it as a fast
  first-line tripwire, not a complete safety boundary; the real enforcement gate is the approval
  system. Fail-open vs fail-closed is the CALLER's responsibility -- this module has no internal error
  handling. As of this pass, all wrapping call sites (the /agent router, the /v1 OpenAI-compatible
  router, and the clean_reply_text finalizer) FAIL CLOSED on an internal error: they withhold/decline
  rather than pass content through. If you add a new call site, wrap it the same way.

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
    # CSAM-adjacent: an AGE indicator and a SEXUAL indicator CO-OCCURRING within a
    # sentence/short-paragraph window (<=250 chars, either order). Narrowed vs. the legacy
    # rule (which paired ANY age token with ANY sexual token anywhere in a 20k-char window)
    # to stop blocking ordinary adult-between-adults content while KEEPING CSAM coverage:
    #   (a) age terms are REAL age indicators only -- bare boy/girl removed (adults use them for
    #       each other); "little girl"/"young boy" kept as age-qualified compounds so dropping bare
    #       "girl" does NOT open a CSAM hole. BUT bare `kid` is KEPT (adversarial verify caught the
    #       first pass dropping it -- "kid" is an unambiguous child word, unlike boy/girl, so
    #       "abuse of a kid" must still block), and `teenager|adolescent|schoolgirl|schoolboy` are
    #       ADDED (unambiguous minors that adult prose does not use as endearments). Deliberately NOT
    #       added: bare `teen` and numeric ages -- an "18-year-old" is an adult, and forcing those
    #       would re-block the consensual adult content this whole change exists to allow.
    #       `one` dropped from the compound target so "young one"/"baby, ..." adult endearments pass.
    #   (b) proximity-scoped (<=250 chars) instead of the whole 20k blob, so an unrelated
    #       "girl" and "erotic" thousands of chars apart can no longer co-trigger.
    # re.DOTALL is dropped (no '.' used; spanning is the explicit [\s\S]); the lazy {0,250}?
    # bound is required. Only this tuple changed -- WMD/malware Tier-1 and all Tier-2 untouched.
    (re.compile(
        r"(?:"
        r"(?:\b(?:child|minor|underage|preteen|toddler|infant|kid|teenager|adolescent|schoolgirl|schoolboy)\b"
        r"|(?:little|young|small|tiny|prepubescent|baby)\s+(?:boy|girl|kid|child))"
        r"[\s\S]{0,250}?\b(?:naked|nude|sexual|porn|erotic|molest|abuse)\b"
        r")|(?:"
        r"\b(?:naked|nude|sexual|porn|erotic|molest|abuse)\b[\s\S]{0,250}?"
        r"(?:\b(?:child|minor|underage|preteen|toddler|infant|kid|teenager|adolescent|schoolgirl|schoolboy)\b"
        r"|(?:little|young|small|tiny|prepubescent|baby)\s+(?:boy|girl|kid|child))"
        r")",
        re.IGNORECASE,
    ), "csam_adjacent"),
    # Weapons of mass destruction: requires weapon type + synthesis/creation
    #
    # PERF (ReDoS fix): the `\A` anchor is load-bearing, not cosmetic. These "contains X AND
    # contains Y" rules are built entirely from zero-width lookaheads, so an UNANCHORED
    # re.search retried them at every one of the ~20k start positions, and each retry rescanned
    # the rest of the string (`.*` + backtrack) -- O(n^2). Measured on a 20k input that matches
    # nothing (ordinary long prose): ~9s PER PATTERN, ~47s for one check_input call. check_input
    # runs on every user message and check_output re-scans the GROWING buffer every stride during
    # streaming, so that was a live hang on the turn path, not just a slow test.
    #
    # Anchoring is semantically identical here, not a narrowing: `(?=.*X)` at position i asserts
    # "X occurs at or after i". Position 0 is the most permissive case -- if it fails there, X is
    # absent from the whole string, so every i>0 (a subset of the tail) must fail too. Only
    # position 0 can ever succeed, so trying only position 0 loses no match. Coverage is
    # unchanged; only the 20k wasted retries are gone.
    (re.compile(
        r"\A(?=.*\b(synthesize|manufacture|create|build|make|produce|assemble)\b)"
        r"(?=.*\b(nerve\s*agent|sarin|vx\s*gas|anthrax|ricin|biological\s*weapon|chemical\s*weapon|dirty\s*bomb|nuclear\s*device)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "wmd_synthesis"),
    # Malware/exploit: requires creation verb + malware type. `\A`: see the ReDoS note above.
    (re.compile(
        r"\A(?=.*\b(write|create|build|code|develop|generate)\b)"
        r"(?=.*\b(ransomware|keylogger|rootkit|trojan|worm|zero.day\s*exploit|botnet|cryptolocker)\b)",
        re.IGNORECASE | re.DOTALL,
    ), "malware_generation"),
]

# ---------------------------------------------------------------------------
# Tier 2: Blocked by default, overridable with age verification
# ---------------------------------------------------------------------------

_TIER2_COMPOUND_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Self-harm instructions: requires method + instruction context.
    # `\A`: same ReDoS fix as the Tier-1 lookahead rules -- see the note there.
    (re.compile(
        r"\A(?=.*\b(how\s+to|steps\s+to|guide\s+to|instructions?\s+for|method\s+for|painless(?:ly)?|best\s+way)\b)"
        r"(?=.*\b(kill\s+yourself|commit\s+suicide|self.harm|cut\s+yourself|overdose|"
        r"end\s+(?:my|your|it)\s+(?:life|all)|take\s+my\s+own\s+life)\b)",
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


# Leetspeak → letter, so "r@ns0mw4re" normalises to "ransomware" for matching only.
_LEET = str.maketrans({"@": "a", "4": "a", "3": "e", "1": "i", "!": "i", "0": "o",
                       "5": "s", "$": "s", "7": "t", "+": "t", "8": "b", "9": "g"})


def _match_variants(text: str) -> list[str]:
    """The forms an obfuscated payload might take — checked so evasions hit the same
    compound patterns: original, leetspeak-decoded, and de-spaced ('r a n s o m' → …)."""
    # Security review Finding 4: cap the normalized window so building 4 copies + running
    # the de-space regex can't be a CPU/RAM amplifier on a huge input. Malicious payloads
    # are short; real prose past ~20KB doesn't need de-obfuscation.
    text = (text or "")[:20_000]
    low = text.lower()
    deleet = low.translate(_LEET)
    # collapse runs of single chars separated by whitespace/punctuation into one token
    _despace_re = re.compile(r"\b(\w)(?:[\s.\-_*]+(\w)\b)+")

    def _collapse(m):
        return "".join(re.findall(r"\w", m.group(0)))

    # A single-char run is AMBIGUOUS: "a n t h r a x" is the one word "anthrax", but "a k e y l o g g e r"
    # is a lone word "a" shielding "keylogger" — collapsing the whole run to "akeylogger" destroys the
    # \bkeylogger\b boundary the Tier-1 pattern needs, so a single leading letter defeated the check.
    # Both readings are indistinguishable without a dictionary, so emit BOTH: full collapse (still catches
    # "anthrax") and a first-letter-split (catches the "a"+payload prefix). Purely additive.
    def _split_lead(m):
        chars = re.findall(r"\w", m.group(0))
        return (chars[0] + " " + "".join(chars[1:])) if len(chars) > 1 else "".join(chars)

    # Treat a run of 2+ whitespace as a WORD boundary: spacing a phrase out letter-by-letter leaves a
    # WIDER gap between words ("w r i t e   r a n s o m w a r e") than between letters, so splitting on
    # \s{2,} first stops the verb and the payload from gluing into one unmatchable token
    # ("writeransomware") — the second de-space evasion. Bounded work (input already capped at 20KB).
    _segs = re.split(r"\s{2,}", low)
    despaced = " ".join(_despace_re.sub(_collapse, s) for s in _segs)
    despaced_split = " ".join(_despace_re.sub(_split_lead, s) for s in _segs)
    despaced_deleet = despaced.translate(_LEET)
    despaced_split_deleet = despaced_split.translate(_LEET)
    # de-dup while preserving order
    seen, out = set(), []
    for v in (text, deleet, despaced, despaced_split, despaced_deleet, despaced_split_deleet):
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _check(text: str, cfg: dict) -> GuardResult:
    """Internal check against all tiers."""
    if not text or len(text) < 10:
        return GuardResult()

    _variants = _match_variants(text)

    # Tier 1: Always blocked
    for pattern, category in _TIER1_COMPOUND_PATTERNS:
        if any(pattern.search(v) for v in _variants):
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
            if any(pattern.search(v) for v in _variants):
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
            "system should assist with, regardless of settings. This boundary is not unlocked by "
            "age-verification or any per-tier content setting."
        )
    if result.tier == 2:
        return (
            "This request is blocked by default safety settings. If you are 18+ and want "
            "to adjust these boundaries, you can enable `content_guard_age_verified` in your "
            "runtime configuration. Some content restrictions exist to protect, not to censor."
        )
    return "Content blocked by safety policy."

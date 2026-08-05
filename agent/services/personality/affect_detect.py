"""Detect an EMOTIONAL-SUPPORT turn — the person is sharing something personally hard (distress,
a relationship, grief, loneliness) and needs to be *heard*, not handed a task plan.

This is the missing signal behind the companion-quality failure: Layla's whole response path is wired
for terse task-execution, so an "I'm in pain" message routed to the coding blade + an anti-warmth
output-discipline and came back clinical (advice lists, "draft a message", "seek counseling"). This
detector lets routing pick a warm aspect and lets the prompt flip to warmth-first on these turns.

Deliberately errs toward warmth: for a companion, a false-positive (a slightly-too-gentle reply to a
neutral message) is far cheaper than a false-negative (a clinical reply to someone in pain). The
patterns require an actual emotion/relationship word, so ordinary technical talk ("I feel like this
code is wrong", "the function hurts performance") does not trip it.
"""
from __future__ import annotations

import re

# Relationship / bond context.
_RELATIONAL = re.compile(
    r"\b(girlfriend|boyfriend|my (partner|wife|husband|gf|bf)|our relationship|"
    r"\brelationship\b|break(ing)?\s?up|broke up|divorce|marriage|\bmy ex\b|in love with|dating)\b",
    re.IGNORECASE,
)
# Raw distress / affect words.
_DISTRESS = re.compile(
    r"\b(hurt(ing)?|in pain|heartbroken|heartbreak|devastated|depress(ed|ion|ing)|anxious|anxiety|"
    r"lonely|so alone|overwhelmed|crying|\bcry(ing)?\b|grief|grieving|hopeless|worthless|miserable|"
    r"suicidal|numb inside|empty inside|falling apart|at the end of my rope|end of my rope|"
    r"can'?t take (it|this) any\s?more|breaking down)\b",
    re.IGNORECASE,
)
# Explicitly asking to be heard / reassured / to vent.
_SUPPORT = re.compile(
    r"\b(reassur(e|ance)|just need to (talk|vent)|need to vent|comfort me|hold my hand|"
    r"i just need you|i need you to (understand|listen|hear|be here)|feel(ing)? (un)?heard|"
    r"i (feel|felt) (so |really |)?(alone|lonely|hurt|sad|scared|unwanted|unloved|worthless|"
    r"hopeless|empty|rejected|abandoned|dismissed|invisible|like i don'?t matter))\b",
    re.IGNORECASE,
)


def is_affective_turn(text: str) -> bool:
    """True when the message is an emotional-support turn (distress / relationship / needing to be
    heard), so routing + prompt can respond as a present, warm companion rather than a task-doer."""
    if not text or not isinstance(text, str):
        return False
    t = text.strip()
    if len(t) < 3:
        return False
    return bool(_DISTRESS.search(t) or _SUPPORT.search(t) or _RELATIONAL.search(t))

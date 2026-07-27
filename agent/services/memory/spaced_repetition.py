# -*- coding: utf-8 -*-
"""
spaced_repetition.py — the ONE SM-2 implementation for the whole tree (Plan #22).

WHY THIS MODULE EXISTS AGAIN
    SM-2 had been hand-rolled three times, each drifting from the others:
      - services/infrastructure/german_mode.py::_sm2   (the live flashcard deck)
      - layla/tools/impl/memory.py::_sm2               (the learnings review tool + loop)
      - an old services/memory/spaced_repetition.py    (deleted 2026-07-17 — it carried a big
        StudyItem/StudySession/queue scaffold with ZERO production callers, which is why it went)
    Two of the copies disagreed on real behaviour: one dropped the ease factor on a failed recall
    and one didn't; one grew the interval off the ease produced BY the review and one off the stale
    pre-review ease. A fix in one never reached the other.

    RESEARCH DECISION (Plan #22): keep the in-house SM-2 — do NOT pull in an external library
    (py-fsrs etc.). Instead collapse the duplicates into this single module so a correctness fix
    lands once. Both remaining `_sm2` shims (german deck + learnings path) now delegate here, and
    the scheduled learnings review loop calls `sm2` directly. This module carries ONLY what is
    actually wired — no queue scaffold — so the dead-symbols gate stays green.
"""
from __future__ import annotations

# SM-2's ease factor floor. Below it the interval multiplier collapses and a repeatedly-failed item
# is driven toward a schedule it can never climb out of (due in the past, forever). SM-2 clamps here.
EASE_FLOOR = 1.3
DEFAULT_EASE = 2.5


def sm2(*, ease: float, interval_days: int, reps: int, quality: int) -> tuple[float, int, int]:
    """One SM-2 step. Returns ``(ease, interval_days, reps)``.

    ``quality`` is clamped to 0-5. A grade below 3 is a failed recall: the repetition streak resets
    and the item comes back tomorrow (interval = 1 day). A grade of 3+ grows the interval along the
    standard ladder 1 -> 6 -> round(interval * ease).

    Two correctness properties the old duplicates each got half-right, pinned here as the contract:

      * The ease factor is updated on EVERY grade via SM-2's EF formula (it can dip on a weak pass
        and always drops on failure), and is floored at ``EASE_FLOOR`` — including on the failure
        path, where one old copy left it unclamped.
      * The interval is computed from the ease produced BY THIS review, never the stale ease the item
        carried in, and is floored at 1 day so a low ease can't round it to a permanently-overdue 0.
    """
    q = max(0, min(5, int(quality)))
    # Classic SM-2 EF update — applied for all q, including failures — then floored.
    new_ease = max(EASE_FLOOR, float(ease) + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))

    if q < 3:
        return new_ease, 1, 0

    reps = int(reps) + 1
    if reps == 1:
        new_interval = 1
    elif reps == 2:
        new_interval = 6
    else:
        new_interval = max(1, int(round(max(1, int(interval_days)) * new_ease)))
    return new_ease, new_interval, reps


def self_grade_learning(
    *,
    importance: float | None = None,
    confidence: float | None = None,
    age_days: float | None = None,
) -> int:
    """Deterministic 0-5 self-grade for an UNATTENDED review pass (Plan #22 review loop).

    There is no user present to rate recall in a batch loop, and an LLM grade per item is far too
    slow. So we proxy "how well is this memory holding up?" from stored signals only:

      * strength = mean of the item's confidence and importance (each 0-1). A solid, important
        learning grades as a strong recall (4-5) so its interval keeps growing; a weak one grades
        low (1-2) so it resurfaces sooner instead of drifting out of sight.
      * a staleness penalty: an item that has gone a long time without a review loses a grade (or
        two past ~6 months), which shortens its next interval — the batch equivalent of "I hadn't
        seen this in ages and barely remembered it".

    Fully deterministic and cheap, so the whole batch is a few microseconds. ``confidence`` defaults
    to ``importance`` when unknown (the due-item query exposes importance but not confidence).
    """
    imp = 0.5 if importance is None else max(0.0, min(1.0, float(importance)))
    conf = imp if confidence is None else max(0.0, min(1.0, float(confidence)))
    strength = 0.5 * conf + 0.5 * imp

    if strength >= 0.80:
        grade = 5
    elif strength >= 0.60:
        grade = 4
    elif strength >= 0.40:
        grade = 3
    elif strength >= 0.20:
        grade = 2
    else:
        grade = 1

    age = max(0.0, float(age_days or 0.0))
    if age > 180:
        grade -= 2
    elif age > 60:
        grade -= 1
    return max(0, min(5, grade))

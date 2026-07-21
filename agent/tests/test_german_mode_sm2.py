"""german_mode._sm2 — the SM-2 that drives the ONLY real flashcard UI.

WHY THIS FILE EXISTS. There were two SM-2 implementations in this tree:

  services/memory/spaced_repetition.py  — correct, 24 passing tests, ZERO production importers
  services/infrastructure/german_mode.py::_sm2 — a buggier clone, wired to the live flashcard deck

Every test pointed at the copy nobody ran. The copy the user actually hits had no test at all, so its
defects were free to persist: the deck silently mis-scheduled and nothing anywhere went red. The dead
module has now been deleted; these tests port its correctness properties onto the LIVE function, which
is where they should have been pointed all along.

Do NOT re-hand-roll SM-2 to satisfy these. If the generalized study-queue feature is ever wanted, adopt
`fsrs` (MIT, single dep) rather than growing a third copy of this algorithm.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from services.infrastructure.german_mode import _sm2  # noqa: E402

# ── Ported from the deleted services/memory/spaced_repetition.py tests ────────────────────────────────

def test_sm2_grows_and_resets():
    """The baseline SM-2 schedule shape: 1 day, 6 days, then interval*ease; failure resets to 1."""
    ef, iv, reps = _sm2(2.5, 0, 0, 5)        # first success
    assert (iv, reps) == (1, 1)
    ef, iv, reps = _sm2(ef, iv, reps, 5)     # second success
    assert (iv, reps) == (6, 2)
    ef2, iv2, reps2 = _sm2(ef, iv, reps, 5)  # third success → interval * ease
    assert iv2 > 6 and reps2 == 3
    _ef3, iv3, reps3 = _sm2(ef2, iv2, reps2, 1)  # failure → reset
    assert iv3 == 1 and reps3 == 0


# ── The two defects, pinned ───────────────────────────────────────────────────────────────────────────

def test_interval_uses_the_NEW_ease_not_the_stale_one():
    """BUG 2 (live, reachable): the reps>=2 branch multiplied by the ease from BEFORE this review.

    Every interval past the second review was scheduled off the PREVIOUS review's ease, so the schedule
    always lagged one step behind the user's actual performance — growing too slowly after a good streak
    and too fast after a bad one. Silent: a lagging interval still looks like a plausible date.

    quality=5 on (ease 2.5, interval 6, reps 2):
        new_ef = 2.5 + 0.1 - 0*(...) = 2.6
        correct : round(6 * 2.6) = 16
        buggy   : round(6 * 2.5) = 15   ← stale ease

    This assertion is the whole guard: revert `new_ef` to `ease_factor` on that line and it reads 15.
    """
    new_ef, new_interval, new_reps = _sm2(2.5, 6, 2, 5)
    assert new_ef == 2.6
    assert new_reps == 3
    assert new_interval == 16, (
        "interval must be computed from the ease produced BY THIS REVIEW (2.6), not the ease the card "
        "carried into it (2.5). 15 means the stale-ease bug is back."
    )


def test_ease_keeps_its_1_3_floor_on_failure():
    """BUG 1 (latent, NOT reachable via the live deck — measured, not assumed).

    SM-2 floors the ease factor at 1.3; below it the interval multiplier collapses and a repeatedly
    failed card is driven toward a schedule it cannot climb out of. The failure branch returned the
    input ease UNCLAMPED.

    REACHABILITY, MEASURED — I traced every write to `flashcards.ease_factor`:
      - the only INSERT (german_mode.py, add_flashcard) omits the column  -> DEFAULT 2.5
      - the only UPDATE (review_flashcard) writes `_sm2`'s own output, and the success branch is
        already `max(1.3, ...)`
    So a live card's ease can never enter `_sm2` below 1.3, and this branch cannot currently be reached
    with a sub-floor value. It is fixed as a CONTRACT of the function, not as a live user-facing repair
    — the next caller (an import path, a seeded deck, a config-supplied default) would reach it, and the
    cost of being right here is one `max()`.
    """
    ease, interval, reps = _sm2(1.0, 10, 5, 0)
    assert (interval, reps) == (1, 0)
    assert ease >= 1.3, "SM-2's ease factor has a hard floor of 1.3, including on the failure path"


def test_interval_never_rounds_below_one_day():
    """A low ease could round a 1-day interval to 0 — a card due in the past, forever."""
    _ef, interval, _reps = _sm2(1.3, 1, 2, 3)
    assert interval >= 1, "an interval of 0 makes the card permanently overdue"

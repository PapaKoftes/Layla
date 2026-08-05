"""BUG regression: onboarding complete() was not idempotent. advance() auto-completes on the last
stage AND the UI separately POSTs /onboarding/complete, so complete() ran twice — inserting the
"Onboarding interview completed…" timeline event a second time (the duplicate the operator saw in
the Intelligence timeline) and re-applying personality prefs. complete() must be a no-op on a second
call."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _count_complete_events():
    from layla.memory.user_profile import get_recent_timeline_events
    evs = get_recent_timeline_events(n=200)
    return sum(1 for e in evs if e.get("event_type") == "onboarding_complete"
               or "Onboarding interview completed" in str(e.get("content", "")))


def test_complete_is_idempotent_no_duplicate_timeline_event(isolated_db):
    from services.user.onboarding_interview import OnboardingInterview

    oi = OnboardingInterview()
    oi.start()
    r1 = oi.complete()
    assert r1.get("ok") is True and r1.get("is_complete") is True
    after_first = _count_complete_events()
    assert after_first == 1, f"expected exactly one completion event, got {after_first}"

    # Second complete() (the double-completion path) must NOT add another event.
    r2 = oi.complete()
    assert r2.get("ok") is True and r2.get("is_complete") is True, "2nd complete should still report complete"
    after_second = _count_complete_events()
    assert after_second == 1, f"complete() re-added the timeline event: {after_second} events"

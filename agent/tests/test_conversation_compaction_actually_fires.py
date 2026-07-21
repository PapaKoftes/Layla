"""Conversation compaction was gated on a condition its own buffer could never satisfy.

`conversation_summaries` had 0 rows for the entire life of the database — not because the writer was
missing, broken, or uncalled, but because it sits past an early-return that nothing could reach:

    append_conv_history -> _compact_bg (daemon thread, every assistant turn)
      -> maybe_auto_compact -> summarize_history
         `if total <= threshold: return messages`     <-- always taken
         add_conversation_summary(...)                <-- never reached

The threshold is a share of the MODEL WINDOW (n_ctx 8192 * 0.6 = 4915 tokens). The buffer it
measures is `shared_state._conv_histories[cid]`, a `deque(maxlen=20)`. A ring buffer cannot build
token pressure — at capacity it discards from the left — so its token count plateaus at "the most
recent 20 messages" forever. Measured on the live DB that plateau is ~1428 tokens, 29% of the
threshold. Crossing it would require all 20 messages to average 246 tokens simultaneously, while
assistant replies are capped at completion_max_tokens=320 and user messages average 15.

The consequence was not merely a missing feature. Turns older than 20 were DELETED by rolloff
instead of being distilled, and five long-term writers sit behind that same gate:
add_conversation_summary, add_relationship_memory, add_timeline_event, create_episode and
add_episode_event — which is why relationship_memory and the episode tables are also empty.

The fix compacts on OCCUPANCY instead, a few slots before rolloff destroys anything.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from services.context.context_manager import (
    maybe_auto_compact,
    summarize_history,
    token_estimate_messages,
)

GOOD_SUMMARY = "[Earlier conversation summary]\n- discussed the auth refactor"
FALLBACK = "[Earlier conversation (truncated)]"


def _history(n: int, user_tokens: int = 15, asst_tokens: int = 128) -> list[dict]:
    """Realistic traffic: short user turns, assistant replies bounded by completion_max_tokens."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append({"role": "user", "content": "w " * user_tokens})
        else:
            out.append({"role": "assistant", "content": "w " * asst_tokens})
    return out


def test_a_full_ring_buffer_cannot_reach_the_token_threshold():
    """The arithmetic that made the gate unreachable. This is the regression guard on the premise.

    If this ever fails it means message sizes grew enough that pressure-based compaction would fire
    on its own — at which point the force path is belt-and-braces rather than the only trigger.
    """
    full_ring = _history(20)
    plateau = token_estimate_messages(full_ring)
    threshold = int(8192 * 0.6)
    assert plateau < threshold, "premise check: a full ring should sit under the pressure threshold"
    assert plateau < threshold * 0.5, (
        f"a full 20-message ring is {plateau} tokens vs a {threshold}-token threshold "
        f"({plateau / threshold:.0%}) — pressure is the wrong signal for a fixed-length buffer"
    )


def test_without_force_a_full_ring_never_compacts():
    """Reproduces the shipped bug exactly: nothing is summarized, nothing is persisted."""
    with patch("services.context.context_manager._compress_to_summary", return_value=GOOD_SUMMARY) as spy:
        out = summarize_history(_history(20), n_ctx=8192, threshold_ratio=0.6, force=False)
    spy.assert_not_called()
    assert len(out) == 20, "unforced compaction must leave a sub-threshold history untouched"


def test_force_compacts_and_persists_the_summary():
    """The fix: with force, the writer past the gate is finally reached."""
    with patch("services.context.context_manager._compress_to_summary", return_value=GOOD_SUMMARY), \
         patch("layla.memory.db.add_conversation_summary") as add_summary, \
         patch("layla.memory.db.add_relationship_memory") as add_rel, \
         patch("layla.memory.db.add_timeline_event", return_value=1), \
         patch("layla.memory.db.create_episode", return_value=1), \
         patch("layla.memory.db.add_episode_event"):
        out = summarize_history(_history(20), n_ctx=8192, threshold_ratio=0.6, force=True)

    add_summary.assert_called_once()
    assert add_summary.call_args.args[0].startswith("[Earlier conversation summary]")
    # relationship_memory is empty for this same reason — it rides the identical gate.
    add_rel.assert_called_once()
    assert len(out) < 20, "a forced compaction must actually shrink the history"
    assert any(m.get("role") == "system" for m in out), "the summary should be present as a system message"


def test_force_refuses_to_destroy_messages_it_could_not_save():
    """The hazard the fix itself introduces, closed deliberately.

    _compress_to_summary takes the LLM lock with blocking=False and degrades to a truncation marker
    under contention — a marker that is deliberately NOT persisted. Compacting into it would delete
    exactly the turns this call exists to preserve.
    """
    before = _history(20)
    with patch("services.context.context_manager._compress_to_summary", return_value=FALLBACK), \
         patch("layla.memory.db.add_conversation_summary") as add_summary:
        out = summarize_history(list(before), n_ctx=8192, threshold_ratio=0.6, force=True)

    add_summary.assert_not_called()
    assert out == before, (
        "forced compaction fell back to the non-persisted truncation marker and destroyed messages "
        "anyway — the ring must be left intact so the next turn can retry"
    )


def test_unforced_compaction_still_sheds_tokens_under_real_pressure():
    """The refusal above must NOT leak into the genuine-overflow path.

    When context is actually overflowing, truncating beats failing to fit. Only the proactive caller
    has the slack to wait for the summarizer.
    """
    huge = _history(40, user_tokens=400, asst_tokens=400)
    assert token_estimate_messages(huge) > int(2048 * 0.6), "premise: this history must exceed the threshold"
    with patch("services.context.context_manager._compress_to_summary", return_value=FALLBACK):
        out = summarize_history(huge, n_ctx=2048, threshold_ratio=0.6, force=False)
    assert len(out) < len(huge), "real overflow must still shed messages even without a persistable summary"


@pytest.mark.parametrize(
    "n_messages,expect_force",
    [(0, False), (5, False), (15, False), (16, True), (19, True), (20, True)],
)
def test_the_ring_forces_compaction_only_as_it_approaches_rolloff(n_messages, expect_force):
    """The trigger fires a few slots BEFORE capacity, because at capacity the next append deletes."""
    import shared_state

    captured: dict = {}
    done = threading.Event()

    def _fake_compact(messages, n_ctx=4096, cfg=None, force=False):
        captured["force"] = force
        done.set()
        return list(messages)

    cid = f"test-ring-{n_messages}"
    with shared_state._conv_hist_lock:
        shared_state._conv_histories.pop(cid, None)
    hist = shared_state.get_conv_history(cid)
    with shared_state._conv_hist_lock:
        hist.clear()
        for m in _history(max(0, n_messages - 1)):
            hist.append(m)

    try:
        with patch("services.context.context_manager.maybe_auto_compact", _fake_compact):
            # An assistant append is what schedules _compact_bg.
            shared_state.append_conv_history(cid, "assistant", "reply")
            assert done.wait(timeout=10), "the compaction thread never ran"
        assert captured["force"] is expect_force, (
            f"ring at {n_messages}/20 messages: force={captured['force']}, expected {expect_force}"
        )
    finally:
        with shared_state._conv_hist_lock:
            shared_state._conv_histories.pop(cid, None)

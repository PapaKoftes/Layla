"""Two latent defects that P13-B2 turned live by making auto-compaction actually run.

Both were reported by the audit loop (round-6 #12 HIGH, #14 MEDIUM) and both were unreachable for as
long as the compaction gate never opened. P13-B2 opened it — and made it fire at >= maxlen-4
occupancy, i.e. usually at exactly maxlen — so these are not speculative hardening. They close paths
that change opened.

#14 STALENESS GUARD. _compact_bg snapshots the conversation deque, runs a multi-second summariser
with the lock RELEASED, then guards the swap. The guard compared LENGTH. This deque has maxlen=20, so
once saturated an append EVICTS from the left and the length is identical before and after — the
guard is blind exactly at the occupancy where compaction now fires. Two turns arriving mid-summary
would read as "unchanged", the swap would proceed from the stale snapshot, and the newest exchange
would be discarded while two evicted messages returned from the dead.

#12 SELF-DEADLOCK. _compress_to_summary held `busy_lock` across run_completion(). Under
`llm_serialize_per_workspace: true` that lock IS llm_generation_lock, a NON-REENTRANT threading.Lock,
which run_completion re-enters on the same thread — blocking forever while holding the lock every
local completion needs. All inference freezes process-wide. The default config uses a reentrant lock,
which masked it.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import shared_state
from services.context.context_manager import _compress_to_summary


def _msgs(n: int, tag: str = "m") -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{tag}{i} " * 20} for i in range(n)]


class TestSaturatedDequeStalenessGuard:
    def test_revision_counter_advances_on_every_append(self):
        cid = "rev-counter-test"
        with shared_state._conv_hist_lock:
            shared_state._conv_histories.pop(cid, None)
            shared_state._conv_revisions.pop(cid, None)
        try:
            shared_state.get_conv_history(cid)
            with shared_state._conv_hist_lock:
                start = shared_state.conv_revision(cid)
            shared_state.append_conv_history(cid, "user", "hello")
            with shared_state._conv_hist_lock:
                assert shared_state.conv_revision(cid) == start + 1
        finally:
            with shared_state._conv_hist_lock:
                shared_state._conv_histories.pop(cid, None)
                shared_state._conv_revisions.pop(cid, None)

    def test_revision_advances_even_when_length_cannot(self):
        """THE bug in one assertion: at maxlen, length is constant while contents change."""
        cid = "saturated-test"
        with shared_state._conv_hist_lock:
            shared_state._conv_histories.pop(cid, None)
            shared_state._conv_revisions.pop(cid, None)
        try:
            hist = shared_state.get_conv_history(cid)
            with shared_state._conv_hist_lock:
                for m in _msgs(20):
                    hist.append(m)
            maxlen = hist.maxlen
            assert len(hist) == maxlen, "premise: the deque must be saturated"

            with shared_state._conv_hist_lock:
                len_before, rev_before = len(hist), shared_state.conv_revision(cid)
            shared_state.append_conv_history(cid, "user", "a brand new turn")
            with shared_state._conv_hist_lock:
                len_after, rev_after = len(hist), shared_state.conv_revision(cid)

            assert len_after == len_before, (
                "premise of the bug: a saturated deque does not change length on append"
            )
            assert rev_after != rev_before, (
                "the revision counter MUST detect what length cannot — otherwise the compaction "
                "swap proceeds from a stale snapshot and drops the newest turn"
            )
        finally:
            with shared_state._conv_hist_lock:
                shared_state._conv_histories.pop(cid, None)
                shared_state._conv_revisions.pop(cid, None)

    def test_compaction_aborts_when_a_turn_arrives_mid_summary(self):
        """End to end: a turn landing during summarisation must not be swallowed."""
        cid = "midsummary-test"
        with shared_state._conv_hist_lock:
            shared_state._conv_histories.pop(cid, None)
            shared_state._conv_revisions.pop(cid, None)
        try:
            hist = shared_state.get_conv_history(cid)
            with shared_state._conv_hist_lock:
                for m in _msgs(19):
                    hist.append(m)

            done = threading.Event()

            def _slow_compact(messages, n_ctx=4096, cfg=None, force=False):
                # Simulate a concurrent user turn arriving while the summariser runs.
                shared_state.append_conv_history(cid, "user", "URGENT NEW TURN")
                done.set()
                return [{"role": "system", "content": "[Earlier conversation summary]\n- stale"}]

            with patch("services.context.context_manager.maybe_auto_compact", _slow_compact):
                shared_state.append_conv_history(cid, "assistant", "reply that triggers compaction")
                assert done.wait(timeout=10), "compaction thread never ran"
                # Let the daemon finish its guarded swap.
                for _ in range(100):
                    with shared_state._conv_hist_lock:
                        contents = [m.get("content", "") for m in shared_state._conv_histories[cid]]
                    if any("URGENT NEW TURN" in c for c in contents):
                        break
                    threading.Event().wait(0.05)

            with shared_state._conv_hist_lock:
                contents = [m.get("content", "") for m in shared_state._conv_histories[cid]]
            assert any("URGENT NEW TURN" in c for c in contents), (
                "the turn that arrived during summarisation was destroyed by the swap"
            )
        finally:
            with shared_state._conv_hist_lock:
                shared_state._conv_histories.pop(cid, None)
                shared_state._conv_revisions.pop(cid, None)


class TestSummariserDoesNotSelfDeadlock:
    def test_busy_lock_is_released_before_the_nested_completion(self):
        """With a NON-reentrant lock (the per-workspace config), this hangs forever if held across."""
        real_lock = threading.Lock()  # non-reentrant, exactly like llm_generation_lock
        held_during_completion = {}

        def _fake_run_completion(prompt, **kw):
            # run_completion re-acquires the same lock internally. Prove it is free by doing so here.
            held_during_completion["could_acquire"] = real_lock.acquire(blocking=False)
            if held_during_completion["could_acquire"]:
                real_lock.release()
            return {"choices": [{"message": {"content": "- a real summary bullet line"}}]}

        with patch("services.llm.llm_gateway.llm_generation_lock", real_lock), \
             patch("services.llm.llm_gateway.llm_serialize_lock", real_lock), \
             patch("services.llm.llm_gateway.run_completion", _fake_run_completion), \
             patch("runtime_safety.load_config", return_value={"llm_serialize_per_workspace": True}):
            out = _compress_to_summary(_msgs(6))

        assert held_during_completion.get("could_acquire") is True, (
            "busy_lock was still held while run_completion ran — with the non-reentrant "
            "llm_generation_lock this is an unconditional self-deadlock that freezes ALL local "
            "inference, not merely a contention issue"
        )
        assert out.startswith("[Earlier conversation summary]"), "the summary must still be produced"

    def test_busy_lock_is_left_unlocked_afterwards(self):
        """A released-early lock must not be double-released or leaked."""
        real_lock = threading.Lock()
        with patch("services.llm.llm_gateway.llm_generation_lock", real_lock), \
             patch("services.llm.llm_gateway.llm_serialize_lock", real_lock), \
             patch("services.llm.llm_gateway.run_completion",
                   return_value={"choices": [{"message": {"content": "- bullet one line here"}}]}), \
             patch("runtime_safety.load_config", return_value={"llm_serialize_per_workspace": True}):
            _compress_to_summary(_msgs(6))
        assert real_lock.acquire(blocking=False), "lock leaked — inference would be frozen"
        real_lock.release()

    def test_busy_lock_still_skips_when_the_llm_is_genuinely_busy(self):
        """The admission behaviour must survive the fix: busy means skip, not queue."""
        real_lock = threading.Lock()
        real_lock.acquire()  # someone else is mid-generation
        try:
            with patch("services.llm.llm_gateway.llm_generation_lock", real_lock), \
                 patch("services.llm.llm_gateway.llm_serialize_lock", real_lock), \
                 patch("runtime_safety.load_config", return_value={"llm_serialize_per_workspace": True}):
                out = _compress_to_summary(_msgs(6))
            assert out.startswith("[Earlier conversation (truncated)]"), (
                "when the LLM is busy the summariser must fall back, not block behind a user turn"
            )
        finally:
            real_lock.release()

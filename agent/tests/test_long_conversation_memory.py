"""Plan #21 — durable, session-independent long-conversation memory.

THE 0-ROWS DEFECT: conversation_summaries had 0 rows for the entire life of the database. The only
writer, context_manager.summarize_history, compacts the IN-MEMORY ring (a deque(maxlen=20)) within a
single long session — so short chats and cross-session tails never produced a persistent summary, and
the head's recall path (get_recent_conversation_summaries) had nothing to surface.

These tests drive the durable trigger added in layla.memory.conversations and prove:
  (a) a conversation_summaries row is WRITTEN (0-rows-before / row-after);
  (b) the `conversation_compacted` liveness effect fires on the write;
  (c) get_recent_conversation_summaries returns the row;
  (d) a 30-message session produces a recallable summary.

The summarizer is mocked (this asserts the WRITE happened, not the model's prose quality). All DB
access is isolated via the `isolated_db` fixture — the operator's real DB is never touched.
"""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

GOOD_SUMMARY = "[Earlier conversation summary]\n- discussed the auth refactor and the DB migration plan"
FALLBACK = "[Earlier conversation (truncated)]\n- raw tail of the conversation"


def _summary_count() -> int:
    from layla.memory.db_connection import _conn
    with _conn() as db:
        return int(db.execute("SELECT COUNT(*) FROM conversation_summaries").fetchone()[0])


def _liveness_count(effect: str) -> int:
    from services.observability import liveness
    return int(liveness.snapshot().get(effect, {}).get("count") or 0)


def _seed_messages(cid: str, pairs: int, *, quiet: bool = False) -> None:
    """Persist `pairs` user+assistant exchanges through the real durable write path.

    quiet=True neutralises the per-append periodic trigger so seeding is purely synchronous DB
    writes with no background summariser threads — used when a test drives the trigger itself and
    needs a deterministic starting state.
    """
    from layla.memory.db import append_conversation_message, create_conversation
    create_conversation(cid)

    def _run() -> None:
        for i in range(pairs):
            append_conversation_message(cid, "user", f"user question {i}: how should we structure the module?")
            append_conversation_message(cid, "assistant", f"assistant answer {i}: here is a fairly detailed design outline")

    if quiet:
        with patch("layla.memory.conversations._maybe_durable_summary_on_append", lambda *a, **k: None):
            _run()
    else:
        _run()


def _wait_for_summary(timeout: float = 6.0) -> int:
    """Poll until at least one durable summary row exists (or timeout) — the periodic trigger writes
    on a daemon thread. Returns the final row count."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = _summary_count()
        if n >= 1:
            return n
        time.sleep(0.05)
    return _summary_count()


# ── (a) durable write + 0-before / row-after, and (b) liveness, (c) recall ──────────────────────────
def test_durable_summary_written_zero_rows_before_row_after(isolated_db):
    from layla.memory.conversations import (
        get_recent_conversation_summaries,
        summarize_conversation_to_durable_memory,
    )

    # 0 rows before — the defect's starting condition.
    assert _summary_count() == 0
    cc_before = _liveness_count("conversation_compacted")

    # Ten durable messages exist, but no existing path ever writes a summary for them.
    _seed_messages("conv-a", pairs=5, quiet=True)
    assert _summary_count() == 0, "DEFECT PROOF: durable messages exist yet no summary was ever written"

    with patch("services.context.context_manager.summarize_messages", return_value=GOOD_SUMMARY):
        result = summarize_conversation_to_durable_memory("conv-a")

    # Row after.
    assert result and result.startswith("[Earlier conversation summary]")
    assert _summary_count() == 1, "the durable trigger must WRITE a conversation_summaries row"

    # (b) liveness fired.
    assert _liveness_count("conversation_compacted") == cc_before + 1

    # (c) recall returns it.
    sums = get_recent_conversation_summaries(n=5)
    assert any(GOOD_SUMMARY in (s.get("summary") or "") for s in sums)


# ── (a, via >=16 turns) the natural, append-driven periodic trigger ─────────────────────────────────
def test_sixteen_turns_persists_a_summary(isolated_db):
    assert _summary_count() == 0

    # 16 exchanges (32 messages) drive the every-N periodic trigger through the real append path.
    with patch("services.context.context_manager.summarize_messages", return_value=GOOD_SUMMARY):
        _seed_messages("conv-16turns", pairs=16)
        n = _wait_for_summary()

    assert n >= 1, "driving >=16 turns must persist at least one durable summary via the append trigger"
    assert _liveness_count("conversation_compacted") >= 1


# ── (d) a 30-message session produces a recallable summary ──────────────────────────────────────────
def test_thirty_message_session_is_recallable(isolated_db):
    from layla.memory.conversations import (
        get_recent_conversation_summaries,
        summarize_conversation_to_durable_memory,
    )

    _seed_messages("conv-30", pairs=15, quiet=True)  # 30 messages
    assert _summary_count() == 0

    with patch("services.context.context_manager.summarize_messages", return_value=GOOD_SUMMARY):
        result = summarize_conversation_to_durable_memory("conv-30")

    assert result == GOOD_SUMMARY
    sums = get_recent_conversation_summaries(n=3)
    assert sums, "a 30-message session must leave a recallable durable summary"
    assert any(GOOD_SUMMARY in (s.get("summary") or "") for s in sums)


# ── the automatic path keeps low-value truncation rows out of recall; force persists them ───────────
def test_automatic_path_skips_truncation_but_force_persists(isolated_db):
    from layla.memory.conversations import summarize_conversation_to_durable_memory

    _seed_messages("conv-fallback", pairs=5, quiet=True)

    with patch("services.context.context_manager.summarize_messages", return_value=FALLBACK):
        # Automatic (force=False): LLM unavailable → text-only marker → NOT persisted, retry later.
        auto = summarize_conversation_to_durable_memory("conv-fallback")
        assert auto is None
        assert _summary_count() == 0

        # A session-end / manual snapshot (force=True) persists it as a durable record.
        forced = summarize_conversation_to_durable_memory("conv-fallback", force=True)

    assert forced == FALLBACK
    assert _summary_count() == 1


# ── the idle / session-end scheduler trigger writes summaries for short chats that ended ─────────────
def test_idle_job_writes_summary_for_idle_conversation(isolated_db):
    from layla.memory.db_connection import _conn
    from layla.scheduler.jobs import _bg_conversation_summary
    from layla.time_utils import utcnow

    # A short chat (8 messages) that ended before the every-N trigger could ever fire.
    _seed_messages("conv-idle", pairs=4, quiet=True)
    assert _summary_count() == 0

    # Backdate it so the idle window treats the session as ended.
    past = (utcnow() - timedelta(minutes=60)).isoformat()
    with _conn() as db:
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (past, "conv-idle"))
        db.commit()

    cc_before = _liveness_count("conversation_compacted")
    with patch("services.context.context_manager.summarize_messages", return_value=GOOD_SUMMARY):
        _bg_conversation_summary()

    assert _summary_count() == 1, "the idle/session-end job must persist a summary for an ended short chat"
    assert _liveness_count("conversation_compacted") == cc_before + 1

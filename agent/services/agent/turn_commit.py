"""The single place a completed turn is durably recorded. Persist, then learn.

Every reply Layla ships — quick-reply, cached, fast-reason, multi-agent, streamed,
orchestrated, or /v1-compat — passes through commit_turn exactly once, on the turn
boundary. Before this seam existed the same persist block was repeated at TEN done-frames
across two routers (seven in routers/agent.py, three in routers/openai_compat.py), with
real behavioural forks between them: aspect resolution differed three ways, `_mem_receipt`
fired at only 2 of 10, and the /v1 sites synthesized no conversation title at all.

Scope note: this owns the DURABLE record (conversations + messages + title) and the
post-turn learning. The in-memory history deques stay at the call sites — see the comment
in the persist block for why that is a boundary and not an oversight.

`state` is optional: post-turn learning needs only (goal, text, aspect_id), and the fast
paths have no run state at all — they never call agent_loop, so there was never anything
for run_finalizer to gate on. What genuinely needs the run (outcome evaluation, strategy
stats, skill acquisition, answer_quality) stays in run_finalizer.

Why the finalizer could not be the seam: reasoning_handler sets status="stream_pending"
and returns BEFORE the answer exists whenever stream_final=True, and the UI ships
streaming ON by default. run_finalizer gated all its learning work on
`status == "finished"`, so the learning pipeline only ever ran when the operator manually
unchecked "Stream responses". The gate was attached to a liveness signal; it is now a
SAFETY filter here (see _NO_LEARN_STATUSES) and liveness is the turn boundary itself.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("layla")

# Persistence is deliberately NOT gated on this — a refused, blocked, timed-out or aborted turn
# still belongs in the transcript; only LEARNING is withheld.
#
# HISTORY, because the reasoning here has been wrong once already. This list used to carry a
# reachability argument: "the done-frames only ever pass finished/blocked/fast_path, so entries
# like timeout/client_abort/pipeline_needs_input could not fire anyway." BL-245 DELETED that
# premise — those done-frames now all call commit_turn (they used to persist nothing at all, so
# the operator's message vanished on reload).
#
# Do NOT re-derive this list from "what can't happen" — derive it from what SHOULD not be learned.
# That is the whole point, and it is why the honest statement of reachability is: MOST of these are
# now demonstrably reachable, and `timeout` specifically was NOT reproducible when tried. Reaching it
# required defeating two layers (config_schema.py:121 clamps max_runtime_seconds to min 5, and
# auto_tune.py:125 authoritatively forces 300 unless the key is in auto_tune_locked_keys) — and even
# then a 63.7s multi-tool turn returned status=None, not the timeout branch. The frame exists and
# commits; whether the status label ever lands is unproven.
#
# An earlier version of this comment claimed "every status below is reachable today." That replaced a
# false reachability premise with the opposite claim, equally undemonstrated. Both are the same
# mistake: asserting reachability instead of measuring it. If you need to know, measure it.
#
# The semantic argument, which survives and is the real one: post-BL-376 the extractor reads the
# OPERATOR's turn, not the assistant's reply. "I prefer tea" is still true even if the run timed
# out, the parse failed, or the user closed the tab. Run mechanics do not invalidate what the
# operator said, so timeout / client_abort / error / pipeline_needs_input DO learn — blocking
# them would silently drop valid preferences the operator stated.
#
# Two things genuinely warrant withholding, for two DIFFERENT reasons:
#
#  1. SAFETY — we should not act on this exchange at all:
#     "blocked" (content guard replaced the text). Refusals are handled by the `refused` flag.
#     Proved by test_refused_turn_writes_no_learning / test_blocked_turn_writes_no_learning.
#  2. RESOURCE COHERENCE — "system_busy" is the governor REFUSING to run the LLM because CPU/RAM
#     is exhausted (agent_loop.py raises it). Learning is not free: _auto_extract_learnings makes
#     its own LLM call. Answering "the box is out of resources" by immediately starting more LLM
#     work is incoherent, and on this CPU-only box it is how you turn a busy moment into a stuck
#     one. The operator's message is still persisted; only the extraction is skipped.
_NO_LEARN_STATUSES = frozenset(
    {
        "blocked",      # content-guard replaced the text; treat the exchange as off-limits
        "system_busy",  # governor declined LLM work — do not spawn an LLM extraction in reply
    }
)


# ── BL-243: the rail needs to know a title is still in flight ──
#
# The title is synthesized by an LLM on a BACKGROUND thread (see _maybe_synth_title). On this
# CPU-bound box that call lands ~14s+ AFTER the done-frame has already closed the SSE stream —
# so the title cannot be pushed down the turn's own stream, and the rail's single re-render
# (app.js, on the done-frame) always raced the synth and always lost. The operator saw the
# instant extractive title forever: "it never reloads the ui once it's actually done loading."
#
# This registry is the seam that makes a BOUNDED poll possible instead of a heartbeat: the UI
# asks GET /conversations/{id}/title, and only keeps asking while synth_pending is true. Without
# it the UI would have to poll blind on every turn — including the ~all turns that synthesize no
# title at all — which is exactly the kind of idle burn this box cannot afford.
#
# Registration happens SYNCHRONOUSLY inside commit_turn, before the done-frame is yielded, so
# there is no window in which the client can poll and be told "not pending" for a synth that is
# about to start.
_TITLE_SYNTH_LOCK = threading.Lock()
_TITLE_SYNTH_PENDING: set[str] = set()


def title_synth_pending(conversation_id: str) -> bool:
    """True while a background title synthesis is in flight for this conversation."""
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    with _TITLE_SYNTH_LOCK:
        return cid in _TITLE_SYNTH_PENDING


def _cfg() -> dict:
    try:
        import runtime_safety

        return runtime_safety.load_config()
    except Exception:
        return {}


def _should_learn(status: str, refused: bool) -> bool:
    """Safety filter. Note it does NOT test the reply's length.

    The old finalizer required `len(reply) >= 80` before extracting. That was evidence about
    how chatty the ASSISTANT was, which is not evidence that the OPERATOR said anything worth
    remembering — and post-BL-376 the extractor does not read the reply at all. A terse "Got
    it." in answer to "I prefer tea" is exactly the case worth keeping, and it is precisely
    the case the old gate dropped.
    """
    return not (refused or (status or "") in _NO_LEARN_STATUSES)


def _maybe_synth_title(conversation_id: str, user_msg: str, assistant_text: str) -> None:
    """On the FIRST exchange, async-polish the auto title into an LLM-synthesized topic name.

    Non-blocking (background thread) so it never adds latency to the reply — the instant
    extractive title from _auto_name_conversation already shows in the rail; this replaces it
    with a crisper name that lands on the next rail refresh. Flag-gated; safe no-op on failure.
    """
    cid = (conversation_id or "").strip()
    if not cid or not (user_msg or "").strip():
        return
    try:
        import runtime_safety
        if not runtime_safety.load_config().get("conversation_title_synthesis_enabled", True):
            return
        from layla.memory.db import get_conversation
        conv = get_conversation(cid) or {}
        # first exchange only (user + assistant just persisted → count ~2); don't clobber later
        if int(conv.get("message_count") or 0) > 2:
            return
        _prior_title = str(conv.get("title") or "")  # the instant extractive title, captured pre-synth
        # Skip synth entirely if the user already set a CUSTOM title (BEFORE the first message) — the
        # current title is then NOT the auto-extractive one, and overwriting it with an LLM title would
        # discard the manual rename. (The compare-and-set in _bg covers a rename made DURING the window.)
        try:
            from layla.memory.conversations import _auto_name_conversation
            _expected_auto = _auto_name_conversation(user_msg)
            if _expected_auto and _prior_title and _prior_title != _expected_auto:
                return
        except Exception:
            pass

        def _bg() -> None:
            try:
                from services.agent.title_synthesizer import synthesize_conversation_title
                t = synthesize_conversation_title(user_msg, assistant_text)
                if t:
                    from layla.memory.db import get_conversation as _gc
                    from layla.memory.db import rename_conversation
                    # Compare-and-set: only overwrite if the title is STILL the auto/extractive one we
                    # captured. The synth LLM call lands ~14s later; a manual rename the user made in
                    # that window (POST /conversations/{id}/rename) must NOT be silently reverted.
                    if str((_gc(cid) or {}).get("title") or "") == _prior_title:
                        rename_conversation(cid, t)
            except Exception as _tx:
                logger.debug("title synth bg failed: %s", _tx)
            finally:
                # BL-243: clear the flag on EVERY exit path (success, no-title, exception, or a
                # compare-and-set that declined to write). A leaked flag would make the rail poll
                # to its ceiling on a synth that already finished — bounded, but pure waste.
                with _TITLE_SYNTH_LOCK:
                    _TITLE_SYNTH_PENDING.discard(cid)

        # Mark BEFORE start(): once the thread is running the done-frame may already be on the
        # wire, and a client that polls before this line would be told "nothing pending".
        with _TITLE_SYNTH_LOCK:
            _TITLE_SYNTH_PENDING.add(cid)
        try:
            threading.Thread(target=_bg, daemon=True, name="title-synth").start()
        except Exception:
            # Thread never started, so _bg's finally will never run — don't strand the flag.
            with _TITLE_SYNTH_LOCK:
                _TITLE_SYNTH_PENDING.discard(cid)
            raise
    except Exception as _te:
        logger.debug("title synth gate failed: %s", _te)


def _mem_receipt(user_msg: str) -> str:
    """Persist any durable fact the user stated this turn; return a receipt for the done-frame.

    Fast (regex only) so it's fine synchronously in the done-path. Powers the 'memory updated'
    chip and makes the durable fact show up in the About-you panel. Flag-gated; '' on nothing.
    """
    try:
        import runtime_safety
        if not runtime_safety.load_config().get("identity_capture_enabled", True):
            return ""
        from services.memory.identity_extractor import capture_identity_from_turn
        return capture_identity_from_turn(user_msg or "")
    except Exception as _me:
        logger.debug("identity capture failed: %s", _me)
        return ""


def commit_turn(
    conversation_id: str,
    goal: str,
    text: str,
    *,
    aspect_id: str,
    status: str = "finished",
    refused: bool = False,
    learn: bool = True,
    state: dict | None = None,
) -> str:
    """Persist the turn, then learn from it. Returns the memory receipt ('' if none).

    `text` must be the CLEANED, floored reply — every call site already computes it
    (polish_output → _apply_output_floor).

    `learn=False` is for replayed replies (the response-cache hit): a replay is not a new
    exchange, and learning from it would double-count the original.

    Idempotency: callers must invoke this exactly once per turn. It is NOT
    self-deduplicating — append_conversation_message is append-only with no upsert.
    """
    cid = (conversation_id or "").strip()
    asp = (aspect_id or "").strip()

    # ── 1. Persist durably (the ten-way duplication, once) ──
    # NOTE the deliberate boundary: the in-memory history deques (shared_state.append_conv_history
    # and main._append_history) stay at the call sites. They are a per-turn CONTEXT CACHE, lost on
    # restart — not the durable record this function is named for — and `_append_history` genuinely
    # forks per caller (the stream=false site substitutes standby text). shared_state is also the
    # module the architecture is actively shrinking (tests/test_architecture_boundaries.py caps its
    # importers and the count is meant to fall), so a new services/ module must not add itself to
    # that list to save two lines. Durable persistence + learning is the seam; the caches are not.
    try:
        from layla.memory.db import append_conversation_message, create_conversation

        create_conversation(cid, aspect_id=asp)
        append_conversation_message(cid, "user", goal, aspect_id=asp)
        append_conversation_message(cid, "assistant", text, aspect_id=asp)
        _maybe_synth_title(cid, goal, text)
    except Exception as e:
        logger.debug("commit_turn: durable persist failed: %s", e)

    # ── 2. Receipt: durable operator facts (was wired at only 2 of 10 sites) ──
    receipt = _mem_receipt(goal)

    # ── 3. Learn (safety-gated) ──
    if not learn or not _should_learn(status, refused):
        return receipt

    try:
        if _cfg().get("emotional_presence_enabled", True):
            from services.personality.emotional_presence import register_from_turn

            _ev = (state or {}).get("outcome_evaluation") or {}
            register_from_turn(
                str(goal or ""),
                outcome_success=_ev.get("success") if isinstance(_ev, dict) else None,
            )
    except Exception as e:
        logger.debug("commit_turn: mood nudge failed: %s", e)

    try:
        from services.infrastructure.outcome_writer import _auto_extract_learnings

        threading.Thread(
            target=_auto_extract_learnings,
            args=(goal, text, asp),
            daemon=True,
            name="auto-learn",
        ).start()
    except Exception as e:
        logger.debug("commit_turn: learning extraction failed: %s", e)

    try:
        from services.memory.conversation_entity_extractor import extract_in_background

        extract_in_background(goal, text, conversation_id=cid, aspect_id=asp)
    except Exception as e:
        logger.debug("commit_turn: entity extraction failed: %s", e)

    return receipt

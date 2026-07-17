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

# SAFETY filter, not a liveness one. Persistence is deliberately NOT gated on this — a refused
# or blocked turn still belongs in the transcript; only LEARNING is withheld.
#
# This list is deliberately SHORT, and the short list is the considered answer rather than an
# unfinished one. An earlier draft also carried timeout / client_abort / system_busy / error /
# parse_failed / pipeline_needs_input. Two things were wrong with that:
#
#  1. Reachability. The done-frames only ever pass "finished", "blocked" or "fast_path"
#     (pipeline_needs_input and plan_ready return early and never reach commit_turn at all), so
#     those entries could not fire. A list that looks like a guard but cannot execute is
#     documentation — exactly the failure mode this seam exists to remove.
#  2. Semantics. Those entries were reasoned from the OLD extractor, which read the assistant's
#     reply: if the run timed out, the reply was junk, so learning from it was junk. Post-BL-376
#     the extractor reads the OPERATOR's turn. "I prefer tea" is still true even if the run
#     timed out, the parse failed, or the user closed the tab. Run mechanics do not invalidate
#     what the operator said; blocking on them would silently DROP valid preferences.
#
# What genuinely invalidates the operator's turn is that we should not be acting on it: the
# request was refused, or its output tripped the content guard. Both are reachable and both are
# proved by tests (test_refused_turn_writes_no_learning / test_blocked_turn_writes_no_learning).
_NO_LEARN_STATUSES = frozenset(
    {
        "blocked",  # content-guard replaced the text; treat the exchange as off-limits
    }
)


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

        threading.Thread(target=_bg, daemon=True, name="title-synth").start()
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

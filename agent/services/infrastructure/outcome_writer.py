"""
Post-run outcome memory, Echo aspect memories, patch extraction, auto-learnings.
Extracted from agent_loop (consolidation Phase 4).
"""
from __future__ import annotations

import collections
import logging
import re
import threading

from services.memory.memory_router import save_aspect_memory as _db_save_aspect_memory  # canonical write path

logger = logging.getLogger("layla")

_fingerprint_lock = threading.Lock()

_ASPECT_LEARNING_TYPE: dict = {
    "morrigan": "strategy",
    "nyx": "fact",
    "echo": "preference",
    "eris": "fact",
    "lilith": "identity",
    "cassandra": "fact",
}
from constants import GREETING_WORDS as _GREETING_WORDS  # P2-8

_recent_learning_fingerprints: collections.OrderedDict = collections.OrderedDict()
_recent_tool_pattern_fingerprints: collections.OrderedDict = collections.OrderedDict()


def _maybe_save_session_pattern_memory(
    aspect_id: str,
    user_msg: str,
    reply: str,
    conversation_history: list,
) -> None:
    """Save a distilled session-pattern note to the ACTIVE aspect's memories.

    - Every 5 turns, and every turn while Echo is active: store recurring user topics.
    - Written under `aspect_id`, because that is the key the reader queries by.

    THIS WROTE TO A HARDCODED "echo" FOR THE LIFE OF THE DATABASE. The old docstring said
    "Echo tracks patterns across all turns, not just when Echo is the active aspect", and the
    body honoured that by passing the literal `"echo"` to _db_save_aspect_memory while the true
    active aspect sat unused in `aspect_id` — interpolated into the note's TEXT one line above,
    but discarded for the column. The intent was a cross-aspect observer.

    The reader makes that intent unachievable: user_profile.get_aspect_memories filters
    `WHERE aspect_id=?`, and system_head_builder passes the CURRENT aspect's id. So notes filed
    under Echo are readable only by Echo. On the operator's box that meant Morrigan — the main
    aspect, 120 interactions, 3.5x any other — read zero of her own memories while Echo silently
    accumulated all 18 rows. Five aspects had no episodic memory at all.

    Writing to `aspect_id` is what makes the write agree with the read. A genuine cross-aspect
    tracker is still possible later, but it needs a reader that queries across aspects; it cannot
    be built by writing to the wrong key and hoping.
    """
    turn_count = len(conversation_history) if conversation_history else 0
    is_echo = aspect_id == "echo"

    # NOTE: we no longer store the raw "User: <msg>. Echo replied: <reply>" exchange as an
    # aspect memory — that verbatim echo was run-log noise (and could carry a leaked marker)
    # that then got injected into unrelated turns. The distilled session-pattern note below
    # (recurring topics only) is the useful signal Echo actually needs.

    if turn_count > 0 and (turn_count % 5 == 0 or is_echo):
        try:
            recent = conversation_history[-6:] if len(conversation_history) >= 6 else conversation_history
            topics = []
            for t in recent:
                if t.get("role") == "user":
                    msg = (t.get("content") or "")[:80].strip()
                    if msg:
                        topics.append(msg)
            if topics and len(topics) >= 2:
                pattern_note = (
                    f"Session pattern ({turn_count} turns): "
                    + "; ".join(topics[:3])
                    + f". Last reply aspect: {aspect_id}."
                )
                # aspect_id, NOT "echo" — the reader filters by this exact column.
                _db_save_aspect_memory(aspect_id, pattern_note[:400])
        except Exception:
            pass


def _save_outcome_memory(state: dict) -> None:
    """
    After successful multi-step runs, store a short semantic summary (what was done, what worked).
    Uses existing learnings/memory; avoids logs and noise.
    """
    global _recent_tool_pattern_fingerprints
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] != "reason"]
    if state.get("status") != "finished":
        return
    # NOTE: we deliberately do NOT store an "Objective: <goal>. Replied. Snippet: <reply>"
    # summary as a learning. That echoed the run's own prompt+reply into the learnings table,
    # so every trivial turn ("hello", "ready") — and worse, a research turn carrying its
    # answer template — became an injected "memory" that hijacked later unrelated turns
    # (a bare "hello" would get answered as the remembered topic, template and all). Durable
    # knowledge comes from the distiller (facts) + the precise tool-success patterns below;
    # a raw objective/reply echo is run-log noise, not knowledge.

    # Layla v3: tool success patterns (high precision, deterministic).
    # Persist compact "what worked" snippets from successful tool steps.
    try:
        from services.memory.memory_router import save_learning  # canonical write path

        saved = 0
        for s in tool_steps[:30]:
            action = str(s.get("action") or "").strip()
            if not action or action in ("think", "reason", "none", "client_abort", "pre_read_probe"):
                continue
            r = s.get("result") or {}
            if not (isinstance(r, dict) and r.get("ok")):
                continue
            path = str(r.get("path") or "").strip()
            hint = ""
            if path:
                hint = f" on {path}"
            elif isinstance(r.get("entries"), list):
                hint = f" returning {len(r.get('entries') or [])} entries"
            elif r.get("message"):
                hint = f" ({str(r.get('message') or '')[:80]})"
            item = f"Tool pattern: {action}{hint} succeeded."
            fp = (action + "|" + (path or "")).lower()[:120]
            with _fingerprint_lock:
                if fp in _recent_tool_pattern_fingerprints:
                    continue
                _recent_tool_pattern_fingerprints[fp] = None  # OrderedDict as ordered set
                if len(_recent_tool_pattern_fingerprints) > 300:
                    # Evict oldest entries (first inserted), keep most recent 160
                    while len(_recent_tool_pattern_fingerprints) > 160:
                        _recent_tool_pattern_fingerprints.popitem(last=False)
            try:
                save_learning(content=item[:240], kind="strategy")
                saved += 1
            except Exception:
                pass
            if saved >= 3:
                break
    except Exception as e:
        logger.debug("tool pattern auto-learn failed: %s", e)
    try:
        from services.infrastructure.reflection_engine import run_reflection

        run_reflection(state)
    except Exception as e:
        logger.debug("reflection engine failed: %s", e)

    # Golden examples: persist small high-score patterns for future few-shot injection.
    try:
        ev = state.get("outcome_evaluation") if isinstance(state.get("outcome_evaluation"), dict) else {}
        score = ev.get("score") if isinstance(ev, dict) else None
        if score is not None and float(score) >= 0.85:
            steps = state.get("steps") or []
            toolish = [s for s in steps if s.get("action") and s.get("action") not in ("reason", "think", "none", "client_abort")]
            pattern_lines: list[str] = []
            for s in toolish[:3]:
                act = str(s.get("action") or "").strip()
                if not act:
                    continue
                args = s.get("args")
                if isinstance(args, dict) and args:
                    # Keep it short/deterministic; avoid leaking big payloads into the DB.
                    arg_keys = ",".join(sorted(str(k) for k in list(args.keys())[:6]))
                    pattern_lines.append(f'{{"action":"tool","tool":"{act}","args_keys":"{arg_keys}"}}')
                else:
                    pattern_lines.append(f'{{"action":"tool","tool":"{act}"}}')
            if pattern_lines:
                from services.memory.golden_examples import store_golden_example

                goal = (state.get("original_goal") or state.get("goal") or "").strip()
                store_golden_example(
                    task_type="agent",
                    goal=goal,
                    decision_pattern="\n".join(pattern_lines),
                    score=float(score),
                )
    except Exception as e:
        logger.debug("golden example save skipped: %s", e)

    # Reinforce learnings that were retrieved and used during the run.
    try:
        from services.memory.memory_consolidation import reinforce_learning

        ev = state.get("outcome_evaluation") if isinstance(state.get("outcome_evaluation"), dict) else {}
        ok = bool(ev.get("success", state.get("status") == "finished"))
        score_hint = ev.get("score")
        try:
            sd = ev.get("score_dimensions") if isinstance(ev.get("score_dimensions"), dict) else {}
            comp = sd.get("completion")
            if comp is not None:
                score_hint = comp
        except Exception:
            pass
        used_ids = state.get("used_learning_ids") if isinstance(state.get("used_learning_ids"), list) else []
        for lid in used_ids[:20]:
            s = str(lid).strip()
            if not s:
                continue
            try:
                reinforce_learning(int(s), success=ok)
            except (TypeError, ValueError):
                continue
            try:
                from layla.memory.db_connection import _conn
                from layla.memory.migrations import migrate
                from layla.memory.vector_store import patch_learning_metadata

                migrate()
                with _conn() as db:
                    row = db.execute(
                        "SELECT embedding_id FROM learnings WHERE id=? AND embedding_id != ''",
                        (int(s),),
                    ).fetchone()
                if row and score_hint is not None:
                    eid = row["embedding_id"] if hasattr(row, "keys") else row[0]
                    if eid:
                        patch_learning_metadata(str(eid), {"success_score": float(score_hint)})
            except Exception as _pe:
                logger.debug("chroma success_score patch skipped: %s", _pe)
    except Exception as e:
        logger.debug("reinforce_learning skipped: %s", e)


def _extract_patch_text(goal: str) -> str:
    """Extract only the patch/diff body from the message, not instructions or extra text."""
    g = (goal or "").strip()
    if not g:
        return g
    for marker in ("```patch", "```diff", "``` unified", "```"):
        if marker in g:
            parts = g.split(marker, 2)
            if len(parts) >= 3:
                body = parts[1].strip()
                if body:
                    return body
    for line in g.splitlines():
        stripped = line.strip()
        if stripped.startswith("--- ") or stripped.startswith("diff --git") or stripped.startswith("Index:"):
            return g[g.find(line) :].strip()
    return g


# ── operator-fact extraction (BL-376) ────────────────────────────────────────
# Durable facts about the operator can only come from the OPERATOR. This function used to
# read the ASSISTANT's reply and "extract insights" from it, so it faithfully memorised
# docstrings ('n (int): The position in the Fibonacci sequence to return.'), citations
# ('[1] "Python Sets". Real Python.') and Paris trivia. 28/28 rows in the operator's DB were
# this — it was working exactly as written. The fix is not a threshold: all 28 rows pass
# every gate in the store. The fix is the SOURCE.

_SUBJECTS = ("user", "world", "none")
_MEM_TYPES = ("preference", "correction", "identity", "episodic")

# Type -> stored confidence. Confidence IS the TTL: the daily job in layla/scheduler/jobs.py
# runs decay_stored_confidence (x0.98/day after a 7-day grace) then
# prune_low_confidence_learnings (archives, reversibly, at <0.08). No new expiry machinery.
#   0.80 -> archived at ~1.1 years   (identity/correction)
#   0.70 -> archived at ~5.5 months  (preference)
#   0.12 -> archived at ~27 days     (episodic)
# reinforce_learning is +0.04/use, which outweighs ~17 days of decay at the episodic level,
# so an episodic memory that keeps being retrieved graduates to durable on its own.
_TYPE_CONFIDENCE = {
    "identity": 0.80,
    "correction": 0.80,
    "preference": 0.70,
    "episodic": 0.12,
}

_TYPE_PREFIX = {
    "preference": "Operator preference: ",
    "correction": "Operator correction: ",
    "identity": "Operator identity: ",
    "episodic": "Operator context: ",
}

_CORRECTION_TRIGGERS = (
    "actually", "that's wrong", "that is wrong", "no,", "not true", "correction",
)
_PREFERENCE_TRIGGERS = (
    "i prefer ", "i like ", "i dislike ", "always use ", "never use ",
    "don't use ", "do not use ",
)

# Cheap pre-filter for the LLM path ONLY. A message with no first-person reference cannot
# state a fact about the user, so there is nothing for the model to find. This is what keeps
# the per-turn tax off a CPU-bound box: on the operator's real corpus ("what is the capital
# of france", "write me a fibonacci function", "python sets") this matches ZERO times, so
# ZERO extra inference runs. Deliberate recall trade: a first-person-free identity claim
# ("name's Mina") is missed. The deterministic detectors below do NOT depend on this gate —
# "actually no, use tabs" has no first-person pronoun and is still caught.
_FIRST_PERSON_RE = re.compile(r"\b(i|i'm|im|i've|my|mine|me|myself|we|our|us)\b", re.IGNORECASE)


def detect_operator_facts(user_msg: str) -> list[tuple[str, str]]:
    """Deterministic, high-precision operator-fact detectors. PRIMARY path — ALWAYS runs.

    Promoted from the old lines 302-335, which had the right instinct (read `user_msg`) in
    the wrong place: they sat AFTER `if not extracted: return`, so a preference was only
    ever recorded when the extractor had ALSO scraped something out of the assistant's
    reply. The repo's own test documented the workaround ("The response needs extractable
    bullet points so the function doesn't early-return"). That coupling is why the
    operator's DB holds 16 'fact' + 12 'strategy' rows and ZERO 'preference' rows. The
    island is now the mainland: these run first, unconditionally, never behind the LLM.
    """
    um = (user_msg or "").strip()
    if not um or len(um) > 300:
        return []
    ul = um.lower()
    flat = um.replace("\n", " ").strip()
    out: list[tuple[str, str]] = []
    # elif, NOT a second if. "Actually I prefer the recursive version" trips BOTH trigger sets, and these
    # were two independent ifs — so ONE message wrote TWO rows carrying the SAME text. Dedup could not
    # collapse them either: the type prefixes differ ("Operator correction: …" vs "Operator preference: …"),
    # so content_hash differs. Correction wins because it is the stronger, more specific signal (the operator
    # is telling us we got something wrong) and it already carries the higher confidence, 0.8 vs 0.7.
    if any(k in ul for k in _CORRECTION_TRIGGERS):
        out.append(("correction", flat[:180]))
    elif any(t in ul for t in _PREFERENCE_TRIGGERS):
        out.append(("preference", flat[:180]))
    return out


_EXTRACT_PROMPT = """Read one message the user sent to an assistant. Decide whether it states a durable fact ABOUT THE USER.

subject:
  "user"  - the message states a preference, correction, or identity fact about the user.
  "world" - the message is about code, math, or facts about the outside world.
  "none"  - a question, a greeting, or a request to do work.

Rules:
- A question is never a fact about the user. "how do I write fibonacci?" -> none
- A request is never a fact about the user. "write a python script" -> none
- Code, docstrings and citations are never facts about the user -> world
- If unsure, answer none.

type (only meaningful when subject is "user"):
  "preference" - what the user likes or always wants. "I prefer tea"
  "correction" - the user correcting the assistant. "actually no, use tabs"
  "identity"   - a stable fact about who the user is. "I'm a backend dev"
  "episodic"   - what the user is doing right now. "I'm debugging auth today"

fact: one short third-person sentence starting with "The operator". Empty string unless subject is "user".
durable: true if it will still be true next month.

Message: what is the capital of france
{"subject":"world","type":"episodic","fact":"","durable":false}
Message: write me a fibonacci function
{"subject":"none","type":"episodic","fact":"","durable":false}
Message: I prefer tea
{"subject":"user","type":"preference","fact":"The operator prefers tea.","durable":true}
Message: I'm debugging the auth module today
{"subject":"user","type":"episodic","fact":"The operator is debugging the auth module.","durable":false}

Message: __MSG__
"""


def _llm_extract_operator_fact(user_msg: str) -> tuple[str, str] | None:
    """Closed-schema, grammar-pinned extraction. Returns (type, fact) or None.

    EVERY failure mode returns None ("extract nothing"). There is deliberately NO path that
    stores unvalidated model output: "store it anyway" is how the DB filled with docstrings.
    """
    if not _FIRST_PERSON_RE.search(user_msg or ""):
        return None
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        return None
    if not cfg.get("operator_memory_llm_enabled", True):
        return None
    # Grammar sampling is a local-llama_cpp capability; a remote server cannot take a
    # LlamaGrammar object. Same gate as the gbnf branch in llm_decision.py.
    if (cfg.get("llama_server_url") or "").strip():
        return None
    try:
        from services.llm.gbnf_grammar import run_gbnf_memory_extraction
        from services.llm.llm_gateway import _get_llm, llm_generation_lock, llm_serialize_lock

        llm = _get_llm()
        if llm is None:
            return None

        # llama_cpp is NOT thread-safe: two threads decoding on one Llama handle corrupt the
        # shared scratch buffer and abort the PROCESS via
        #   GGML_ASSERT(src1_ptr + src1_col_stride*nrows <= params->wdata + params->wsize)
        # This is not theoretical — an un-serialized version of this call killed the server on the
        # first real streamed turn, because extraction runs on a background thread while the turn's
        # own generation is still decoding. Every other local completion serializes on this lock
        # (llm_gateway picks it as `infer_lock`; inference_router applies it as `with _llm_lock:`),
        # and the pre-existing GBNF caller in services/agent/llm_decision.py is safe only because it
        # runs ON the already-serialized run thread. A background writer must take the lock itself.
        # Mirror the gateway's selection exactly so we contend on the SAME object it uses.
        infer_lock = llm_generation_lock if cfg.get("llm_serialize_per_workspace") else llm_serialize_lock
        # Bounded wait, then give up: this is a daemon thread doing optional work behind a reply the
        # user already has. Skipping the LLM path costs recall, never correctness — the deterministic
        # detectors have already run and are unaffected.
        if not infer_lock.acquire(timeout=120):
            logger.debug("operator-fact: inference lock busy, skipping LLM extraction for this turn")
            return None
        try:
            obj = run_gbnf_memory_extraction(llm, _EXTRACT_PROMPT.replace("__MSG__", (user_msg or "")[:250]))
        finally:
            infer_lock.release()
    except Exception as e:
        logger.debug("operator-fact extraction skipped: %s", e)
        return None
    if not isinstance(obj, dict):
        return None

    # ── the hard reject ──────────────────────────────────────────────────────
    # This single line is the whole of BL-376. Every one of the 28 junk rows is
    # subject="world"; a docstring param and a Real Python citation cannot survive it.
    if str(obj.get("subject") or "").strip().lower() != "user":
        return None

    mem_type = str(obj.get("type") or "").strip().lower()
    if mem_type not in _MEM_TYPES:
        return None
    fact = str(obj.get("fact") or "").strip()
    if len(fact) < 8:
        return None
    # `durable` is a DEMOTION signal only, never a promotion: the enum keys are grammar-pinned
    # and trustworthy, a 3B's free boolean is not. durable=false downgrades to episodic TTL;
    # durable=true can never upgrade an episodic memory into a permanent one.
    if not bool(obj.get("durable")) and mem_type != "correction":
        mem_type = "episodic"
    return (mem_type, fact[:180])


def _auto_extract_learnings(user_msg: str, response: str, aspect_id: str) -> None:
    """Extract durable facts about the OPERATOR from the operator's own turn, and persist.

    Its one caller is services/agent/turn_commit.commit_turn (BL-338), which fires on the turn
    boundary for every reply path. `response` is accepted to keep the (user_msg, response,
    aspect_id) signature stable for that caller and is DELIBERATELY UNUSED: reading it IS the
    BL-376 defect. Do not reintroduce it — the guard at
    tests/test_operator_fact_extractor.py::test_assistant_reply_junk_yields_no_learning
    will go red.
    """
    global _recent_learning_fingerprints
    try:
        um = (user_msg or "").strip()
        if not um or len(um) > 2000:
            return
        words = um.split()
        if len(words) < 3:
            return
        first_words = set(w.lower().strip(".,!?") for w in words[:6])
        if first_words.issubset(_GREETING_WORDS):
            return

        # Deterministic first (free), LLM second (additive, never a fallback for the other).
        candidates: list[tuple[str, str]] = list(detect_operator_facts(um))
        hit = _llm_extract_operator_fact(um)
        if hit and not any(c[0] == hit[0] for c in candidates):
            candidates.append(hit)
        if not candidates:
            return

        from services.memory.memory_router import save_learning  # canonical write path

        saved = 0
        for mem_type, fact in candidates[:2]:
            content = (_TYPE_PREFIX.get(mem_type, "Operator context: ") + fact)[:240]
            fp = (mem_type + "|" + fact[:60]).lower()
            with _fingerprint_lock:
                if fp in _recent_learning_fingerprints:
                    continue
                _recent_learning_fingerprints[fp] = None
                if len(_recent_learning_fingerprints) > 200:
                    while len(_recent_learning_fingerprints) > 100:
                        _recent_learning_fingerprints.popitem(last=False)
            try:
                # min_length=12: an operator fact is high-information at any length. The
                # 40-char floor is a verbosity proxy that rejects 'Operator preference: I
                # prefer tea' (33 chars) — see learning_filter.filter_learning.
                rid = save_learning(
                    content=content,
                    kind=mem_type,
                    confidence=_TYPE_CONFIDENCE.get(mem_type, 0.12),
                    source="operator_turn",
                    aspect_id=aspect_id or "",
                    min_length=12,
                )
                if rid and int(rid) > 0:
                    saved += 1
            except Exception:
                pass
        if saved:
            logger.debug("operator-fact: saved %d rows (aspect=%s)", saved, aspect_id)
    except Exception as e:
        logger.debug("operator-fact extraction failed: %s", e)

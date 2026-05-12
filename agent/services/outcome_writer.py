"""
Post-run outcome memory, Echo aspect memories, patch extraction, auto-learnings.
Extracted from agent_loop (consolidation Phase 4).
"""
from __future__ import annotations

import logging
import threading

from services.memory_router import save_aspect_memory as _db_save_aspect_memory  # canonical write path

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
_GREETING_WORDS = frozenset({"hi", "hello", "hey", "thanks", "thank", "ok", "okay", "yes", "no", "sure", "cool"})
_recent_learning_fingerprints: set = set()
_recent_tool_pattern_fingerprints: set = set()


def _maybe_save_echo_memory(
    aspect_id: str,
    user_msg: str,
    reply: str,
    conversation_history: list,
) -> None:
    """
    Echo tracks patterns across all turns, not just when Echo is the active aspect.
    - Every 5 turns: saves a brief session pattern summary to Echo's aspect memories.
    - When Echo is active: saves the full exchange immediately.
    - Extracts recurring topics / avoidance signals from recent history.
    """
    turn_count = len(conversation_history) if conversation_history else 0
    is_echo = aspect_id == "echo"

    if is_echo:
        summary = f"User: {user_msg[:120]}. Echo replied: {reply[:250]}."
        _db_save_aspect_memory("echo", summary)

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
                _db_save_aspect_memory("echo", pattern_note[:400])
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
    objective = (state.get("objective") or state.get("original_goal") or "")[:200]
    if tool_steps:
        actions = ", ".join(s["action"] for s in tool_steps[:5])
        facts = []
        for s in tool_steps:
            r = s.get("result") or {}
            if isinstance(r, dict) and r.get("ok"):
                if r.get("path"):
                    facts.append(f"path:{r.get('path', '')[:80]}")
                if r.get("entries") and isinstance(r["entries"], list):
                    facts.append(f"listed {len(r['entries'])} items")
        summary = f"Objective: {objective}. Did: {actions}. " + (" ".join(facts[:3]) if facts else "Completed.")
    else:
        final_text = ""
        for s in reversed(steps):
            if s.get("action") == "reason":
                r = s.get("result", "")
                final_text = r if isinstance(r, str) else ""
                break
        snippet = (final_text.strip()[:140] + ("..." if len(final_text.strip()) > 140 else "")) if final_text else ""
        summary = f"Objective: {objective}. Replied. " + (f"Snippet: {snippet}" if snippet else "Completed.")
    if len(summary) > 400:
        summary = summary[:397] + "..."
    try:
        from services.memory_router import save_learning  # canonical write path

        save_learning(content=summary, kind="outcome")
    except Exception as e:
        logger.debug("outcome memory save failed: %s", e)

    # Layla v3: tool success patterns (high precision, deterministic).
    # Persist compact "what worked" snippets from successful tool steps.
    try:
        from services.memory_router import save_learning  # canonical write path

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
                _recent_tool_pattern_fingerprints.add(fp)
                if len(_recent_tool_pattern_fingerprints) > 300:
                    _recent_tool_pattern_fingerprints = set(list(_recent_tool_pattern_fingerprints)[-160:])
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
        from services.reflection_engine import run_reflection

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
                from services.golden_examples import store_golden_example

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
        from services.memory_consolidation import reinforce_learning

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


def _auto_extract_learnings(user_msg: str, response: str, aspect_id: str) -> None:
    """Background thread: extract 1-2 concise learnings from a completed exchange and persist them."""
    global _recent_learning_fingerprints
    try:
        resp_clean = response.strip()
        words = resp_clean.split()
        if len(words) < 20:
            return
        first_words = set(w.lower().strip(".,!?") for w in words[:6])
        if first_words.issubset(_GREETING_WORDS):
            return

        learning_type = _ASPECT_LEARNING_TYPE.get(aspect_id, "fact")
        extracted = []

        try:
            from services.llm_gateway import run_completion

            prompt = (
                "Extract 1-2 concise, standalone, reusable insights from this exchange. "
                "Output only a valid JSON array of strings. Max 100 chars each. No explanation.\n\n"
                f"User: {user_msg[:250]}\n"
                f"Response: {resp_clean[:500]}"
            )
            raw = (run_completion(prompt=prompt, max_tokens=140, temperature=0.1) or "").strip()
            import json as _json
            import re as _re_al

            m = _re_al.search(r"\[.*?\]", raw, _re_al.DOTALL)
            if m:
                items = _json.loads(m.group(0))
                for item in items[:2]:
                    if isinstance(item, str) and len(item.strip()) >= 12:
                        extracted.append(item.strip()[:200])
        except Exception:
            pass

        if not extracted:
            import re as _re_al

            for line in resp_clean.split("\n"):
                line = line.strip()
                if _re_al.match(r"^[\d\-\*\•\–]\s+.{25,150}$", line):
                    clean = _re_al.sub(r"^[\d\-\*\•\–]\s+", "", line).strip()
                    if clean:
                        extracted.append(clean)
                elif any(
                    kw in line.lower()
                    for kw in [
                        "always ",
                        "never ",
                        "should ",
                        "must ",
                        "key insight",
                        "important:",
                        "note:",
                        "tip:",
                        "best practice",
                        "remember:",
                        "the solution",
                    ]
                ) and 25 < len(line) < 200:
                    extracted.append(line)
                if len(extracted) >= 2:
                    break

        if not extracted:
            return
        from services.memory_router import save_learning  # canonical write path

        saved = 0
        # Operator correction detection (high precision heuristic)
        try:
            um = (user_msg or "").strip()
            if um and any(k in um.lower() for k in ("actually", "that's wrong", "that is wrong", "no,", "not true", "correction")):
                corr = um.replace("\n", " ").strip()[:180]
                save_learning(content=f"Operator correction: {corr}", kind="preference")
        except Exception:
            pass

        # Implicit preference detection (high precision, exact phrase triggers).
        try:
            um = (user_msg or "").strip()
            ul = um.lower()
            triggers = (
                "i prefer ",
                "i like ",
                "i dislike ",
                "always use ",
                "never use ",
                "don't use ",
                "do not use ",
            )
            if um and any(t in ul for t in triggers) and len(um) <= 300:
                pref = um.replace("\n", " ").strip()
                fp = ("pref|" + pref[:80].lower()).strip()
                with _fingerprint_lock:
                    if fp not in _recent_learning_fingerprints:
                        _recent_learning_fingerprints.add(fp)
                        if len(_recent_learning_fingerprints) > 200:
                            _recent_learning_fingerprints = set(list(_recent_learning_fingerprints)[-100:])
                        save_learning(content=f"Operator preference: {pref}"[:240], kind="preference")
        except Exception:
            pass
        for item in extracted[:2]:
            fp = item[:60].lower()
            with _fingerprint_lock:
                if fp in _recent_learning_fingerprints:
                    continue
                _recent_learning_fingerprints.add(fp)
                if len(_recent_learning_fingerprints) > 200:
                    _recent_learning_fingerprints = set(list(_recent_learning_fingerprints)[-100:])
            try:
                save_learning(content=item, kind=learning_type)
                saved += 1
            except Exception:
                pass
        if saved:
            logger.debug("auto-learn: saved %d %s learnings (aspect=%s)", saved, learning_type, aspect_id)
    except Exception as e:
        logger.debug("auto-learn failed: %s", e)

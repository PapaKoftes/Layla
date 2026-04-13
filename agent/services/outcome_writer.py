"""
Post-run outcome memory, Echo aspect memories, patch extraction, auto-learnings.
Extracted from agent_loop (consolidation Phase 4).
"""
from __future__ import annotations

import logging
import threading

from layla.memory.db import save_aspect_memory as _db_save_aspect_memory

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
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] != "reason"]
    if not tool_steps or state.get("status") != "finished":
        return
    objective = (state.get("objective") or state.get("original_goal") or "")[:200]
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
    if len(summary) > 400:
        summary = summary[:397] + "..."
    try:
        from layla.memory.db import save_learning

        save_learning(content=summary, kind="outcome")
    except Exception as e:
        logger.debug("outcome memory save failed: %s", e)
    try:
        from services.reflection_engine import run_reflection

        run_reflection(state)
    except Exception as e:
        logger.debug("reflection engine failed: %s", e)


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
        from layla.memory.db import save_learning

        saved = 0
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

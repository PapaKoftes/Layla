"""Conversations — Layla SQLite."""
import json
import logging
import sqlite3
import threading

from layla.memory.db_connection import _conn
from layla.memory.migrations import migrate
from layla.time_utils import utcnow

logger = logging.getLogger("layla")


# ── conversation summaries (context overflow prevention) ────────────────────

def add_conversation_summary(summary: str) -> None:
    """Persist a conversation summary for long-term context retention. Stores embedding for retrieval."""
    if not (summary or "").strip():
        return
    migrate()
    summary_text = summary.strip()[:8000]
    embedding_id = ""
    try:
        from layla.memory.vector_store import add_vector, embed
        vec = embed(summary_text)
        embedding_id = add_vector(vec, {"content": summary_text, "type": "conversation_summary"})
    except Exception:
        pass
    with _conn() as db:
        db.execute(
            "INSERT INTO conversation_summaries (summary, created_at, embedding_id) VALUES (?,?,?)",
            (summary_text, utcnow().isoformat(), embedding_id),
        )
        db.commit()


def get_recent_conversation_summaries(n: int = 5) -> list[dict]:
    """Return the n most recent conversation summaries (newest first)."""
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT id, summary, created_at, embedding_id FROM conversation_summaries ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Durable long-conversation memory (plan #21) ─────────────────────────────
#
# THE 0-ROWS DEFECT: conversation_summaries had 0 rows for the life of the DB. The only writer was
# context_manager.summarize_history, which compacts the IN-MEMORY ring (shared_state._conv_histories,
# a deque(maxlen=20)) within a SINGLE long session — so short chats and cross-session tails never
# produced a persistent summary. These triggers read the PERSISTENT conversation_messages directly and
# fire on message-count / idle / session-end, independent of any live session.
#
# Best-effort, in-process dedup watermark: the durable message_count at which we last wrote a summary
# for a conversation. Prevents the periodic (every-N) and idle/session-end triggers from writing
# near-duplicate summaries of the same tail. It resets on process restart — worst case one redundant
# summary per recently-active conversation after a restart, which the idle job's recent-window scan
# bounds. conversation_summaries has no conversation_id column (summaries are a GLOBAL second-tier
# memory the head recalls via get_recent_conversation_summaries), so a persistent per-conversation
# watermark cannot live in that table without a schema change owned elsewhere.
_LAST_DURABLE_SUMMARY_COUNT: dict[str, int] = {}
_DURABLE_SUMMARY_LOCK = threading.Lock()

DURABLE_SUMMARY_EVERY_N = 16      # summarize on the in-memory ring's rolloff cadence (deque maxlen=20)
DURABLE_SUMMARY_MIN_MESSAGES = 6  # below this a chat is too short to be worth distilling
DURABLE_SUMMARY_MAX_TAIL = 30     # summarize at most the most-recent N durable messages


def summarize_conversation_to_durable_memory(
    conversation_id: str,
    *,
    min_messages: int = DURABLE_SUMMARY_MIN_MESSAGES,
    max_tail: int = DURABLE_SUMMARY_MAX_TAIL,
    force: bool = False,
) -> str | None:
    """DURABLE, session-independent long-conversation memory (plan #21). THE fix for the 0-rows defect.

    Summarize the tail of the PERSISTENT ``conversation_messages`` for ``conversation_id`` and WRITE a
    row to ``conversation_summaries`` via ``add_conversation_summary`` (which embeds best-effort and
    resolves the DB off LAYLA_DATA_DIR — no ``__file__``-relative writes). Fires the
    ``conversation_compacted`` liveness effect on a successful write.

    Returns the summary text written, or ``None`` (too few messages / nothing new since the last
    summary / the summarizer produced nothing persistable).

    ``force`` bypasses the min-messages and watermark gates and persists even the text-only truncation
    fallback (a session-end / manual snapshot). The AUTOMATIC callers persist only a real LLM summary
    and leave the watermark unadvanced so the idle job retries once the model is free — this keeps
    low-value truncation rows out of the global recall pool.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    try:
        migrate()
        all_msgs = get_conversation_messages(cid, limit=2000)
        total = len(all_msgs)
        if not force:
            if total < max(1, int(min_messages)):
                return None
            with _DURABLE_SUMMARY_LOCK:
                last = _LAST_DURABLE_SUMMARY_COUNT.get(cid, 0)
            if total <= last:
                return None  # nothing new persisted since the last durable summary
        # get_conversation_messages returns oldest-first; take the most-recent tail to summarize.
        tail = all_msgs[-max(1, int(max_tail)):]
        msgs = [{"role": m.get("role", ""), "content": m.get("content", "")} for m in tail]

        from services.context.context_manager import summarize_messages
        summary = (summarize_messages(msgs) or "").strip()
        if not summary:
            return None
        # Automatic path persists only a real LLM summary; force persists the truncation fallback too.
        if not (force or summary.startswith("[Earlier conversation summary]")):
            return None
        add_conversation_summary(summary)  # writes the row + embeds (best-effort), honouring LAYLA_DATA_DIR
        with _DURABLE_SUMMARY_LOCK:
            _LAST_DURABLE_SUMMARY_COUNT[cid] = total
        try:
            from services.observability import liveness
            liveness.fire("conversation_compacted")  # plan #21's built-in liveness check; never raises
        except Exception:
            pass
        return summary
    except Exception as e:
        logger.debug("summarize_conversation_to_durable_memory(%s) failed: %s", cid, e)
        return None


def _maybe_durable_summary_on_append(conversation_id: str, new_message_count: int) -> None:
    """Periodic durable-summary trigger, fired from append_conversation_message.

    Every N persisted messages, distill the conversation tail into a durable summary OFF the reply
    path (a daemon thread — the summarizer takes an LLM call this box cannot afford inline). This is
    the ACTIVE-long-session trigger; the idle scheduler job covers short chats that end before N.
    Best-effort; never raises into the caller.
    """
    try:
        cid = (conversation_id or "").strip()
        if not cid or int(new_message_count or 0) <= 0:
            return
        every_n = DURABLE_SUMMARY_EVERY_N
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
            if not bool(cfg.get("long_conversation_memory_enabled", True)):
                return
            every_n = max(2, int(cfg.get("long_conversation_summary_every_n", DURABLE_SUMMARY_EVERY_N)
                                 or DURABLE_SUMMARY_EVERY_N))
        except Exception:
            pass
        if new_message_count < every_n or new_message_count % every_n != 0:
            return
        threading.Thread(
            target=summarize_conversation_to_durable_memory,
            args=(cid,),
            daemon=True,
            name="durable-conv-summary",
        ).start()
    except Exception as e:
        logger.debug("_maybe_durable_summary_on_append(%s) failed: %s", conversation_id, e)


def recall_summaries_by_similarity(query: str, n: int = 3) -> list[dict]:
    """Semantic recall over durable conversation summaries (for future use).

    Embed ``query`` and return up to ``n`` stored conversation summaries ranked by vector similarity,
    filtered to ``type == 'conversation_summary'``. Read-only; degrades to ``[]`` when the embedder or
    vector store is unavailable. The head currently recalls the most-RECENT summaries
    (get_recent_conversation_summaries); this is the by-relevance counterpart.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        from layla.memory.vector_store import embed, search_similar
        vec = embed(q)
        hits = search_similar(vec, k=max(1, int(n)) * 4) or []
        out: list[dict] = []
        for h in hits:
            if not isinstance(h, dict) or h.get("type") != "conversation_summary":
                continue
            content = (h.get("content") or "").strip()
            if content:
                out.append({"summary": content, "embedding_id": h.get("embedding_id", "")})
            if len(out) >= max(1, int(n)):
                break
        return out
    except Exception as e:
        logger.debug("recall_summaries_by_similarity failed: %s", e)
        return []


import re as _re

# Leading politeness / question framing to strip so the title is the topic, not "can you help me…".
_TITLE_FILLER_RE = _re.compile(
    r"^(hey|hi|hello|ok|okay|so|um|please|pls|can you|could you|would you|will you|"
    r"i want to|i wanna|i need to|i'?d like to|help me|let'?s|lets|"
    r"how (do|can|would|should) i|how to|what'?s|what is|what are|tell me( about)?|"
    r"give me|show me|explain|write( me)?|make( me)?|create|build)\s+",
    _re.IGNORECASE,
)


def _auto_name_conversation(first_user_message: str) -> str:
    """A short topic title extracted from the first message (not a raw 40-char truncation).

    This is the instant placeholder; an LLM may polish it async on the first exchange
    (see services/agent/title_synthesizer.py). Returns 'New chat' only for empty input.
    """
    t = _re.sub(r"\s+", " ", (first_user_message or "").strip())
    if not t:
        return "New chat"
    # Strip chained leading filler ("can you help me …" → "…") up to a few times, but never to empty.
    core = t
    for _ in range(3):
        stripped = _TITLE_FILLER_RE.sub("", core).strip()
        if not stripped or stripped == core:
            break
        core = stripped
    core = _re.sub(r"[,\s]+(please|pls|thanks|thank you|thx)\s*$", "", core, flags=_re.IGNORECASE).strip() or t
    words = core.split()
    title = " ".join(words[:7])
    if len(title) > 52:
        title = title[:52].rsplit(" ", 1)[0]
    title = title.rstrip(" .,:;-?!—")
    if not title:
        return "New chat"
    return title[:1].upper() + title[1:]


def create_conversation(conversation_id: str, title: str = "", aspect_id: str = "") -> dict:
    migrate()
    now = utcnow().isoformat()
    cid = (conversation_id or "").strip()
    if not cid:
        import uuid

        cid = str(uuid.uuid4())
    with _conn() as db:
        db.execute(
            """INSERT OR IGNORE INTO conversations
               (id, title, aspect_id, dominant_aspect, created_at, updated_at, message_count)
               VALUES (?,?,?,?,?,?,0)""",
            (cid, (title or "").strip(), (aspect_id or "").strip(), (aspect_id or "").strip(), now, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else {"id": cid}


def get_conversation(conversation_id: str) -> dict | None:
    migrate()
    with _conn() as db:
        row = db.execute("SELECT * FROM conversations WHERE id=?", ((conversation_id or "").strip(),)).fetchone()
    return dict(row) if row else None


def list_conversations(limit: int = 200, offset: int = 0) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (max(1, min(int(limit), 1000)), max(0, int(offset or 0))),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_conversation(conversation_id: str, title: str) -> bool:
    migrate()
    with _conn() as db:
        cur = db.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            ((title or "").strip()[:120], utcnow().isoformat(), (conversation_id or "").strip()),
        )
        db.commit()
        return cur.rowcount > 0


def delete_conversation(conversation_id: str) -> bool:
    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    with _conn() as db:
        db.execute("DELETE FROM conversation_messages WHERE conversation_id=?", (cid,))
        # Clear the parent link on any child fork so it doesn't dangle at a now-missing parent (the
        # fork-tree UI would otherwise show a broken parent reference). The child + its messages stay intact.
        db.execute("UPDATE conversations SET parent_id='' WHERE parent_id=?", (cid,))
        cur = db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        db.commit()
        return cur.rowcount > 0


def clear_all_conversations() -> int:
    """Delete every conversation and its messages. Returns the number of conversations removed."""
    migrate()
    with _conn() as db:
        n = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        db.execute("DELETE FROM conversation_messages")
        db.execute("DELETE FROM conversations")
        db.commit()
    return int(n or 0)


def append_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    aspect_id: str = "",
    token_count: int = 0,
) -> str:
    import uuid

    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        create = create_conversation("", "")
        cid = create["id"]
    msg_id = str(uuid.uuid4())
    now = utcnow().isoformat()
    safe_content = (content or "").strip()
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        max_chars = int(cfg.get("conversation_message_max_chars", 100_000) or 100_000)
        if max_chars > 0 and len(safe_content) > max_chars:
            safe_content = safe_content[:max_chars]
    except Exception:
        # Fallback: fixed cap to avoid unbounded DB writes.
        if len(safe_content) > 100_000:
            safe_content = safe_content[:100_000]
    safe_role = (role or "assistant").strip()
    new_count = 0
    with _conn() as db:
        db.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, role, content, aspect_id, created_at, token_count)
               VALUES (?,?,?,?,?,?,?)""",
            (msg_id, cid, safe_role, safe_content, (aspect_id or "").strip(), now, max(0, int(token_count or 0))),
        )
        row = db.execute("SELECT title, message_count FROM conversations WHERE id=?", (cid,)).fetchone()
        title = (row["title"] or "").strip() if row else ""
        count = int(row["message_count"] or 0) if row else 0
        new_count = count + 1  # this INSERT is the (count+1)-th durable message for the conversation
        if safe_role == "user" and not title and count == 0:
            title = _auto_name_conversation(safe_content)
        dom = (aspect_id or "").strip()
        db.execute(
            """UPDATE conversations
               SET updated_at=?, message_count=COALESCE(message_count,0)+1,
                   title=CASE WHEN ?!='' THEN ? ELSE title END,
                   dominant_aspect=CASE WHEN ?!='' THEN ? ELSE dominant_aspect END,
                   aspect_id=CASE WHEN ?!='' THEN ? ELSE aspect_id END
               WHERE id=?""",
            (now, title, title, dom, dom, dom, dom, cid),
        )
        db.commit()
    # Plan #21: durable long-conversation memory. Every N persisted messages, summarize the tail into
    # conversation_summaries off the reply path. Fully best-effort — a summariser hiccup must never
    # break a message write.
    _maybe_durable_summary_on_append(cid, new_count)
    return msg_id


def get_conversation_messages(conversation_id: str, limit: int = 200) -> list[dict]:
    migrate()
    with _conn() as db:
        rows = db.execute(
            """SELECT id, conversation_id, role, content, aspect_id, created_at, token_count
               FROM conversation_messages
               WHERE conversation_id=?
               ORDER BY created_at ASC
               LIMIT ?""",
            ((conversation_id or "").strip(), max(1, min(int(limit), 2000))),
        ).fetchall()
    return [dict(r) for r in rows]


def search_conversations(query: str, limit: int = 50) -> list[dict]:
    migrate()
    q = (query or "").strip()
    if not q:
        return list_conversations(limit=limit)
    with _conn() as db:
        rows = db.execute(
            """SELECT DISTINCT c.*
               FROM conversations c
               LEFT JOIN conversation_messages m ON m.conversation_id = c.id
               WHERE c.title LIKE ? OR m.content LIKE ?
               ORDER BY c.updated_at DESC
               LIMIT ?""",
            (f"%{q}%", f"%{q}%", max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(r) for r in rows]


def _normalize_tags(tags: str | list[str]) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = tags.replace(";", ",").replace("|", ",")
        parts = [p.strip().lower() for p in raw.split(",")]
    else:
        parts = [str(p).strip().lower() for p in tags]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if not p:
            continue
        # keep tags lightweight + safe for LIKE matching
        safe = "".join(ch for ch in p if ch.isalnum() or ch in ("_", "-", "/"))[:32].strip()
        if not safe or safe in seen:
            continue
        seen.add(safe)
        out.append(safe)
    return out


def set_conversation_tags(conversation_id: str, tags: str | list[str]) -> bool:
    """Set tags for a conversation. Stored as comma-separated normalized tags."""
    migrate()
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    norm = _normalize_tags(tags)
    tags_s = ",".join(norm)
    with _conn() as db:
        cur = db.execute(
            "UPDATE conversations SET tags=?, updated_at=? WHERE id=?",
            (tags_s, utcnow().isoformat(), cid),
        )
        db.commit()
        return cur.rowcount > 0


def suggest_conversation_tags(prefix: str = "", limit: int = 20) -> list[str]:
    migrate()
    p = (prefix or "").strip().lower()
    with _conn() as db:
        rows = db.execute(
            "SELECT tags FROM conversations WHERE tags IS NOT NULL AND tags != '' ORDER BY updated_at DESC LIMIT 800"
        ).fetchall()
    pool: list[str] = []
    for r in rows:
        ts = (r["tags"] or "").strip()
        if not ts:
            continue
        pool.extend(_normalize_tags(ts))
    uniq: list[str] = []
    seen: set[str] = set()
    for t in pool:
        if p and not t.startswith(p):
            continue
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
        if len(uniq) >= max(1, min(int(limit or 20), 100)):
            break
    return uniq


def list_conversations_filtered(limit: int = 200, tag: str | None = None, offset: int = 0) -> list[dict]:
    migrate()
    t = (tag or "").strip().lower()
    if not t:
        return list_conversations(limit=limit, offset=offset)
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM conversations WHERE (','||COALESCE(tags,'')||',') LIKE ? "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (f"%,{t},%", max(1, min(int(limit), 1000)), max(0, int(offset or 0))),
        ).fetchall()
    return [dict(r) for r in rows]


def search_conversations_filtered(query: str, limit: int = 50, tag: str | None = None, offset: int = 0) -> list[dict]:
    migrate()
    q = (query or "").strip()
    t = (tag or "").strip().lower()
    if not q:
        return list_conversations_filtered(limit=limit, tag=t or None, offset=offset)
    tag_sql = ""
    args: list = [f"%{q}%", f"%{q}%"]
    if t:
        tag_sql = " AND (','||COALESCE(c.tags,'')||',') LIKE ?"
        args.append(f"%,{t},%")
    args.append(max(1, min(int(limit), 500)))
    args.append(max(0, int(offset or 0)))
    with _conn() as db:
        rows = db.execute(
            f"""SELECT DISTINCT c.*
               FROM conversations c
               LEFT JOIN conversation_messages m ON m.conversation_id = c.id
               WHERE (c.title LIKE ? OR m.content LIKE ?){tag_sql}
               ORDER BY c.updated_at DESC
               LIMIT ? OFFSET ?""",
            tuple(args),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Conversation branching / time-travel (git-for-dialogue) ─────────────────

def fork_conversation(source_id: str, *, at_message_id: str = "", new_title: str = "") -> dict | None:
    """Branch a conversation: create a NEW conversation that copies the source's messages up
    to (and including) at_message_id, linked back to the source. Empty at_message_id copies
    the whole conversation. The new branch can then continue independently ("rewind + explore
    a different path"). Returns the new conversation row, or None if source/message not found."""
    import uuid

    migrate()
    src = (source_id or "").strip()
    parent = get_conversation(src)
    if not parent:
        return None
    msgs = get_conversation_messages(src, limit=2000)
    if at_message_id:
        idx = next((i for i, m in enumerate(msgs) if m.get("id") == at_message_id), None)
        if idx is None:
            return None
        msgs = msgs[: idx + 1]

    new_id = str(uuid.uuid4())
    base_title = (new_title or "").strip() or ((parent.get("title") or "Conversation") + " (branch)")
    now = utcnow().isoformat()
    with _conn() as db:
        db.execute(
            """INSERT INTO conversations
               (id, title, aspect_id, dominant_aspect, created_at, updated_at, message_count, parent_id, forked_at_message_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_id, base_title[:120], parent.get("aspect_id", "") or "", parent.get("dominant_aspect", "") or "",
                now, now, len(msgs), src, (at_message_id or ""),
            ),
        )
        for m in msgs:
            db.execute(
                """INSERT INTO conversation_messages
                   (id, conversation_id, role, content, aspect_id, created_at, token_count)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), new_id, m.get("role", ""), m.get("content", ""),
                 m.get("aspect_id", "") or "", m.get("created_at", now), int(m.get("token_count", 0) or 0)),
            )
        db.commit()
    return get_conversation(new_id)


def list_branches(conversation_id: str) -> dict | None:
    """Return this conversation's branch relationships: its parent (if it is itself a fork)
    and its direct children (branches forked from it), for a fork tree / picker."""
    migrate()
    cid = (conversation_id or "").strip()
    conv = get_conversation(cid)
    if not conv:
        return None
    with _conn() as db:
        children = db.execute(
            """SELECT id, title, created_at, forked_at_message_id, message_count
               FROM conversations WHERE parent_id=? ORDER BY created_at ASC""",
            (cid,),
        ).fetchall()
    return {
        "id": cid,
        "parent_id": conv.get("parent_id") or "",
        "forked_at_message_id": conv.get("forked_at_message_id") or "",
        "branches": [dict(r) for r in children],
    }


def compare_conversations(a_id: str, b_id: str) -> dict:
    """Diff two conversations (typically a branch vs its parent): the common leading prefix
    by (role, content), then each side's divergent tail — time-travel compare."""
    migrate()
    a = get_conversation_messages((a_id or "").strip(), limit=2000)
    b = get_conversation_messages((b_id or "").strip(), limit=2000)
    common = 0
    for ma, mb in zip(a, b):
        if ma.get("role") == mb.get("role") and ma.get("content") == mb.get("content"):
            common += 1
        else:
            break
    _slim = lambda ms: [{"role": m.get("role"), "content": m.get("content")} for m in ms]  # noqa: E731
    return {
        "a_id": a_id,
        "b_id": b_id,
        "common_prefix_len": common,
        "a_divergent": _slim(a[common:]),
        "b_divergent": _slim(b[common:]),
    }



"""Verification Queue — learn-and-verify loop for user-confirmed knowledge.

When Layla infers facts about the user (from documents, conversations,
or autonomous research), she queues them for verification rather than
assuming they're true.  The user confirms or corrects during natural
conversation flow.

Rules:
- Max 3 verification prompts per session (don't be annoying)
- 24h cooldown per fact (don't re-ask too soon)
- High-importance facts are asked first
- Confirmed facts get confidence=1.0
- Denied facts are marked 'rejected' and not used

Phase 5B of the distributed infrastructure plan.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("layla")


# ── Constants ────────────────────────────────────────────────────────────

MAX_PROMPTS_PER_SESSION = 3
COOLDOWN_HOURS = 24
MIN_CONFIDENCE_TO_SKIP = 0.9  # Already confident enough, don't ask


class VerificationQueue:
    """Manages the verification queue for inferred facts.

    The queue is backed by the ``verification_queue`` SQLite table
    (created in migrations.py).
    """

    def __init__(self):
        self._prompts_this_session = 0
        self._ensure_table()

    @staticmethod
    def _ensure_table() -> None:
        """Idempotent table creation."""
        try:
            from layla.memory.db_connection import _conn
            with _conn() as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS verification_queue (
                        id           TEXT PRIMARY KEY,
                        fact_content TEXT NOT NULL,
                        source       TEXT DEFAULT 'inferred',
                        confidence   REAL DEFAULT 0.5,
                        importance   REAL DEFAULT 0.5,
                        status       TEXT DEFAULT 'pending',
                        ask_count    INTEGER DEFAULT 0,
                        last_asked   TEXT,
                        user_answer  TEXT,
                        created_at   TEXT NOT NULL,
                        resolved_at  TEXT
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_verification_queue_status ON verification_queue(status)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_verification_queue_importance ON verification_queue(importance DESC)")
                db.commit()
        except Exception as e:
            logger.debug("verification_queue ensure failed: %s", e)

    # ── Submit facts for verification ────────────────────────────────

    def submit(
        self,
        fact: str,
        source: str = "inferred",
        confidence: float = 0.5,
        importance: float = 0.5,
    ) -> str | None:
        """Add a fact to the verification queue.

        Deduplicates by content hash.  Returns the fact ID or None if duplicate.
        """
        if not fact.strip():
            return None

        # Skip if already very confident
        if confidence >= MIN_CONFIDENCE_TO_SKIP:
            return None

        fact_hash = hashlib.sha256(fact.encode()).hexdigest()[:16]

        try:
            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow

            with _conn() as db:
                # Check for duplicate
                existing = db.execute(
                    "SELECT id FROM verification_queue WHERE id = ?",
                    (fact_hash,),
                ).fetchone()
                if existing:
                    return None

                db.execute(
                    """INSERT INTO verification_queue
                       (id, fact_content, source, confidence, importance, status, created_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                    (fact_hash, fact, source, confidence, importance, utcnow().isoformat()),
                )
                db.commit()
                logger.debug("Verification queued: %s (importance=%.1f)", fact[:50], importance)
                return fact_hash

        except Exception as e:
            logger.debug("Verification submit failed: %s", e)
            return None

    # ── Get next fact to verify ──────────────────────────────────────

    def get_next(self) -> dict[str, Any] | None:
        """Get the next fact to ask the user about.

        Returns None if:
        - Session limit reached (max 3 per session)
        - No facts pending
        - All pending facts are in cooldown
        """
        if self._prompts_this_session >= MAX_PROMPTS_PER_SESSION:
            return None

        try:
            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow

            cooldown_cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
            ).isoformat()

            with _conn() as db:
                row = db.execute(
                    """SELECT id, fact_content, source, confidence, importance, ask_count
                       FROM verification_queue
                       WHERE status = 'pending'
                       AND (last_asked IS NULL OR last_asked < ?)
                       ORDER BY importance DESC, created_at ASC
                       LIMIT 1""",
                    (cooldown_cutoff,),
                ).fetchone()

                if not row:
                    return None

                def _g(key, default=None):
                    if isinstance(row, dict):
                        return row.get(key, default)
                    try:
                        return row[key]
                    except (IndexError, KeyError):
                        return default

                fact_id = _g("id")
                # Update ask timestamp and count
                db.execute(
                    """UPDATE verification_queue
                       SET last_asked = ?, ask_count = ask_count + 1
                       WHERE id = ?""",
                    (utcnow().isoformat(), fact_id),
                )
                db.commit()

                self._prompts_this_session += 1

                return {
                    "id": fact_id,
                    "fact": _g("fact_content"),
                    "source": _g("source", "inferred"),
                    "confidence": _g("confidence", 0.5),
                    "importance": _g("importance", 0.5),
                    "ask_count": _g("ask_count", 0) + 1,
                    "prompt_number": self._prompts_this_session,
                    "max_prompts": MAX_PROMPTS_PER_SESSION,
                }

        except Exception as e:
            logger.debug("get_next verification failed: %s", e)
            return None

    # ── Record user's answer ─────────────────────────────────────────

    def answer(self, fact_id: str, confirmed: bool, correction: str = "") -> dict[str, Any]:
        """Record the user's verification answer.

        Parameters
        ----------
        fact_id : str
            The fact ID from get_next().
        confirmed : bool
            True if user confirms the fact is correct.
        correction : str
            If not confirmed, the user's correction (optional).
        """
        try:
            from layla.memory.db_connection import _conn
            from layla.time_utils import utcnow

            now = utcnow().isoformat()
            status = "confirmed" if confirmed else "rejected"
            answer_text = "confirmed" if confirmed else (correction or "rejected")

            with _conn() as db:
                db.execute(
                    """UPDATE verification_queue
                       SET status = ?, user_answer = ?, resolved_at = ?
                       WHERE id = ?""",
                    (status, answer_text, now, fact_id),
                )
                db.commit()

                if confirmed:
                    # Get the fact content to update confidence in learnings
                    row = db.execute(
                        "SELECT fact_content, source FROM verification_queue WHERE id = ?",
                        (fact_id,),
                    ).fetchone()
                    if row:
                        fact_content = row["fact_content"] if isinstance(row, dict) else row[0]
                        # Update matching learnings to confidence=1.0
                        content_hash = hashlib.sha256(fact_content.encode()).hexdigest()[:32]
                        db.execute(
                            """UPDATE learnings SET confidence = 1.0
                               WHERE content_hash = ? OR content LIKE ?""",
                            (content_hash, f"%{fact_content[:50]}%"),
                        )
                        db.commit()
                        logger.info("Verified fact: %s → confirmed", fact_content[:50])
                        # Maturity: award XP for user-verified fact
                        try:
                            from services.personality.maturity_engine import award_xp
                            award_xp(12, reason=f"fact_verified:{fact_id}"[:80])
                        except Exception:
                            pass
                        # Phase 3C: Auto-generate wiki entry from verified fact
                        try:
                            from autonomous.wiki import build_candidate, write_wiki_entry
                            import runtime_safety
                            _wiki_cfg = runtime_safety.load_config()
                            _wiki_candidate = build_candidate(
                                title=fact_content[:60],
                                content_md=fact_content,
                            )
                            write_wiki_entry(
                                workspace_root=str(Path.home()),
                                candidate=_wiki_candidate,
                                allow_write=True,
                                cfg=_wiki_cfg,
                                domain="facts",
                            )
                        except Exception as _wiki_exc:
                            logger.debug("wiki auto-write from verified fact failed: %s", _wiki_exc)

                elif correction:
                    # Store the correction as a new high-confidence learning
                    db.execute(
                        """INSERT INTO learnings
                           (content, type, created_at, source, confidence, content_hash)
                           VALUES (?, 'correction', ?, 'user_correction', 1.0, ?)""",
                        (
                            correction,
                            now,
                            hashlib.sha256(correction.encode()).hexdigest()[:32],
                        ),
                    )
                    db.commit()
                    logger.info("Fact corrected: %s", correction[:50])

            return {"ok": True, "fact_id": fact_id, "status": status}

        except Exception as e:
            logger.warning("Verification answer failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return verification queue statistics."""
        try:
            from layla.memory.db_connection import _conn
            with _conn() as db:
                total = db.execute("SELECT COUNT(*) FROM verification_queue").fetchone()
                pending = db.execute(
                    "SELECT COUNT(*) FROM verification_queue WHERE status = 'pending'"
                ).fetchone()
                confirmed = db.execute(
                    "SELECT COUNT(*) FROM verification_queue WHERE status = 'confirmed'"
                ).fetchone()
                rejected = db.execute(
                    "SELECT COUNT(*) FROM verification_queue WHERE status = 'rejected'"
                ).fetchone()

                def _val(r):
                    if r is None:
                        return 0
                    return r[0] if not isinstance(r, dict) else list(r.values())[0]

                total_n = _val(total)
                confirmed_n = _val(confirmed)

                return {
                    "total": total_n,
                    "pending": _val(pending),
                    "confirmed": confirmed_n,
                    "rejected": _val(rejected),
                    "verified_percent": round(
                        confirmed_n / total_n * 100 if total_n > 0 else 0, 1
                    ),
                    "prompts_this_session": self._prompts_this_session,
                    "max_prompts_per_session": MAX_PROMPTS_PER_SESSION,
                }
        except Exception:
            return {"total": 0, "pending": 0, "confirmed": 0, "rejected": 0}

    def reset_session(self) -> None:
        """Reset the per-session prompt counter (call on new conversation)."""
        self._prompts_this_session = 0


# ── Module-level singleton ───────────────────────────────────────────────

_queue: VerificationQueue | None = None


def get_verification_queue() -> VerificationQueue:
    """Get or create the singleton VerificationQueue."""
    global _queue
    if _queue is None:
        _queue = VerificationQueue()
    return _queue


def submit_for_verification(
    fact: str,
    source: str = "inferred",
    confidence: float = 0.5,
    importance: float = 0.5,
) -> str | None:
    """Convenience: submit a fact for verification."""
    return get_verification_queue().submit(fact, source, confidence, importance)


def get_next_verification() -> dict[str, Any] | None:
    """Convenience: get the next fact to verify."""
    return get_verification_queue().get_next()

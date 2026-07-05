"""Personal operating manual (BL-236) — a living "how you work" doc.

Consolidates what Layla knows about *how the operator likes to work* into one document
that personalises prompts: the identity signals (verbosity, humour, formality, response
length), the operator-quiz profile (work domains, key traits), and a growing set of
user-appended notes (habits, recurring workflows, comm-style preferences). The identity
half is derived live so it's always current; the notes half accrues over time — together
they make a manual that evolves rather than a one-time snapshot.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

NOTE_CATEGORIES = ("habit", "workflow", "preference", "comm_style", "tool", "other")

_IDENTITY_LABELS = {
    "verbosity": "Verbosity",
    "humor_tolerance": "Humour",
    "humour_preference": "Humour",
    "formality": "Formality",
    "response_length": "Response length",
    "life_narrative_summary": "About them",
}


def _data_dir() -> Path:
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "operating_manual.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS manual_note (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── user-appended notes (the "living" half) ──────────────────────────────────
def add_note(category: str, text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "text required"}
    category = category if category in NOTE_CATEGORIES else "other"
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO manual_note (category, text, created_at) VALUES (?,?,?)",
            (category, text[:1000], time.time()),
        )
        return {"ok": True, "id": cur.lastrowid, "category": category}


def list_notes() -> list[dict]:
    with _db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, category, text, created_at FROM manual_note ORDER BY category, created_at"
        ).fetchall()]


def delete_note(note_id: int) -> dict[str, Any]:
    with _db() as conn:
        cur = conn.execute("DELETE FROM manual_note WHERE id=?", (int(note_id),))
        return {"ok": cur.rowcount > 0}


# ── derived identity (the "always current" half) ─────────────────────────────
def _identity() -> dict[str, str]:
    try:
        from layla.memory.user_profile import get_all_user_identity
        return get_all_user_identity() or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("operating_manual identity load failed: %s", e)
        return {}


def _profile() -> dict[str, Any]:
    try:
        from services.personality.operator_quiz import load_profile
        return load_profile() or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("operating_manual profile load failed: %s", e)
        return {}


def build_manual() -> dict[str, Any]:
    """Assemble the operating manual: derived identity + profile + user notes."""
    uid = _identity()
    prof = _profile()

    identity = {}
    for key, label in _IDENTITY_LABELS.items():
        val = (uid.get(key) or "").strip()
        if val:
            identity[label] = val

    notes: dict[str, list[str]] = {}
    for n in list_notes():
        notes.setdefault(n["category"], []).append(n["text"])

    return {
        "identity": identity,
        "work_domains": prof.get("work_domains", []),
        "traits": prof.get("stats", {}),
        "notes": notes,
    }


def manual_markdown() -> str:
    m = build_manual()
    lines = ["# Operating manual — how they work", ""]
    if m["identity"]:
        lines.append("## Style")
        for label, val in m["identity"].items():
            lines.append(f"- **{label}:** {val}")
        lines.append("")
    if m["work_domains"]:
        lines.append("## Work domains")
        lines.append("- " + ", ".join(m["work_domains"]))
        lines.append("")
    if m["notes"]:
        lines.append("## Habits & workflows")
        for cat, items in m["notes"].items():
            for it in items:
                lines.append(f"- _{cat}_: {it}")
        lines.append("")
    if len(lines) <= 2:
        lines.append("_The manual is empty — it fills in as Layla learns how you work._")
    return "\n".join(lines).strip()


def manual_for_prompt(max_chars: int = 600) -> str:
    """A compact digest for injecting into the system prompt."""
    m = build_manual()
    bits: list[str] = []
    for label, val in m["identity"].items():
        bits.append(f"{label.lower()}={val}")
    if m["work_domains"]:
        bits.append("domains: " + ", ".join(m["work_domains"][:5]))
    flat_notes = [f"{c}: {t}" for c, items in m["notes"].items() for t in items]
    if flat_notes:
        bits.append("notes — " + "; ".join(flat_notes[:6]))
    text = " · ".join(bits)
    return text[:max_chars]

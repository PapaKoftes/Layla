"""
services/german_mode.py — German language learning mode (Item #10)

Features:
  - CEFR level calibration (B1/B2 default, configurable A1–C2)
  - Per-turn grammar/vocabulary correction with explanations
  - Flashcard deck management (SQLite-backed)
  - Sentence complexity scoring (word count, subordinate clauses, case markers)
  - Adaptive difficulty: level auto-adjusts on streaks
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# CEFR configuration
# ---------------------------------------------------------------------------

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
_LEVEL_IDX = {lvl: i for i, lvl in enumerate(CEFR_LEVELS)}

# Typical vocabulary thresholds and sentence complexity ceilings per level
_LEVEL_PARAMS: dict[str, dict] = {
    "A1": {"max_words": 8,   "clause_limit": 1, "vocab_band": 800},
    "A2": {"max_words": 12,  "clause_limit": 1, "vocab_band": 1500},
    "B1": {"max_words": 18,  "clause_limit": 2, "vocab_band": 3500},
    "B2": {"max_words": 25,  "clause_limit": 3, "vocab_band": 6500},
    "C1": {"max_words": 35,  "clause_limit": 4, "vocab_band": 12000},
    "C2": {"max_words": 50,  "clause_limit": 6, "vocab_band": 25000},
}

# Common grammar error patterns (heuristic, no NLP required)
_ERROR_PATTERNS: list[dict] = [
    {
        "name": "adjective_ending_nominative",
        "pattern": r"\b(ein|eine|einer|einen)\s+([A-Z][a-züäöß]+(?:er|em|en|es))\b",
        "hint": "Adjektivendungen im Nominativ: ein großer Mann, eine große Frau",
        "level": "A2",
    },
    {
        "name": "verb_second_position",
        "pattern": r"^(Heute|Morgen|Jetzt|Dann|Danach|Gestern)\s+([A-ZÜÄÖ][a-züäöß]+)\s+(ich|du|er|sie|wir|ihr)\b",
        "hint": "Verb-Zweitstellung: 'Heute gehe ich…' (Verb muss an zweiter Stelle stehen)",
        "level": "A2",
    },
    {
        "name": "dative_after_mit",
        "pattern": r"\bmit\s+(der|die|das|ein|eine)\b",
        "hint": "'mit' verlangt den Dativ: mit dem/der/dem",
        "level": "B1",
    },
    {
        "name": "konjunktiv_ii",
        "pattern": r"\b(würde|würden|würdest)\s+\w+en\b",
        "hint": "Konjunktiv II: korrekt gebildet — prüfen Sie, ob ein starkes Verb möglich wäre (hätte/wäre statt würde haben/würde sein)",
        "level": "B2",
    },
    {
        "name": "dass_vs_das",
        "pattern": r"\b(das)\s+(ich|du|er|sie|wir|ihr|man)\s+\w+e?\b",
        "hint": "'dass' (Konjunktion) vs 'das' (Artikel/Pronomen): Nebensatz → dass",
        "level": "B1",
    },
]

# Flashcard state machine
CARD_STATES = ["new", "learning", "review", "mastered"]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> Path:
    """Derive path to german_mode.db from layla memory location."""
    try:
        from layla.memory.db_connection import _resolve_db_path
        return _resolve_db_path().parent / "german_mode.db"
    except Exception:
        return Path.home() / ".layla" / "german_mode.db"


def _open_db() -> sqlite3.Connection:
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


from contextlib import contextmanager


@contextmanager
def _db_ctx():
    """Context manager that guarantees _open_db() connections are closed on any exit path."""
    conn = _open_db()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS german_profile (
            user_id     TEXT PRIMARY KEY DEFAULT 'default',
            level       TEXT NOT NULL DEFAULT 'B1',
            streak_ok   INTEGER DEFAULT 0,
            streak_err  INTEGER DEFAULT 0,
            sessions    INTEGER DEFAULT 0,
            updated_at  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS flashcards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL DEFAULT 'default',
            front       TEXT NOT NULL,
            back        TEXT NOT NULL,
            example     TEXT DEFAULT '',
            tags        TEXT DEFAULT '',
            state       TEXT DEFAULT 'new',
            ease_factor REAL DEFAULT 2.5,
            interval    INTEGER DEFAULT 1,
            due_at      TEXT DEFAULT '',
            reps        INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT '',
            updated_at  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS correction_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL DEFAULT 'default',
            original    TEXT NOT NULL,
            corrected   TEXT NOT NULL,
            errors      TEXT DEFAULT '[]',
            level       TEXT DEFAULT 'B1',
            created_at  TEXT DEFAULT ''
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

def get_profile(user_id: str = "default") -> dict:
    """Return the user's German learning profile, creating defaults if absent."""
    try:
        with _db_ctx() as conn:
            row = conn.execute(
                "SELECT * FROM german_profile WHERE user_id=?", (user_id,)
            ).fetchone()
            if row:
                return dict(row)
            # Create default
            from layla.time_utils import utcnow
            conn.execute(
                "INSERT INTO german_profile (user_id, level, updated_at) VALUES (?,?,?)",
                (user_id, "B1", utcnow().isoformat()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM german_profile WHERE user_id=?", (user_id,)
            ).fetchone()
            return dict(row)
    except Exception as e:
        logger.debug("german_mode.get_profile failed: %s", e)
        return {"user_id": user_id, "level": "B1", "streak_ok": 0, "streak_err": 0, "sessions": 0}


def set_level(level: str, user_id: str = "default") -> dict:
    """Set the CEFR level for a user."""
    level = level.upper().strip()
    if level not in CEFR_LEVELS:
        raise ValueError(f"Invalid CEFR level: {level!r}. Use one of {CEFR_LEVELS}")
    try:
        from layla.time_utils import utcnow
        with _db_ctx() as conn:
            conn.execute(
                "INSERT INTO german_profile (user_id, level, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET level=excluded.level, updated_at=excluded.updated_at",
                (user_id, level, utcnow().isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.debug("german_mode.set_level failed: %s", e)
    return get_profile(user_id)


def _adapt_level(profile: dict, correct: bool, user_id: str = "default") -> str | None:
    """Auto-advance or drop level on streaks. Returns new level if changed, else None."""
    try:
        from layla.time_utils import utcnow
        with _db_ctx() as conn:
            field = "streak_ok" if correct else "streak_err"
            reset_field = "streak_err" if correct else "streak_ok"
            conn.execute(
                f"UPDATE german_profile SET {field}={field}+1, {reset_field}=0, sessions=sessions+1, updated_at=? "
                "WHERE user_id=?",
                (utcnow().isoformat(), user_id),
            )
            conn.commit()
            profile_new = get_profile(user_id)
            current = profile_new["level"]
            idx = _LEVEL_IDX[current]

            new_level = None
            if profile_new["streak_ok"] >= 10 and idx < len(CEFR_LEVELS) - 1:
                new_level = CEFR_LEVELS[idx + 1]
            elif profile_new["streak_err"] >= 8 and idx > 0:
                new_level = CEFR_LEVELS[idx - 1]

            if new_level:
                conn.execute(
                    "UPDATE german_profile SET level=?, streak_ok=0, streak_err=0, updated_at=? WHERE user_id=?",
                    (new_level, utcnow().isoformat(), user_id),
                )
                conn.commit()

            return new_level
    except Exception as e:
        logger.debug("german_mode._adapt_level failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Correction engine
# ---------------------------------------------------------------------------

def _count_subclauses(text: str) -> int:
    """Heuristic: count subordinate clause markers."""
    markers = r"\b(weil|dass|obwohl|wenn|während|nachdem|bevor|damit|sodass|falls|ob)\b"
    return len(re.findall(markers, text, re.I))


def _word_count(text: str) -> int:
    return len(text.split())


def score_complexity(text: str) -> dict:
    """Return a complexity report for a German sentence."""
    words = _word_count(text)
    clauses = _count_subclauses(text)
    # Map to approximate CEFR level
    if words <= 8 and clauses == 0:
        est_level = "A1"
    elif words <= 12 and clauses <= 1:
        est_level = "A2"
    elif words <= 18 and clauses <= 2:
        est_level = "B1"
    elif words <= 25 and clauses <= 3:
        est_level = "B2"
    elif words <= 35 and clauses <= 4:
        est_level = "C1"
    else:
        est_level = "C2"
    return {
        "word_count": words,
        "subclause_count": clauses,
        "estimated_level": est_level,
    }


def detect_errors(text: str, level: str = "B1") -> list[dict]:
    """
    Heuristic error detection. Returns list of {name, hint, match, level}.
    Only flags patterns at or below the user's current level (no noise from advanced rules).
    """
    user_idx = _LEVEL_IDX.get(level.upper(), 2)
    errors = []
    for pat in _ERROR_PATTERNS:
        pat_idx = _LEVEL_IDX.get(pat["level"], 1)
        if pat_idx > user_idx:
            continue  # don't flag things above their level
        m = re.search(pat["pattern"], text, re.I | re.MULTILINE)
        if m:
            errors.append({
                "name": pat["name"],
                "hint": pat["hint"],
                "match": m.group(0),
                "level": pat["level"],
            })
    return errors


def correct_text(text: str, user_id: str = "default") -> dict:
    """
    Analyse a German text and return corrections + suggestions.
    Logs to correction_log; updates streak accordingly.
    """
    profile = get_profile(user_id)
    level = profile.get("level", "B1")
    errors = detect_errors(text, level)
    complexity = score_complexity(text)

    correct = len(errors) == 0
    level_changed = _adapt_level(profile, correct, user_id)

    # Build corrected text (apply hints, mark problem words)
    corrected = text
    marks = []
    for err in errors:
        marks.append(f"[{err['match']} → {err['hint']}]")

    result: dict[str, Any] = {
        "ok": True,
        "original": text,
        "errors": errors,
        "error_count": len(errors),
        "complexity": complexity,
        "level": level,
        "marks": marks,
        "level_changed": level_changed,
        "suggestion": _build_suggestion(text, errors, level),
    }

    # Persist to DB
    try:
        from layla.time_utils import utcnow
        with _db_ctx() as conn:
            conn.execute(
                "INSERT INTO correction_log (user_id, original, corrected, errors, level, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, text, corrected, json.dumps(errors), level, utcnow().isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.debug("german_mode.correct_text DB write failed: %s", e)

    return result


def _build_suggestion(text: str, errors: list[dict], level: str) -> str:
    if not errors:
        return "Gut gemacht! Keine offensichtlichen Fehler gefunden."
    parts = ["Mögliche Probleme:"]
    for e in errors[:3]:
        parts.append(f"• {e['hint']}")
    return "\n".join(parts)


def get_corrections_history(user_id: str = "default", limit: int = 20) -> list[dict]:
    """Return recent corrections for a user."""
    try:
        with _db_ctx() as conn:
            rows = conn.execute(
                "SELECT * FROM correction_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["errors"] = json.loads(d.get("errors") or "[]")
            except Exception:
                d["errors"] = []
            result.append(d)
        return result
    except Exception as e:
        logger.debug("german_mode.get_corrections_history failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Flashcard management (SM-2 spaced repetition)
# ---------------------------------------------------------------------------

def _sm2(ease_factor: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """
    SM-2 spaced repetition algorithm.
    quality: 0-5 (0-2 = fail, 3-5 = pass)
    Returns (new_ease_factor, new_interval, new_reps).
    """
    if quality < 3:
        return ease_factor, 1, 0  # reset

    new_ef = max(1.3, ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if reps == 0:
        new_interval = 1
    elif reps == 1:
        new_interval = 6
    else:
        new_interval = round(interval * ease_factor)
    return new_ef, new_interval, reps + 1


def add_flashcard(
    front: str,
    back: str,
    example: str = "",
    tags: str = "",
    user_id: str = "default",
) -> dict:
    """Add a new flashcard to the deck."""
    try:
        from layla.time_utils import utcnow
        now = utcnow().isoformat()
        with _db_ctx() as conn:
            cur = conn.execute(
                "INSERT INTO flashcards (user_id, front, back, example, tags, state, due_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id, front.strip(), back.strip(), example.strip(), tags.strip(), "new", now, now, now),
            )
            row_id = cur.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM flashcards WHERE id=?", (row_id,)).fetchone()
            return {"ok": True, "card": dict(row)}
    except Exception as e:
        logger.debug("german_mode.add_flashcard failed: %s", e)
        return {"ok": False, "error": str(e)}


def get_due_cards(user_id: str = "default", limit: int = 10) -> list[dict]:
    """Return flashcards due for review (due_at <= now), sorted by due_at."""
    try:
        from layla.time_utils import utcnow
        now = utcnow().isoformat()
        with _db_ctx() as conn:
            rows = conn.execute(
                "SELECT * FROM flashcards WHERE user_id=? AND state != 'mastered' AND due_at <= ? "
                "ORDER BY due_at ASC LIMIT ?",
                (user_id, now, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("german_mode.get_due_cards failed: %s", e)
        return []


def review_card(card_id: int, quality: int, user_id: str = "default") -> dict:
    """
    Record a review result for a flashcard.
    quality 0–5: 0-2=fail, 3=barely, 4=good, 5=perfect.
    """
    quality = max(0, min(5, quality))
    try:
        from datetime import datetime, timedelta, timezone

        from layla.time_utils import utcnow

        with _db_ctx() as conn:
            row = conn.execute(
                "SELECT * FROM flashcards WHERE id=? AND user_id=?", (card_id, user_id)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Card not found"}

            card = dict(row)
            new_ef, new_interval, new_reps = _sm2(
                card.get("ease_factor", 2.5),
                card.get("interval", 1),
                card.get("reps", 0),
                quality,
            )

            now_dt = utcnow()
            due_dt = now_dt + timedelta(days=new_interval)

            # Determine new state
            if quality < 3:
                new_state = "learning"
            elif new_reps >= 4 and new_interval >= 21:
                new_state = "mastered"
            elif new_reps >= 2:
                new_state = "review"
            else:
                new_state = "learning"

            conn.execute(
                "UPDATE flashcards SET state=?, ease_factor=?, interval=?, reps=?, due_at=?, updated_at=? "
                "WHERE id=?",
                (new_state, new_ef, new_interval, new_reps, due_dt.isoformat(), now_dt.isoformat(), card_id),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM flashcards WHERE id=?", (card_id,)).fetchone()
            return {"ok": True, "card": dict(updated), "next_review_days": new_interval}
    except Exception as e:
        logger.debug("german_mode.review_card failed: %s", e)
        return {"ok": False, "error": str(e)}


def delete_flashcard(card_id: int, user_id: str = "default") -> dict:
    try:
        with _db_ctx() as conn:
            conn.execute("DELETE FROM flashcards WHERE id=? AND user_id=?", (card_id, user_id))
            conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_flashcard_stats(user_id: str = "default") -> dict:
    """Return deck statistics for a user."""
    try:
        with _db_ctx() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) as cnt FROM flashcards WHERE user_id=? GROUP BY state",
                (user_id,),
            ).fetchall()
        counts = {r["state"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        return {
            "total": total,
            "new": counts.get("new", 0),
            "learning": counts.get("learning", 0),
            "review": counts.get("review", 0),
            "mastered": counts.get("mastered", 0),
        }
    except Exception as e:
        logger.debug("german_mode.get_flashcard_stats failed: %s", e)
        return {"total": 0, "new": 0, "learning": 0, "review": 0, "mastered": 0}


# ---------------------------------------------------------------------------
# Calibration quiz (generates example sentences at target level)
# ---------------------------------------------------------------------------

_CALIBRATION_SENTENCES: dict[str, list[str]] = {
    "A1": [
        "Ich heiße Maria.",
        "Das ist ein Buch.",
        "Er trinkt Wasser.",
    ],
    "A2": [
        "Gestern bin ich ins Kino gegangen.",
        "Sie hat eine kleine Katze.",
        "Wir essen jeden Tag zusammen.",
    ],
    "B1": [
        "Obwohl es regnet, gehe ich spazieren.",
        "Er hat mir erklärt, dass er keine Zeit hat.",
        "Ich würde gerne nach Deutschland reisen.",
    ],
    "B2": [
        "Hätte ich mehr Zeit gehabt, wäre ich öfter ins Theater gegangen.",
        "Die Entscheidung, die er getroffen hat, war nicht leicht zu verstehen.",
        "Angesichts der Umstände halte ich das für eine vernünftige Lösung.",
    ],
    "C1": [
        "Ungeachtet der wirtschaftlichen Schwierigkeiten gelang es dem Unternehmen, seinen Marktanteil zu halten.",
        "Die Frage, inwiefern kulturelle Identität durch Sprache geprägt wird, ist in der Linguistik umstritten.",
    ],
    "C2": [
        "Die Komplexität zwischenmenschlicher Beziehungen lässt sich schwerlich auf einfache Formeln reduzieren.",
    ],
}


def get_calibration_sentences(level: str = "B1") -> list[str]:
    """Return example sentences at the given CEFR level for calibration exercises."""
    level = level.upper()
    return _CALIBRATION_SENTENCES.get(level, _CALIBRATION_SENTENCES["B1"])


def calibrate_from_answers(answers: list[dict], user_id: str = "default") -> dict:
    """
    Run a simple calibration from answer ratings.
    Each answer: {level: "B1", score: 0-5}
    Returns recommended level.
    """
    if not answers:
        return {"ok": False, "error": "No answers provided"}

    weighted_scores: dict[str, list[float]] = {}
    for a in answers:
        lvl = str(a.get("level", "B1")).upper()
        sc = float(a.get("score", 3))
        weighted_scores.setdefault(lvl, []).append(sc)

    # Find highest level with avg score >= 3.5
    recommended = "A1"
    for lvl in CEFR_LEVELS:
        scores = weighted_scores.get(lvl, [])
        if scores and (sum(scores) / len(scores)) >= 3.5:
            recommended = lvl

    set_level(recommended, user_id)
    return {
        "ok": True,
        "recommended_level": recommended,
        "profile": get_profile(user_id),
    }


# ---------------------------------------------------------------------------
# System prompt injection helpers
# ---------------------------------------------------------------------------

_GERMAN_SYSTEM_BLOCK_TEMPLATE = """
## German Language Mode — CEFR {level}

Du bist Laylas Sprachlernmodus für Deutsch. Aktuelle Stufe: **{level}**.

Regeln:
1. Antworte **ausschließlich auf Deutsch** (außer bei explizitem Wechsel).
2. Passe dein Vokabular und deine Satzlänge an Stufe {level} an.
3. Wenn der Nutzer einen Fehler macht, korrigiere ihn **höflich** am Ende deiner Antwort mit dem Hinweis „🔎 Korrektur:".
4. Füge nach jeder Antwort bis zu 2 neue Vokabelvorschläge hinzu (Format: „📚 Vokabeln: Wort — Bedeutung").
5. Halte Erklärungen kurz und klar; vermeide linguistisches Fachjargon unter B2.

Stilbeispiele für {level}:
{examples}
""".strip()


def build_german_system_block(level: str = "B1") -> str:
    level = level.upper()
    examples = "\n".join(f"- {s}" for s in get_calibration_sentences(level)[:2])
    return _GERMAN_SYSTEM_BLOCK_TEMPLATE.format(level=level, examples=examples)

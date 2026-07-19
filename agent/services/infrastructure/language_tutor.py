"""Generalized multi-language tutor (BL-220).

Language-agnostic evolution of the German tutor (german_mode.py): learn ANY language, with
German + Italian + Spanish shipping now. The generalized engine is **LLM-based correction** — we
prompt the model as a `{language}` tutor at CEFR `{level}` and parse structured errors — so adding
a language is a single registry entry. Per-`(user, language)` level, language-tagged flashcard SRS,
and per-language calibration round out the loop. German additionally keeps its fast regex rules via
the legacy `/german/*` API; this module is the new language-parametrized `/language/*` surface.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
_LEVEL_IDX = {lvl: i for i, lvl in enumerate(CEFR_LEVELS)}

# The language registry. `has_rules` = a fast offline regex path exists (German only, via german_mode);
# every language works through the LLM path regardless. Add a language = add an entry here.
LANGUAGES: dict[str, dict[str, Any]] = {
    "german": {"name": "German", "native": "Deutsch", "flag": "🇩🇪", "has_rules": True},
    "italian": {"name": "Italian", "native": "Italiano", "flag": "🇮🇹", "has_rules": False},
    "spanish": {"name": "Spanish", "native": "Español", "flag": "🇪🇸", "has_rules": False},
    "french": {"name": "French", "native": "Français", "flag": "🇫🇷", "has_rules": False},
    "portuguese": {"name": "Portuguese", "native": "Português", "flag": "🇵🇹", "has_rules": False},
}


def list_languages() -> list[dict[str, Any]]:
    return [{"code": c, **v} for c, v in LANGUAGES.items()]


def normalize_language(language: str) -> str:
    lang = (language or "german").strip().lower()
    return lang if lang in LANGUAGES else "german"


def language_name(language: str) -> str:
    return LANGUAGES.get(normalize_language(language), {}).get("name", language.title())


# ── storage ──────────────────────────────────────────────────────────────────
def _db_path() -> Path:
    try:
        from layla.memory.db_connection import _resolve_db_path
        return _resolve_db_path().parent / "language_tutor.db"
    except Exception:
        from services.infrastructure.data_paths import layla_data_file
        return layla_data_file("language_tutor.db")


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        _migrate(conn)
        yield conn
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lang_profile (
            user_id TEXT NOT NULL, language TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'B1', streak_ok INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0, updated_at TEXT,
            PRIMARY KEY (user_id, language)
        );
        CREATE TABLE IF NOT EXISTS lang_card (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, language TEXT NOT NULL,
            front TEXT NOT NULL, back TEXT NOT NULL,
            ease REAL DEFAULT 2.5, interval_days REAL DEFAULT 0, reps INTEGER DEFAULT 0,
            due_at REAL DEFAULT 0, created_at REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_lang_card ON lang_card(user_id, language, due_at);
        """
    )
    conn.commit()


# ── profile / level ──────────────────────────────────────────────────────────
def get_profile(language: str, user_id: str = "default") -> dict[str, Any]:
    language = normalize_language(language)
    with _db() as conn:
        row = conn.execute("SELECT * FROM lang_profile WHERE user_id=? AND language=?", (user_id, language)).fetchone()
        if not row:
            conn.execute("INSERT INTO lang_profile (user_id, language, level, updated_at) VALUES (?,?,?,?)",
                         (user_id, language, "B1", _now_iso()))
            conn.commit()
            row = conn.execute("SELECT * FROM lang_profile WHERE user_id=? AND language=?", (user_id, language)).fetchone()
    d = dict(row)
    d["language_name"] = language_name(language)
    return d


def set_level(language: str, level: str, user_id: str = "default") -> dict[str, Any]:
    language = normalize_language(language)
    level = (level or "B1").upper()
    if level not in CEFR_LEVELS:
        return {"ok": False, "error": f"invalid CEFR level {level!r}"}
    with _db() as conn:
        conn.execute(
            "INSERT INTO lang_profile (user_id, language, level, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id, language) DO UPDATE SET level=excluded.level, updated_at=excluded.updated_at",
            (user_id, language, level, _now_iso()))
        conn.commit()
    return {"ok": True, "language": language, "level": level}


# ── correction (the generalized LLM engine) ──────────────────────────────────
_CORRECT_PROMPT = (
    "You are a patient {name} language tutor for a CEFR {level} learner. Correct the {name} text below.\n"
    "Reply with ONLY compact JSON (no prose): "
    '{{"corrected": "<the corrected text>", "errors": [{{"match": "<incorrect fragment>", "hint": "<the fix + a brief why>"}}]}}.\n'
    "If the text is already correct, use an empty errors array. Preserve the learner's meaning.\n\nText: {text}"
)


def _llm_complete(prompt: str) -> str:
    from services.llm.llm_gateway import run_completion
    r = run_completion(prompt, max_tokens=400, temperature=0.2)
    if isinstance(r, dict):
        return ((r.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
    return str(r or "")


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    # strip code fences + grab the first {...} block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def correct(text: str, language: str, user_id: str = "default", *, level: str | None = None) -> dict[str, Any]:
    """LLM-based correction for any language. Returns {ok, language, level, corrected, errors, correct}."""
    language = normalize_language(language)
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    lvl = (level or get_profile(language, user_id).get("level") or "B1").upper()
    try:
        raw = _llm_complete(_CORRECT_PROMPT.format(name=language_name(language), level=lvl, text=text))
    except Exception as e:
        return {"ok": False, "error": f"tutor model unavailable: {e}"}
    parsed = _extract_json(raw) or {}
    errors = parsed.get("errors") if isinstance(parsed.get("errors"), list) else []
    errors = [{"match": str(e.get("match", "")), "hint": str(e.get("hint", ""))} for e in errors if isinstance(e, dict)]
    corrected = str(parsed.get("corrected") or text)
    return {
        "ok": True,
        "language": language,
        "language_name": language_name(language),
        "level": lvl,
        "corrected": corrected,
        "errors": errors,
        "correct": len(errors) == 0,
    }


# ── flashcards (language-tagged SM-2 SRS) ────────────────────────────────────
def add_card(language: str, front: str, back: str, user_id: str = "default") -> dict[str, Any]:
    language = normalize_language(language)
    front, back = (front or "").strip(), (back or "").strip()
    if not front or not back:
        return {"ok": False, "error": "front and back required"}
    now = time.time()
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO lang_card (user_id, language, front, back, due_at, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, language, front[:500], back[:500], now, now))
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "language": language}


def due_cards(language: str, user_id: str = "default", limit: int = 20) -> dict[str, Any]:
    language = normalize_language(language)
    now = time.time()
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, front, back, reps FROM lang_card WHERE user_id=? AND language=? AND due_at<=? "
            "ORDER BY due_at ASC LIMIT ?", (user_id, language, now, limit)).fetchall()
    return {"ok": True, "language": language, "cards": [dict(r) for r in rows]}


def stats(language: str, user_id: str = "default") -> dict[str, Any]:
    language = normalize_language(language)
    now = time.time()
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM lang_card WHERE user_id=? AND language=?", (user_id, language)).fetchone()[0]
        due = conn.execute("SELECT COUNT(*) FROM lang_card WHERE user_id=? AND language=? AND due_at<=?", (user_id, language, now)).fetchone()[0]
    return {"ok": True, "language": language, "total": total, "due": due}


def review_card(card_id: int, quality: int, user_id: str = "default") -> dict[str, Any]:
    """Grade a card (quality 0-5) and reschedule via SM-2."""
    q = max(0, min(5, int(quality)))
    with _db() as conn:
        row = conn.execute("SELECT ease, interval_days, reps FROM lang_card WHERE id=? AND user_id=?", (card_id, user_id)).fetchone()
        if not row:
            return {"ok": False, "error": "card not found"}
        ease, interval, reps = float(row["ease"]), float(row["interval_days"]), int(row["reps"])
        if q < 3:
            reps, interval = 0, 1.0
        else:
            reps += 1
            interval = 1.0 if reps == 1 else (6.0 if reps == 2 else interval * ease)
            ease = max(1.3, ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
        due = time.time() + interval * 86400
        conn.execute("UPDATE lang_card SET ease=?, interval_days=?, reps=?, due_at=? WHERE id=? AND user_id=?",
                     (ease, interval, reps, due, card_id, user_id))
        conn.commit()
    return {"ok": True, "id": card_id, "interval_days": round(interval, 1), "reps": reps}


# ── calibration (per-language placement) ─────────────────────────────────────
_CALIBRATION: dict[str, dict[str, list[str]]] = {
    "german": {
        "A1": ["Ich heiße Maria.", "Das ist ein Buch.", "Er trinkt Wasser."],
        "A2": ["Gestern bin ich ins Kino gegangen.", "Ich möchte einen Kaffee bestellen."],
        "B1": ["Wenn ich mehr Zeit hätte, würde ich reisen.", "Der Film, den wir gesehen haben, war spannend."],
        "B2": ["Es wäre besser gewesen, wenn wir früher gegangen wären.", "Trotz des Regens fand die Veranstaltung statt."],
    },
    "italian": {
        "A1": ["Mi chiamo Marco.", "Questo è un libro.", "Lei beve acqua."],
        "A2": ["Ieri sono andato al cinema.", "Vorrei ordinare un caffè."],
        "B1": ["Se avessi più tempo, viaggerei di più.", "Il film che abbiamo visto era avvincente."],
        "B2": ["Sarebbe stato meglio se fossimo partiti prima.", "Nonostante la pioggia, l'evento si è svolto."],
    },
    "spanish": {
        "A1": ["Me llamo María.", "Esto es un libro.", "Él bebe agua."],
        "A2": ["Ayer fui al cine.", "Quisiera pedir un café."],
        "B1": ["Si tuviera más tiempo, viajaría más.", "La película que vimos era emocionante."],
        "B2": ["Habría sido mejor si hubiéramos salido antes.", "A pesar de la lluvia, el evento se celebró."],
    },
}


def calibration_sentences(language: str, level: str) -> list[str]:
    language = normalize_language(language)
    level = (level or "B1").upper()
    by_level = _CALIBRATION.get(language)
    if by_level and by_level.get(level):
        return by_level[level]
    if by_level:  # known language, missing level → nearest
        return by_level.get("B1") or next(iter(by_level.values()))
    # unknown language → generate a few via the LLM (best-effort)
    try:
        raw = _llm_complete(
            f"Give exactly 3 short example {language_name(language)} sentences at CEFR {level}, "
            'as a JSON array of strings only.')
        arr = json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group(0))
        return [str(s) for s in arr][:3] if isinstance(arr, list) else []
    except Exception:
        return []


def calibrate(language: str, answers: list[dict], user_id: str = "default") -> dict[str, Any]:
    """answers: [{level, score 0-5}]. Recommends the highest level the learner comfortably handles."""
    language = normalize_language(language)
    if not isinstance(answers, list) or not answers:
        return {"ok": False, "error": "answers required"}
    best = "A1"
    for a in answers:
        if not isinstance(a, dict):
            continue
        lvl = str(a.get("level", "")).upper()
        score = int(a.get("score", 0) or 0)
        if lvl in _LEVEL_IDX and score >= 3 and _LEVEL_IDX[lvl] >= _LEVEL_IDX[best]:
            best = lvl
    set_level(language, best, user_id)
    return {"ok": True, "language": language, "recommended_level": best}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

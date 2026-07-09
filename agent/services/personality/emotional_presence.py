"""Emotional presence (BL-190) — a light affective state that colors Layla's tone.

A companion feels *present* partly because her mood carries across a conversation instead
of resetting every turn. This keeps a small, decaying affect state — valence (warm↔cool)
and energy (lively↔subdued) — nudged by interaction signals (praise, corrections, task
success/failure, greetings) and surfaced as a subtle system-prompt hint. It never changes
*what* Layla can do or her core persona; it only tints *how* she says it. Flag-gated
(`emotional_presence_enabled`), decays toward neutral so no single moment sticks forever.
"""
from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# interaction signal → (valence delta, energy delta)
_SIGNALS = {
    "praise": (0.35, 0.15),
    "gratitude": (0.30, 0.05),
    "correction": (-0.20, 0.20),
    "success": (0.25, 0.10),
    "failure": (-0.25, 0.05),
    "greeting": (0.10, 0.20),
    "farewell": (0.05, -0.15),
    "frustration": (-0.30, 0.25),
}

_VAL_HALFLIFE_H = 6.0    # valence decays toward 0 (neutral) with this half-life
_ENERGY_REST = 0.5       # energy relaxes toward this baseline


def _data_dir() -> Path:
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"


def _db_path() -> Path:
    return _data_dir() / "mood.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mood (id INTEGER PRIMARY KEY CHECK (id=1), "
            "valence REAL, energy REAL, updated_at REAL)"
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _read_raw() -> tuple[float, float, float]:
    with _db() as conn:
        row = conn.execute("SELECT valence, energy, updated_at FROM mood WHERE id=1").fetchone()
    if not row:
        return 0.0, _ENERGY_REST, 0.0
    return float(row[0]), float(row[1]), float(row[2])


def _decayed(valence: float, energy: float, updated_at: float, now: float) -> tuple[float, float]:
    if updated_at <= 0:
        return valence, energy
    hours = max(0.0, (now - updated_at) / 3600.0)
    valence *= math.pow(0.5, hours / _VAL_HALFLIFE_H)
    # energy relaxes toward rest at the same pace
    k = math.pow(0.5, hours / _VAL_HALFLIFE_H)
    energy = _ENERGY_REST + (energy - _ENERGY_REST) * k
    return valence, energy


def _label(valence: float, energy: float) -> str:
    if abs(valence) < 0.12 and abs(energy - _ENERGY_REST) < 0.12:
        return "steady"
    if valence >= 0.12:
        return "warm and lively" if energy >= _ENERGY_REST else "content and calm"
    if valence <= -0.12:
        return "tense and alert" if energy >= _ENERGY_REST else "subdued"
    return "engaged" if energy >= _ENERGY_REST else "reflective"


def current_mood(*, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    v, e, ts = _read_raw()
    v, e = _decayed(v, e, ts, now)
    return {"valence": round(v, 3), "energy": round(e, 3), "label": _label(v, e)}


def nudge(valence_delta: float, energy_delta: float, *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    v, e, ts = _read_raw()
    v, e = _decayed(v, e, ts, now)
    v = _clamp(v + valence_delta, -1.0, 1.0)
    e = _clamp(e + energy_delta, 0.0, 1.0)
    with _db() as conn:
        conn.execute(
            "INSERT INTO mood (id, valence, energy, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET valence=excluded.valence, energy=excluded.energy, updated_at=excluded.updated_at",
            (v, e, now),
        )
    return {"valence": round(v, 3), "energy": round(e, 3), "label": _label(v, e)}


def register_signal(kind: str, *, now: float | None = None) -> dict[str, Any]:
    """Apply a named interaction signal (praise/correction/success/…)."""
    dv, de = _SIGNALS.get((kind or "").strip().lower(), (0.0, 0.0))
    return nudge(dv, de, now=now)


# High-precision user-sentiment cues, most-specific first. Kept tight on purpose: a false mood
# swing is worse than a missed one, so only clear signals fire. Anchored to word boundaries.
_FRUSTRATION_RE = re.compile(
    r"(ugh|wtf|come on|for fuck'?s sake|seriously\?|frustrat\w*|annoy\w*|stop doing that|"
    r"why (are|do) you keep)", re.IGNORECASE)
_CORRECTION_RE = re.compile(
    r"(^\s*no[,.]|that(?:'?s| is) (?:wrong|not right|not what)|not what i (?:asked|meant|wanted)|"
    r"you(?:'?re| are) wrong|did ?n'?t work|does ?n'?t work|is ?n'?t work|"
    r"still (?:broken|wrong|failing)|incorrect)", re.IGNORECASE)
_PRAISE_RE = re.compile(
    r"\b(thanks|thank you|thx|perfect|awesome|brilliant|exactly right|nailed it|love (it|this)|"
    r"well done|good (job|work|call)|that'?s (great|perfect|exactly (it|right)))\b", re.IGNORECASE)


def register_from_turn(
    user_message: str,
    *,
    outcome_success: bool | None = None,
    now: float | None = None,
) -> None:
    """Nudge mood from one completed turn: the user's sentiment + a failed task outcome.

    Deliberately does NOT reward every 'success' — most turns finish fine, so rewarding them
    would pin mood permanently warm. Mood only moves on notable events (the user reacted, or a
    task actually failed); it decays back to steady otherwise. Caller must gate on the flag.
    """
    msg = (user_message or "").strip()
    if msg:
        # most-specific wins; one sentiment signal per turn
        if _FRUSTRATION_RE.search(msg):
            register_signal("frustration", now=now)
        elif _CORRECTION_RE.search(msg):
            register_signal("correction", now=now)
        elif _PRAISE_RE.search(msg):
            register_signal("praise", now=now)
    if outcome_success is False:
        register_signal("failure", now=now)


def reset() -> None:
    with _db() as conn:
        conn.execute("DELETE FROM mood")


def mood_hint(*, now: float | None = None) -> str:
    """A subtle system-prompt line reflecting the current mood. '' when steady/neutral."""
    m = current_mood(now=now)
    if m["label"] == "steady":
        return ""
    return (f"Right now your mood is **{m['label']}** — let it lightly tint your tone "
            f"(word choice, warmth, pacing) without changing what you do or your core persona.")

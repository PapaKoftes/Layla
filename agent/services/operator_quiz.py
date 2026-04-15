"""Operator quiz + RPG-style stat profile (Fallout-like, Warframe flavored).

Stores results in SQLite via user_identity key/value pairs (see layla.memory.user_profile).
The goal is a clearly visible *seed* profile that evolves over time through maturity + learning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

StatId = Literal["technical", "creative", "analytical", "social", "patience", "ambition"]


STAT_IDS: tuple[StatId, ...] = ("technical", "creative", "analytical", "social", "patience", "ambition")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(float(v))
    except Exception:
        return default
    return max(lo, min(hi, iv))


@dataclass(frozen=True)
class QuizOption:
    id: str
    label: str
    deltas: Dict[StatId, int]
    prefs: Dict[str, str] | None = None


@dataclass(frozen=True)
class QuizQuestion:
    id: str
    stage: int
    prompt: str
    options: List[QuizOption]


def _q(
    *,
    qid: str,
    stage: int,
    prompt: str,
    options: List[QuizOption],
) -> QuizQuestion:
    return QuizQuestion(id=qid, stage=stage, prompt=prompt, options=options)


QUESTIONS: List[QuizQuestion] = [
    # Stage 0 — work instinct
    _q(
        qid="bug_2am",
        stage=0,
        prompt="It’s 2am. Production is failing. You wake up to alerts.",
        options=[
            QuizOption(
                id="fix_now",
                label="Fix it immediately. Sleep later.",
                deltas={"technical": 2, "ambition": 2, "patience": -1, "analytical": 1, "creative": 0, "social": -1},
                prefs={"communication_style": "direct"},
            ),
            QuizOption(
                id="triage_document",
                label="Triage, document the failure, make a plan. Then act.",
                deltas={"analytical": 2, "patience": 2, "technical": 1, "social": 0, "creative": 0, "ambition": 0},
                prefs={"communication_style": "structured"},
            ),
            QuizOption(
                id="automate_alerts",
                label="Stabilize the alerts first so future-you suffers less.",
                deltas={"analytical": 1, "patience": 1, "technical": 1, "creative": 1, "ambition": 0, "social": 0},
                prefs={"work_domains": "devops"},
            ),
            QuizOption(
                id="call_team",
                label="Wake the team. You don’t want heroics; you want reliability.",
                deltas={"social": 2, "analytical": 1, "patience": 1, "technical": 0, "creative": 0, "ambition": 0},
                prefs={"communication_style": "collaborative"},
            ),
        ],
    ),
    _q(
        qid="new_framework",
        stage=1,
        prompt="A new framework drops. Everyone is hyped. You…",
        options=[
            QuizOption(
                id="ignore_until_proven",
                label="Ignore it until it has battle scars and docs.",
                deltas={"analytical": 2, "patience": 1, "technical": 1, "creative": -1, "ambition": 0, "social": 0},
                prefs={"risk_tolerance": "low"},
            ),
            QuizOption(
                id="try_small_project",
                label="Try it on a tiny side project. Learn by doing.",
                deltas={"creative": 1, "technical": 1, "ambition": 1, "analytical": 0, "patience": 0, "social": 0},
                prefs={"risk_tolerance": "medium"},
            ),
            QuizOption(
                id="deep_dive",
                label="Read the source, the RFC, and the benchmarks first.",
                deltas={"analytical": 2, "technical": 2, "patience": 1, "creative": 0, "ambition": 0, "social": -1},
                prefs={"learning_style": "depth_first"},
            ),
            QuizOption(
                id="teach_team",
                label="Try it, then teach it. Knowledge sticks when shared.",
                deltas={"social": 2, "technical": 1, "creative": 1, "ambition": 1, "analytical": 0, "patience": 0},
                prefs={"learning_style": "teach_back"},
            ),
        ],
    ),
    _q(
        qid="bad_pr",
        stage=2,
        prompt="A teammate opens a messy PR. It works, but it’s ugly.",
        options=[
            QuizOption(
                id="rewrite",
                label="Rewrite it cleanly and ask them to learn from it.",
                deltas={"technical": 2, "ambition": 1, "patience": -1, "social": -1, "analytical": 1, "creative": 0},
                prefs={"feedback_style": "direct"},
            ),
            QuizOption(
                id="review_teach",
                label="Leave a careful review with examples. Make them stronger.",
                deltas={"social": 2, "patience": 2, "technical": 1, "analytical": 1, "creative": 0, "ambition": 0},
                prefs={"feedback_style": "coaching"},
            ),
            QuizOption(
                id="accept_and_log_debt",
                label="Merge it and log debt. The system must move.",
                deltas={"analytical": 1, "ambition": 1, "technical": 0, "patience": 0, "social": 0, "creative": 0},
                prefs={"planning_bias": "ship_first"},
            ),
            QuizOption(
                id="pair_program",
                label="Pair program. Fix it together.",
                deltas={"social": 2, "technical": 1, "patience": 1, "creative": 0, "analytical": 0, "ambition": 0},
                prefs={"collaboration_mode": "pairing"},
            ),
        ],
    ),
    _q(
        qid="free_weekend",
        stage=3,
        prompt="You have a free weekend and no obligations. You choose…",
        options=[
            QuizOption(
                id="build_tool",
                label="Build a tool that makes your life easier forever.",
                deltas={"technical": 2, "analytical": 1, "ambition": 1, "creative": 0, "patience": 0, "social": 0},
                prefs={"goals_summary": "Build leverage: tools, automation, systems."},
            ),
            QuizOption(
                id="learn_deeply",
                label="Study something hard. Depth is power.",
                deltas={"analytical": 2, "patience": 2, "technical": 1, "creative": 0, "social": 0, "ambition": 0},
                prefs={"goals_summary": "Develop mastery through deep study."},
            ),
            QuizOption(
                id="create_world",
                label="Create something with style: story, art, or a weird project.",
                deltas={"creative": 2, "ambition": 1, "social": 0, "technical": 0, "analytical": 0, "patience": 0},
                prefs={"goals_summary": "Build meaning and expression through creation."},
            ),
            QuizOption(
                id="connect",
                label="Spend it with people. Relationships are the real game.",
                deltas={"social": 2, "patience": 1, "creative": 0, "technical": 0, "analytical": 0, "ambition": 0},
                prefs={"goals_summary": "Strengthen relationships and shared projects."},
            ),
        ],
    ),
    # Stage 4 — collaboration and communication
    _q(
        qid="status_update",
        stage=4,
        prompt="You need to post a status update on a project. You prefer…",
        options=[
            QuizOption(
                id="bullets_and_actions",
                label="Bullets with clear next actions and owners.",
                deltas={"analytical": 2, "patience": 1, "social": 1, "technical": 0, "creative": 0, "ambition": 0},
                prefs={"status_update_style": "actions_first"},
            ),
            QuizOption(
                id="narrative",
                label="A short narrative: context, progress, blockers, ask.",
                deltas={"social": 2, "analytical": 1, "patience": 0, "technical": 0, "creative": 1, "ambition": 0},
                prefs={"status_update_style": "narrative"},
            ),
            QuizOption(
                id="minimal",
                label="Minimal: what changed and what’s next. No fluff.",
                deltas={"technical": 1, "analytical": 1, "patience": 0, "social": 0, "creative": 0, "ambition": 1},
                prefs={"status_update_style": "minimal"},
            ),
            QuizOption(
                id="sync_call",
                label="I’d rather do a quick sync call than write updates.",
                deltas={"social": 2, "patience": 0, "analytical": 0, "technical": 0, "creative": 0, "ambition": 0},
                prefs={"status_update_style": "sync_call"},
            ),
        ],
    ),
    # Stage 5 — risk tolerance in execution
    _q(
        qid="risky_change",
        stage=5,
        prompt="A change could improve things a lot, but has real risk. You…",
        options=[
            QuizOption(
                id="feature_flag",
                label="Ship behind a feature flag with an easy rollback.",
                deltas={"analytical": 2, "technical": 1, "patience": 1, "social": 0, "creative": 0, "ambition": 0},
                prefs={"risk_execution": "flagged_rollout"},
            ),
            QuizOption(
                id="prototype_first",
                label="Prototype in a sandbox and measure before shipping.",
                deltas={"analytical": 2, "creative": 1, "patience": 1, "technical": 0, "social": 0, "ambition": 0},
                prefs={"risk_execution": "prototype_measure"},
            ),
            QuizOption(
                id="go_for_it",
                label="Go for it. We learn fastest under real pressure.",
                deltas={"ambition": 2, "technical": 1, "creative": 1, "analytical": -1, "patience": -1, "social": 0},
                prefs={"risk_execution": "bold"},
            ),
            QuizOption(
                id="avoid",
                label="Avoid. Stability beats novelty unless proven necessary.",
                deltas={"patience": 2, "analytical": 1, "technical": 0, "creative": -1, "ambition": -1, "social": 0},
                prefs={"risk_execution": "conservative"},
            ),
        ],
    ),
    # Stage 6 — learning preference under time pressure
    _q(
        qid="learning_mode",
        stage=6,
        prompt="When learning something new, you get traction fastest by…",
        options=[
            QuizOption(
                id="read_docs",
                label="Reading docs and building a clean mental model first.",
                deltas={"analytical": 2, "patience": 1, "technical": 1, "creative": 0, "social": 0, "ambition": 0},
                prefs={"learning_mode": "docs_first"},
            ),
            QuizOption(
                id="ship_small",
                label="Shipping a tiny working version, then iterating.",
                deltas={"technical": 1, "ambition": 1, "creative": 1, "analytical": 0, "patience": 0, "social": 0},
                prefs={"learning_mode": "iterate"},
            ),
            QuizOption(
                id="examples",
                label="Studying examples and patterns, then adapting them.",
                deltas={"analytical": 1, "technical": 1, "patience": 0, "creative": 0, "social": 0, "ambition": 0},
                prefs={"learning_mode": "examples"},
            ),
            QuizOption(
                id="pair",
                label="Pairing with someone (or an assistant) and asking questions.",
                deltas={"social": 2, "patience": 1, "analytical": 0, "technical": 0, "creative": 0, "ambition": 0},
                prefs={"learning_mode": "pairing"},
            ),
        ],
    ),
    # Stage 7 — stuckness response
    _q(
        qid="when_stuck",
        stage=7,
        prompt="When you’re stuck on a hard problem, your default move is…",
        options=[
            QuizOption(
                id="reduce_scope",
                label="Reduce scope to the smallest failing case and debug from there.",
                deltas={"analytical": 2, "technical": 1, "patience": 1, "creative": 0, "social": 0, "ambition": 0},
                prefs={"debug_style": "min_repro"},
            ),
            QuizOption(
                id="take_break",
                label="Step away briefly. Clarity comes when pressure drops.",
                deltas={"patience": 2, "analytical": 0, "technical": 0, "creative": 1, "social": 0, "ambition": 0},
                prefs={"debug_style": "break_then_return"},
            ),
            QuizOption(
                id="ask_for_help",
                label="Ask for help early. Time matters more than ego.",
                deltas={"social": 2, "patience": 1, "analytical": 0, "technical": 0, "creative": 0, "ambition": 0},
                prefs={"debug_style": "ask_early"},
            ),
            QuizOption(
                id="brute_force",
                label="Brute force variations until the pattern reveals itself.",
                deltas={"technical": 1, "creative": 1, "analytical": 0, "patience": -1, "social": 0, "ambition": 1},
                prefs={"debug_style": "brute_force"},
            ),
        ],
    ),
    # Stage 8 — output preferences for an assistant
    _q(
        qid="assistant_style",
        stage=8,
        prompt="When an assistant responds, you value most…",
        options=[
            QuizOption(
                id="concise",
                label="Concise, high-signal answers. Minimal fluff.",
                deltas={"analytical": 1, "technical": 1, "patience": 0, "creative": 0, "social": 0, "ambition": 0},
                prefs={"assistant_style": "concise"},
            ),
            QuizOption(
                id="thorough",
                label="Thorough explanations with trade-offs and references.",
                deltas={"analytical": 2, "patience": 1, "technical": 0, "creative": 0, "social": 0, "ambition": 0},
                prefs={"assistant_style": "thorough"},
            ),
            QuizOption(
                id="actionable",
                label="Actionable steps and checklists I can follow.",
                deltas={"analytical": 1, "patience": 1, "technical": 0, "creative": 0, "social": 0, "ambition": 1},
                prefs={"assistant_style": "actionable"},
            ),
            QuizOption(
                id="playful",
                label="A bit of style and personality, as long as it stays useful.",
                deltas={"creative": 2, "social": 1, "analytical": 0, "technical": 0, "patience": 0, "ambition": 0},
                prefs={"assistant_style": "playful"},
            ),
        ],
    ),
]


def list_stages() -> list[int]:
    return sorted({q.stage for q in QUESTIONS})


def get_stage(stage_idx: int) -> dict[str, Any]:
    idx = _clamp_int(stage_idx, 0, 99, 0)
    qs = [q for q in QUESTIONS if q.stage == idx]
    if not qs:
        return {"ok": False, "error": "unknown_stage", "stage": idx, "known_stages": list_stages()}
    return {
        "ok": True,
        "stage": idx,
        "questions": [
            {
                "id": q.id,
                "prompt": q.prompt,
                "options": [{"id": o.id, "label": o.label} for o in q.options],
            }
            for q in qs
        ],
    }


def _initial_stats(seed: Optional[dict[str, Any]] = None) -> Dict[StatId, int]:
    # Start at 5 across the board as a visible seed; quiz shifts around it.
    base: Dict[StatId, int] = {sid: 5 for sid in STAT_IDS}
    if seed:
        for sid in STAT_IDS:
            key = f"stat_{sid}"
            if key in seed:
                base[sid] = _clamp_int(seed.get(key), 1, 10, base[sid])
    return base


def score_answers(
    answers: list[dict[str, Any]],
    *,
    seed_identity: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (profile_preview, identity_kv_updates). Does not persist."""
    stats = _initial_stats(seed_identity)
    prefs: dict[str, str] = {}

    q_by_id = {q.id: q for q in QUESTIONS}
    for a in answers or []:
        qid = str((a or {}).get("question_id") or (a or {}).get("qid") or "").strip()
        oid = str((a or {}).get("option_id") or (a or {}).get("oid") or "").strip()
        if not qid or not oid:
            continue
        q = q_by_id.get(qid)
        if not q:
            continue
        opt = next((o for o in q.options if o.id == oid), None)
        if not opt:
            continue
        for sid, dv in (opt.deltas or {}).items():
            try:
                stats[sid] = _clamp_int(stats[sid] + int(dv), 1, 10, stats[sid])
            except Exception:
                pass
        if opt.prefs:
            prefs.update({str(k): str(v) for k, v in opt.prefs.items() if k})

    # Identity KV updates to store
    kv: dict[str, str] = {}
    for sid, v in stats.items():
        kv[f"stat_{sid}"] = str(_clamp_int(v, 1, 10, 5))
    for k, v in prefs.items():
        # allow small JSON payloads as strings
        kv[str(k)] = str(v)[:4000]

    # Defaults for maturity seed (only set if missing by caller)
    kv.setdefault("maturity_xp", "0")
    kv.setdefault("maturity_rank", "0")
    kv.setdefault("maturity_phase", "nascent")
    kv.setdefault("quiz_completed_at", _utcnow_iso())

    preview = {
        "stats": stats,
        "prefs": prefs,
        "known_stats": list(STAT_IDS),
    }
    return preview, kv


def save_identity_kv(kv: dict[str, str]) -> None:
    from layla.memory.db import set_user_identity

    for k, v in (kv or {}).items():
        kk = str(k or "").strip()
        if not kk:
            continue
        set_user_identity(kk, str(v or ""))


def load_profile() -> dict[str, Any]:
    """Return a structured profile view from user_identity."""
    from layla.memory.db import get_all_user_identity

    uid = get_all_user_identity() or {}
    stats: dict[str, int] = {}
    for sid in STAT_IDS:
        stats[sid] = _clamp_int(uid.get(f"stat_{sid}"), 1, 10, 5)

    maturity = {
        "xp": _clamp_int(uid.get("maturity_xp"), 0, 2_000_000_000, 0),
        "rank": _clamp_int(uid.get("maturity_rank"), 0, 10_000, 0),
        "phase": (uid.get("maturity_phase") or "nascent").strip().lower() or "nascent",
    }

    # Work domains may be a JSON list, a string token, or missing.
    work_domains: list[str] = []
    raw_domains = (uid.get("work_domains") or "").strip()
    if raw_domains:
        try:
            parsed = json.loads(raw_domains)
            if isinstance(parsed, list):
                work_domains = [str(x) for x in parsed if str(x).strip()]
            else:
                work_domains = [str(parsed)]
        except Exception:
            work_domains = [raw_domains]

    prefs = {k: v for k, v in uid.items() if k and not k.startswith("stat_") and k not in {"maturity_xp", "maturity_rank", "maturity_phase"}}
    return {
        "ok": True,
        "stats": stats,
        "maturity": maturity,
        "work_domains": work_domains,
        "prefs": prefs,
        "raw": uid,
    }


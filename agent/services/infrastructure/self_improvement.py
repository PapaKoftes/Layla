from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("layla")


_ALLOWED_CONFIG_KEYS: set[str] = {
    # UX / output shaping
    "output_quality_gate_enabled",
    # Core behavior shaping
    "inline_initiative_enabled",
    "observation_mode_enabled",
    "capability_level_inject_enabled",
    "maturity_enabled",
}


def _parse_instructions(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _apply_config_keys(config_keys: dict[str, Any]) -> dict[str, Any]:
    """
    Apply allowlisted config keys into runtime_config.json.
    This is only called after operator approval.
    """
    clean: dict[str, Any] = {}
    unknown: list[str] = []
    for k, v in (config_keys or {}).items():
        kk = str(k).strip()
        if not kk:
            continue
        if kk not in _ALLOWED_CONFIG_KEYS:
            unknown.append(kk)
            continue
        clean[kk] = v
    if unknown:
        return {"ok": False, "error": "unknown_config_keys", "unknown": sorted(set(unknown))}
    if not clean:
        return {"ok": True, "applied": {}, "changed": False}

    try:
        from runtime_safety import CONFIG_FILE, atomic_write_config

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        changed = False
        for k, v in clean.items():
            if data.get(k) != v:
                data[k] = v
                changed = True

        if changed:
            atomic_write_config(data)
        return {"ok": True, "applied": clean, "changed": changed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def apply_approved_proposals(ids: list[int]) -> dict[str, Any]:
    """
    Apply the instructions payload of already-approved proposals.
    Currently supports: {"config_keys": {...}} with a strict allowlist.
    """
    from layla.memory.db import get_improvements_by_ids, set_improvement_status

    rows = get_improvements_by_ids(ids)
    applied: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for r in rows:
        try:
            pid = int(r.get("id") or 0)
        except Exception:
            pid = 0
        if pid <= 0:
            continue
        st = str(r.get("status") or "").strip().lower()
        if st != "approved":
            continue

        instr = _parse_instructions(r.get("instructions"))
        if not instr:
            continue
        if "config_keys" in instr and isinstance(instr.get("config_keys"), dict):
            res = _apply_config_keys(instr.get("config_keys") or {})
            if res.get("ok"):
                applied.append(
                    {
                        "id": pid,
                        "type": "config_keys",
                        "changed": bool(res.get("changed")),
                        "keys": sorted(list((res.get("applied") or {}).keys())),
                    }
                )
                set_improvement_status([pid], "applied")
            else:
                errors.append(
                    {
                        "id": pid,
                        "error": res.get("error") or "apply_failed",
                        "details": {k: v for k, v in res.items() if k not in ("ok",)},
                    }
                )

    return {"ok": True, "applied": applied, "errors": errors}


# ── Behavioral self-analysis ─────────────────────────────────────────────────
# Instead of emitting fixed advice, we MINE the telemetry the system already records
# and name a specific tool/effect/pattern with the numbers behind it. Every miner
# degrades to [] when its source is empty or unavailable — a fresh install produces
# an honest "not enough data yet", never fabricated proposals.


def _tool_call_window_iso(days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(tz=timezone.utc) - timedelta(days=max(1, days))).isoformat()


def _mine_tool_failures(days: int = 30) -> list[dict[str, Any]]:
    """Per-tool failure counts from the tool_calls trace (routers/tools_history reads the same table).

    A tool that keeps failing is the single most actionable, evidence-backed signal: it names a
    concrete subject (the tool), a count/rate, and the dominant error code.
    """
    out: list[dict[str, Any]] = []
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        cutoff = _tool_call_window_iso(days)
        with _conn() as db:
            agg = db.execute(
                "SELECT tool_name, COUNT(*) AS calls, SUM(result_ok) AS successes "
                "FROM tool_calls WHERE created_at >= ? GROUP BY tool_name",
                (cutoff,),
            ).fetchall()
            err = db.execute(
                "SELECT tool_name, error_code, COUNT(*) AS cnt FROM tool_calls "
                "WHERE created_at >= ? AND result_ok=0 AND error_code IS NOT NULL AND error_code != '' "
                "GROUP BY tool_name, error_code ORDER BY cnt DESC",
                (cutoff,),
            ).fetchall()
    except Exception as e:  # noqa: BLE001 — a missing table / cold DB is "no signal", not an error
        logger.debug("tool-failure mining skipped: %s", e)
        return out

    top_err: dict[str, tuple[str, int]] = {}
    for r in err:
        tn = r["tool_name"]
        if tn not in top_err:  # rows are pre-sorted by count desc, so first seen is the top error
            top_err[tn] = (r["error_code"], int(r["cnt"] or 0))

    for r in agg:
        tool = str(r["tool_name"] or "").strip()
        calls = int(r["calls"] or 0)
        succ = int(r["successes"] or 0)
        fails = max(0, calls - succ)
        if not tool or calls <= 0 or fails <= 0:
            continue
        rate = round(fails / calls, 3)
        # Precision gate: a sustained problem, not a single blip.
        if not (fails >= 3 or (calls >= 4 and rate >= 0.5)):
            continue
        code, code_n = top_err.get(tool, ("", 0))
        evidence = {
            "calls": calls,
            "failures": fails,
            "failure_rate": rate,
            "window_days": days,
            "top_error": code or None,
            "top_error_count": code_n,
        }
        err_phrase = f"most common error '{code}' ({code_n}x). " if code else ""
        action = (
            f"Investigate tool '{tool}': {err_phrase}"
            "add input validation or a guard before dispatch, or wire a fallback tool."
        )
        out.append(
            {
                "signal": "tool_failure",
                "subject": tool,
                "title": f"Tool '{tool}' is failing: {fails}/{calls} calls failed ({int(rate * 100)}%)",
                "evidence": evidence,
                "action": action,
                "risk_level": "medium" if rate >= 0.5 else "low",
                "domain": "tools",
                "severity": fails * 10 + int(rate * 10),
            }
        )
    return out


def _mine_liveness() -> list[dict[str, Any]]:
    """Known load-bearing effects stuck at 0 — but ONLY when the system is otherwise active.

    A zero count on a fresh install is meaningless (nothing has happened yet). It becomes a real
    finding only when SOME effect has fired (the registry is live and being written) while a
    specific effect never has — the codebase's signature "correct component, nobody drives it" bug.
    """
    out: list[dict[str, Any]] = []
    try:
        from services.observability.liveness import snapshot

        snap = snapshot()
    except Exception as e:  # noqa: BLE001
        logger.debug("liveness mining skipped: %s", e)
        return out
    if not isinstance(snap, dict) or not snap:
        return out

    active = sorted(name for name, rec in snap.items() if isinstance(rec, dict) and int(rec.get("count") or 0) > 0)
    if not active:
        return out  # nothing has ever fired → fresh/idle install, not a defect

    for name, rec in snap.items():
        if not isinstance(rec, dict) or not rec.get("known"):
            continue
        if int(rec.get("count") or 0) > 0:
            continue
        desc = str(rec.get("description") or "")
        if "Expected 0" in desc:  # documented as legitimately-zero until a later feature lands
            continue
        evidence = {
            "count": 0,
            "last_fired_at": rec.get("last_fired_at"),
            "baseline_active_effects": active,
            "baseline_active_count": len(active),
        }
        action = (
            f"Verify the code path that should call liveness.fire('{name}'). "
            f"{desc[:180]}".strip()
        )
        out.append(
            {
                "signal": "liveness_zero",
                "subject": name,
                "title": f"Load-bearing effect '{name}' has never fired while {len(active)} other effect(s) have",
                "evidence": evidence,
                "action": action,
                "risk_level": "medium",
                "domain": "observability",
                "severity": 60,
            }
        )
    return out


def _mine_outcome_evaluations(limit: int = 200) -> list[dict[str, Any]]:
    """Recurring failure reasons across persisted per-turn outcome evaluations."""
    import collections

    out: list[dict[str, Any]] = []
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        with _conn() as db:
            rows = db.execute(
                "SELECT evaluation_json FROM outcome_evaluations ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.debug("outcome-evaluation mining skipped: %s", e)
        return out

    reasons: collections.Counter = collections.Counter()
    reason_improve: dict[str, str] = {}
    scores: list[float] = []
    total = 0
    for r in rows:
        try:
            ev = json.loads(r["evaluation_json"])
        except Exception:
            continue
        if not isinstance(ev, dict):
            continue
        total += 1
        try:
            scores.append(float(ev.get("score")))
        except (TypeError, ValueError):
            pass
        reason = str(ev.get("reason") or "").strip().lower()
        if not reason:
            if int(ev.get("tool_fail") or 0) > 0:
                reason = "tool_failed"
            elif ev.get("success") is True:
                reason = "ok"
            else:
                reason = "incomplete"
        if reason in ("ok", ""):
            continue
        reasons[reason] += 1
        if reason not in reason_improve and ev.get("improvement"):
            reason_improve[reason] = str(ev.get("improvement"))[:300]

    if total < 3 or not reasons:
        return out
    mean_score = round(sum(scores) / len(scores), 3) if scores else None
    reason, count = reasons.most_common(1)[0]
    if count < 3:
        return out
    action = reason_improve.get(reason) or (
        f"Review the recurring '{reason}' failures and add a guard or verification step to prevent them."
    )
    out.append(
        {
            "signal": "outcome_pattern",
            "subject": f"outcome:{reason}",
            "title": f"{count} of {total} recent turns failed with reason '{reason}'",
            "evidence": {
                "reason": reason,
                "count": count,
                "total_evaluated": total,
                "mean_score": mean_score,
            },
            "action": action,
            "risk_level": "low",
            "domain": "quality",
            "severity": count * 3,
        }
    )
    return out


def _mine_reflections(limit: int = 200) -> list[dict[str, Any]]:
    """Recurring 'what could improve' lines from the reflection engine (stored as learnings)."""
    import collections

    out: list[dict[str, Any]] = []
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        with _conn() as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(learnings)").fetchall()}
            if "source" not in cols:
                return out
            rows = db.execute(
                "SELECT content FROM learnings WHERE source='reflection_engine' "
                "ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.debug("reflection mining skipped: %s", e)
        return out

    improves: collections.Counter = collections.Counter()
    for r in rows:
        content = str(r["content"] or "")
        # Content shape: "Reflection (obj): Worked: … | Failed: … | Improve: …"
        for part in content.split("|"):
            p = part.strip()
            low = p.lower()
            if low.startswith("improve:"):
                phrase = p.split(":", 1)[-1].strip().lower()
                if phrase and phrase not in ("n/a", "none"):
                    improves[phrase[:120]] += 1
    if not improves:
        return out
    phrase, count = improves.most_common(1)[0]
    if count < 2:
        return out
    out.append(
        {
            "signal": "reflection_pattern",
            "subject": f"reflection:{phrase[:40]}",
            "title": f"Reflections repeatedly recommend: '{phrase[:80]}'",
            "evidence": {"occurrences": count, "phrase": phrase},
            "action": f"Act on the recurring reflection: {phrase}.",
            "risk_level": "low",
            "domain": "quality",
            "severity": count * 2,
        }
    )
    return out


def _mine_recent_failures(recent_failures: list[str] | None) -> list[dict[str, Any]]:
    """Caller-supplied recent failures (passed through the /improvements/generate API)."""
    fails = [str(f).strip() for f in (recent_failures or []) if str(f).strip()]
    if not fails:
        return []
    return [
        {
            "signal": "recent_failures",
            "subject": "recent_failures",
            "title": f"Add regression coverage for {len(fails)} recent failure(s)",
            "evidence": {"count": len(fails), "sample": fails[:3]},
            "action": "Add one regression test per failure class so these breakages cannot recur.",
            "risk_level": "low",
            "domain": "tests",
            "severity": min(len(fails), 10) * 2,
            "extra_instructions": {"recent_failures": fails[:10]},
        }
    ]


def generate_proposals(
    session_summary: str = "",
    capability_levels: dict[str, Any] | None = None,
    recent_failures: list[str] | None = None,
) -> dict[str, Any]:
    """Evidence-backed self-improvement proposals mined from Layla's own telemetry.

    Signals mined (each degrades to nothing when its source is empty):
      - tool_calls trace           → specific tools that keep failing (count + rate + top error)
      - liveness registry snapshot → load-bearing effects stuck at 0 while others fire
      - outcome_evaluations        → recurring per-turn failure reasons
      - reflection-engine learnings→ recurring "what could improve" lines
      - caller-supplied failures   → regression-coverage proposal (API passthrough)

    Every proposal carries a title, a specific subject (tool/effect/pattern), the evidence
    (numbers), and a concrete suggested action. When no signal exists (fresh install) the
    result is an honest "not enough data yet" — never a fabricated proposal.
    """
    proposals: list[dict[str, Any]] = []
    proposals.extend(_mine_tool_failures())
    proposals.extend(_mine_liveness())
    proposals.extend(_mine_outcome_evaluations())
    proposals.extend(_mine_reflections())
    proposals.extend(_mine_recent_failures(recent_failures))

    signals = {
        "tool_failure": sum(1 for p in proposals if p["signal"] == "tool_failure"),
        "liveness_zero": sum(1 for p in proposals if p["signal"] == "liveness_zero"),
        "outcome_pattern": sum(1 for p in proposals if p["signal"] == "outcome_pattern"),
        "reflection_pattern": sum(1 for p in proposals if p["signal"] == "reflection_pattern"),
        "recent_failures": sum(1 for p in proposals if p["signal"] == "recent_failures"),
    }

    if not proposals:
        return {
            "ok": True,
            "created": [],
            "count_created": 0,
            "reason": "not_enough_data",
            "message": (
                "No behavioral telemetry to analyse yet. Proposals appear once tools run, turns are "
                "evaluated, load-bearing effects register, or the reflection engine records critiques."
            ),
            "signals": signals,
        }

    # Highest-evidence proposals survive the cap; dedup by (signal, subject).
    proposals.sort(key=lambda p: int(p.get("severity") or 0), reverse=True)
    seen: set[tuple[str, str]] = set()

    from layla.memory.db import create_improvement

    created: list[dict[str, Any]] = []
    for p in proposals:
        key = (p["signal"], p["subject"])
        if key in seen:
            continue
        seen.add(key)

        instructions: dict[str, Any] = {
            "signal": p["signal"],
            "subject": p["subject"],
            "evidence": p["evidence"],
            "action": p["action"],
        }
        if isinstance(p.get("extra_instructions"), dict):
            instructions.update(p["extra_instructions"])

        # The stored rationale is human-readable: action first, then the raw evidence.
        rationale = f"{p['action']} Evidence: {json.dumps(p['evidence'], ensure_ascii=False)}"

        r = create_improvement(
            p["title"],
            rationale=rationale,
            risk_level=p.get("risk_level", "low"),
            domain=p.get("domain", ""),
            instructions=instructions,
        )
        if r.get("ok") and r.get("proposal"):
            row = dict(r["proposal"])
            row.update(
                {
                    "signal": p["signal"],
                    "subject": p["subject"],
                    "evidence": p["evidence"],
                    "action": p["action"],
                }
            )
            created.append(row)
        if len(created) >= 6:
            break

    return {
        "ok": True,
        "created": created,
        "count_created": len(created),
        "signals": signals,
    }


def list_proposals(status: str = "", limit: int = 50) -> dict[str, Any]:
    from layla.memory.db import list_improvements

    return {"ok": True, "proposals": list_improvements(status=status, limit=limit)}


def approve_batch(ids: list[int]) -> dict[str, Any]:
    from layla.memory.db import set_improvement_status

    base = set_improvement_status(ids, "approved")
    try:
        if not base.get("ok"):
            return base
    except Exception:
        return base

    applied = {"ok": True, "applied": [], "errors": []}
    try:
        applied = apply_approved_proposals(ids)
    except Exception as e:
        logger.debug("apply_approved_proposals failed: %s", e)
        applied = {"ok": False, "error": str(e), "applied": [], "errors": [{"error": str(e)}]}

    out = dict(base)
    out["applied"] = applied.get("applied") or []
    out["apply_errors"] = applied.get("errors") or (
        [] if applied.get("ok") else [{"error": applied.get("error") or "apply_failed"}]
    )
    return out


def reject(ids: list[int]) -> dict[str, Any]:
    from layla.memory.db import set_improvement_status

    return set_improvement_status(ids, "rejected")


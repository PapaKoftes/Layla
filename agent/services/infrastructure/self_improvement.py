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
        from runtime_safety import CONFIG_FILE, invalidate_config_cache

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
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            invalidate_config_cache()
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


def generate_proposals(
    session_summary: str = "",
    capability_levels: dict[str, Any] | None = None,
    recent_failures: list[str] | None = None,
) -> dict[str, Any]:
    """
    Deterministic, high-precision proposal generator.
    Produces a small set of safe defaults; operator must approve.
    """
    fails = recent_failures or []
    summ = (session_summary or "").strip()

    proposals: list[dict[str, Any]] = []

    # Very safe core maintenance suggestions
    proposals.append(
        {
            "title": "Enable output quality gate (if not already) to reduce AI artifacts",
            "rationale": "Keeps outputs consistent and removes common hedges without changing code blocks.",
            "risk_level": "low",
            "domain": "ux",
            "instructions": {"config_keys": {"output_quality_gate_enabled": True}},
        }
    )
    if fails:
        proposals.append(
            {
                "title": "Review recent failures and add 1 regression test per failure class",
                "rationale": "Turns breakages into permanent coverage; keeps system stable as features grow.",
                "risk_level": "low",
                "domain": "tests",
                "instructions": {"recent_failures": fails[:10]},
            }
        )
    if summ and "performance" in summ.lower():
        proposals.append(
            {
                "title": "Add lightweight perf notes to plan reports (duration + iterations)",
                "rationale": "Helps spot slow loops early without adding new dependencies.",
                "risk_level": "low",
                "domain": "observability",
                "instructions": {"area": "engine_plans"},
            }
        )

    # Persist
    from layla.memory.db import create_improvement

    created = []
    for p in proposals[:6]:
        r = create_improvement(
            p["title"],
            rationale=p.get("rationale", ""),
            risk_level=p.get("risk_level", "low"),
            domain=p.get("domain", ""),
            instructions=p.get("instructions", {}),
        )
        if r.get("ok") and r.get("proposal"):
            created.append(r["proposal"])
    return {"ok": True, "created": created, "count_created": len(created)}


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


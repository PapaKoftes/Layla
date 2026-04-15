"""
Rule-based initiative hints from run state (suggestions only; no tool execution).

Gated by runtime_config initiative_engine_enabled. Complements initiative_inline
and optional wakeup lines.
"""
from __future__ import annotations

from typing import Any


def collect_initiative_hints(state: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Return short hint strings derived from the last agent state (bounded list)."""
    if not bool(cfg.get("initiative_engine_enabled", False)):
        return []
    out: list[str] = []
    steps = state.get("steps") or []
    if not isinstance(steps, list):
        return []

    for s in reversed(steps):
        if not isinstance(s, dict):
            continue
        act = str(s.get("action") or "").strip()
        if act in ("reason", "think", "client_abort", "none", ""):
            continue
        r = s.get("result")
        if isinstance(r, dict) and r.get("ok") is False:
            err = str(r.get("error") or r.get("reason") or "error")[:100]
            out.append(f"Recent `{act}` failed ({err}) — add a read or narrow verify step before retrying.")
            break

    try:
        from services.outcome_evaluation import evaluate_outcome_structured

        probe = {**state, "status": state.get("status") or "finished"}
        ev = evaluate_outcome_structured(probe)
        if ev.get("reason") not in ("ok", "reply_only") and ev.get("improvement"):
            imp = str(ev["improvement"]).strip()
            if imp and imp not in out:
                out.append(imp[:300])
    except Exception:
        pass

    if len(out) < 2:
        goal = (state.get("original_goal") or state.get("objective") or "").lower()
        if any(k in goal for k in ("implement", "fix", "refactor")) and len(steps) >= 2:
            out.append("Checkpoint: confirm the smallest behavior change you are proving before expanding edits.")
        try:
            from services.skill_discovery import suggest_packs_for_goal

            packs = suggest_packs_for_goal(state.get("original_goal") or state.get("objective") or "")
            if packs:
                out.append("Optional skill packs that may help: " + ", ".join(packs[:4]))
        except Exception:
            pass

    seen: set[str] = set()
    deduped: list[str] = []
    for h in out:
        key = h[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)
    return deduped[:4]


def wakeup_engine_hints(active_plans: list[Any], cfg: dict[str, Any]) -> list[str]:
    """Read-only wakeup lines when initiative_engine_enabled (no workspace mutation)."""
    if not bool(cfg.get("initiative_engine_enabled", False)):
        return []
    hints: list[str] = []
    n = len(active_plans) if active_plans else 0
    if n >= 4:
        hints.append("You have several active study plans — consider pausing all but one for a week to build momentum.")
    elif n == 0:
        hints.append("No active study plans — one concrete topic in the Study panel can anchor daily progress.")
    else:
        hints.append("Pick the next 25-minute block on your top study plan before opening new scope.")
    return hints[:2]


def generate_project_proposals(workspace_root: str = "", cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Generate 1-3 actionable project ideas from workspace project memory.
    Text-only; no tool execution. Gated by initiative_project_proposals_enabled.
    """
    c = cfg if isinstance(cfg, dict) else {}
    if not bool(c.get("initiative_project_proposals_enabled", False)):
        return []
    try:
        from services.maturity_engine import get_trust_tier

        if get_trust_tier(c) < 2:
            return []
    except Exception:
        pass
    try:
        import runtime_safety
        from services.project_memory import load_project_memory

        root = (workspace_root or "").strip()
        ws = root if root else str(runtime_safety.REPO_ROOT)
        mem = load_project_memory(ws)
    except Exception:
        mem = {}

    # Build a compact prompt from memory fields.
    files = mem.get("files") if isinstance(mem.get("files"), dict) else {}
    todos = mem.get("todos") if isinstance(mem.get("todos"), list) else []
    plan = mem.get("plan") if isinstance(mem.get("plan"), dict) else {}
    issues = mem.get("issues") if isinstance(mem.get("issues"), list) else []
    summary = mem.get("summary") if isinstance(mem.get("summary"), str) else ""

    ctx_lines: list[str] = []
    if summary:
        ctx_lines.append(f"Workspace summary: {summary[:400]}")
    if plan:
        g = (plan.get("goal") or "").strip()
        if g:
            ctx_lines.append(f"Current plan goal: {g[:200]}")
    if todos:
        ctx_lines.append("Todos: " + "; ".join(str(t)[:140] for t in todos[:8]))
    if issues:
        ctx_lines.append("Known issues: " + "; ".join(str(i)[:140] for i in issues[:6]))
    if files:
        ctx_lines.append(f"Files indexed: {len(files)}")
    ctx = "\n".join(ctx_lines).strip()

    prompt = (
        "You are Layla. Propose 1-3 small, high-impact projects the operator can do next.\n"
        "Use the workspace context below. Focus on shippable improvements, tests, or UX hardening.\n\n"
        f"{ctx}\n\n"
        "Return ONLY JSON (no markdown) as: "
        '{"proposals":[{"title":"...","scope":"...","effort":"S|M|L","why_now":"..."}]}\n'
    )
    try:
        import json as _json

        from services.llm_gateway import run_completion

        out = run_completion(prompt, max_tokens=260, temperature=0.2, stream=False)
        text = ""
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
        data = _json.loads(text) if text.strip().startswith("{") else {}
        props = data.get("proposals") if isinstance(data, dict) else None
        if isinstance(props, list):
            cleaned: list[dict[str, Any]] = []
            for p in props[:3]:
                if not isinstance(p, dict):
                    continue
                title = str(p.get("title") or "").strip()
                if not title:
                    continue
                cleaned.append(
                    {
                        "title": title[:120],
                        "scope": str(p.get("scope") or "").strip()[:400],
                        "effort": str(p.get("effort") or "M").strip()[:2],
                        "why_now": str(p.get("why_now") or "").strip()[:300],
                    }
                )
            return cleaned
    except Exception:
        pass
    return []

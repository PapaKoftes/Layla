"""Study plans, wakeup, aspect titles."""
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from layla.time_utils import utcnow

# North Star §10+§14: data-driven initiative (rule order = priority; first match wins)
INITIATIVE_RULES = [
    {"condition": "planning_and_goals", "suggestion": "I can help break down your goals into steps when you're ready."},
    {"condition": "idea", "suggestion": "When you want to move from idea to plan, I can help structure it."},
    {"condition": "has_plans", "suggestion": "You have active study plans; say when you want to dive into one."},
    {"condition": "no_stage", "suggestion": "Set a lifecycle stage (idea, planning, prototype, iteration, execution, reflection) to get stage-specific help."},
]


def _initiative_condition_matches(condition: str, pc: dict, active_plans: list) -> bool:
    """True if the named condition matches current project context and plans."""
    name = (pc.get("project_name") or "").strip()
    stage = (pc.get("lifecycle_stage") or "").strip()
    goals = (pc.get("goals") or "").strip()
    if condition == "planning_and_goals":
        return bool(name and stage == "planning" and goals)
    if condition == "idea":
        return bool(name and stage == "idea")
    if condition == "has_plans":
        return bool(active_plans and len(active_plans) > 0)
    if condition == "no_stage":
        return bool(name and not stage)
    return False


def _wakeup_initiative_suggestion(active_plans: list, greeting_parts: list) -> str:
    """North Star §10+§14: one short proactive suggestion (gated — text only). Uses INITIATIVE_RULES; first match wins."""
    try:
        from layla.memory.db import get_project_context
        pc = get_project_context()
        for rule in INITIATIVE_RULES:
            if _initiative_condition_matches(rule["condition"], pc, active_plans):
                return (rule.get("suggestion") or "").strip()
    except Exception as e:
        logger.debug("_wakeup_initiative_suggestion failed: %s", e)
    return ""

from shared_state import (  # noqa: E402
    get_run_autonomous_study,
    get_touch_activity,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["study"])

# Curated one-click topics for the Web UI (no network; safe to ship in-repo).
STUDY_PRESET_TOPICS: list[str] = [
    "Python type hints and pydantic models",
    "FastAPI: routers, dependencies, and lifespan",
    "SQLite migrations and forward-compatible schemas",
    "Local LLM limits: context window, sampling, tool loops",
    "Testing with pytest: fixtures and parametrize",
    "Git workflow: branches, rebases, and clean history",
]


def _workspace_study_suggestions(root: Path, max_entries: int = 400) -> list[str]:
    """Read-only, single-level scan + optional README title. No network."""
    out: list[str] = []
    if not root.is_dir():
        return out
    try:
        children = list(root.iterdir())
    except OSError:
        return out
    children = [p for p in children[:max_entries] if not p.name.startswith(".")]
    readme = next((p for p in children if p.is_file() and p.name.lower() in ("readme.md", "readme.txt")), None)
    if readme:
        try:
            text = readme.read_text(encoding="utf-8", errors="replace")
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    title = line.lstrip("#").strip()[:160]
                    if title:
                        out.append(f"Project overview: {title}")
                        break
                out.append(f"Project notes: {line[:160]}")
                break
        except OSError:
            pass
    exts: dict[str, int] = {}
    for p in children:
        if p.is_file() and p.suffix:
            suf = p.suffix.lower()
            exts[suf] = exts.get(suf, 0) + 1
    if exts.get(".py", 0) >= 2:
        out.append("Python architecture and modules in this workspace")
    if exts.get(".ts", 0) + exts.get(".tsx", 0) >= 2:
        out.append("TypeScript/React structure in this workspace")
    if exts.get(".md", 0) >= 3:
        out.append("Documentation set: how to navigate these markdown docs")
    return out[:8]


def _derive_topic_from_message(message: str) -> str:
    """Turn last user text into a short study topic (heuristic, privacy-preserving)."""
    raw = (message or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    line = raw.split(".")[0].strip()
    if len(line) > 200:
        line = line[:200].rsplit(" ", 1)[0]
    words = line.split()
    if len(words) > 14:
        line = " ".join(words[:14]) + "…"
    return line[:500]


@router.get("/study_plans/presets")
def get_study_plan_presets():
    return JSONResponse({"topics": STUDY_PRESET_TOPICS})


@router.get("/study_plans/suggestions")
def get_study_plan_suggestions():
    """Safe local signals from configured sandbox_root only (single directory level)."""
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        root = Path(str(cfg.get("sandbox_root") or Path.home())).expanduser().resolve()
        topics = _workspace_study_suggestions(root)
        return JSONResponse({"suggestions": topics, "root": str(root)})
    except Exception as e:
        logger.warning("get_study_plan_suggestions failed: %s", e)
        return JSONResponse({"suggestions": [], "error": str(e)})


@router.post("/study_plans/derive_topic")
def derive_study_topic(req: dict):
    """Derive a study topic string from chat text (no LLM)."""
    msg = (req or {}).get("message") or (req or {}).get("text") or ""
    topic = _derive_topic_from_message(str(msg))
    if not topic:
        return JSONResponse({"ok": False, "error": "empty_message"})
    return JSONResponse({"ok": True, "topic": topic})


@router.get("/study_plans")
def get_study_plans():
    """List active study plans with session counts from audit (single source; replaces legacy main.py route)."""
    try:
        from layla.memory.db import _conn, get_active_study_plans, migrate

        migrate()
        plans = get_active_study_plans()
        enriched = []
        with _conn() as db:
            for p in plans:
                topic_snip = (p.get("topic") or "")[:30]
                try:
                    row = db.execute(
                        "SELECT COUNT(*) as cnt, MAX(timestamp) as last FROM audit WHERE tool='study' AND args_summary LIKE ?",
                        (f"%{topic_snip}%",),
                    ).fetchone()
                    sessions = row["cnt"] if row else 0
                    last = row["last"] if row else None
                except Exception:
                    sessions = 0
                    last = None
                # last_studied: audit trail when study tool ran; else column from record_progress / DB
                _ls = p.get("last_studied")
                last_studied = last or _ls or ""
                enriched.append({
                    "id": p.get("id"),
                    "topic": p.get("topic", ""),
                    "notes": p.get("notes", "") or "",
                    "created_at": p.get("created_at", ""),
                    "study_sessions": sessions,
                    "last_studied": last_studied,
                })
        return JSONResponse({"plans": enriched})
    except Exception as e:
        logger.exception("get_study_plans failed")
        return JSONResponse({"plans": [], "error": str(e)})


@router.delete("/study_plans/{plan_id}")
def delete_study_plan(plan_id: int):
    try:
        from layla.memory.db import _conn, migrate

        migrate()
        with _conn() as db:
            db.execute("DELETE FROM study_plans WHERE id=?", (plan_id,))
            db.commit()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/capabilities")
def get_capabilities():
    """Evolution layer: return capability domains and current growth state."""
    try:
        from layla.memory.db import get_capabilities as get_caps
        from layla.memory.db import get_capability_domains
        domains = get_capability_domains()
        caps = get_caps()
        return JSONResponse({"domains": domains, "capabilities": caps})
    except Exception as e:
        logger.exception("get_capabilities failed")
        return JSONResponse({"domains": [], "capabilities": [], "error": str(e)})


@router.post("/study_plans")
def add_study_plan(req: dict):
    get_touch_activity()()
    from layla.memory.db import get_plan_by_topic, save_study_plan
    topic = (req or {}).get("topic", "").strip()[:500]
    domain_id = (req or {}).get("domain_id") or None
    if isinstance(domain_id, str):
        domain_id = domain_id.strip() or None
    if not topic:
        return JSONResponse({"ok": False, "error": "No topic"})
    existing = get_plan_by_topic(topic)
    if existing:
        return JSONResponse({"ok": True, "topic": topic, "already_exists": True})
    plan_id = uuid.uuid4().hex[:8]
    save_study_plan(plan_id=plan_id, topic=topic, status="active", domain_id=domain_id)
    return JSONResponse({"ok": True, "topic": topic, "domain_id": domain_id})


@router.post("/study_plans/record_progress")
def record_study_progress(req: dict):
    get_touch_activity()()
    from layla.memory.db import get_plan_by_topic, save_study_plan, update_study_progress
    topic = (req or {}).get("topic", "").strip()
    note = (req or {}).get("note", "").strip()
    if not topic:
        return JSONResponse({"ok": False, "error": "No topic"})
    if not note:
        return JSONResponse({"ok": False, "error": "No note"})
    plan = get_plan_by_topic(topic)
    if not plan:
        plan_id = uuid.uuid4().hex[:8]
        save_study_plan(plan_id=plan_id, topic=topic, status="active")
        plan = {"id": plan_id, "topic": topic}
    try:
        update_study_progress(plan["id"], note[:2000])
    except Exception as e:
        logger.exception("record_study_progress failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "topic": topic})


@router.get("/wakeup")
def wakeup():
    get_touch_activity()()
    from layla.memory.db import get_active_study_plans, get_last_wakeup, log_wakeup

    last_row = get_last_wakeup()
    last_ts = last_row.get("timestamp") if last_row else None
    elapsed_hours = 0
    if last_ts:
        try:
            from datetime import datetime, timezone
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            last_dt_utc = last_dt.replace(tzinfo=timezone.utc) if last_dt.tzinfo is None else last_dt
            elapsed_hours = round((utcnow() - last_dt_utc).total_seconds() / 3600, 1)
        except Exception as e:
            logger.debug("wakeup elapsed_hours parse failed: %s", e)

    active_plans = get_active_study_plans()
    greeting_parts = []
    if elapsed_hours > 0:
        greeting_parts.append(f"It has been {elapsed_hours} hours since our last session.")
    else:
        greeting_parts.append("Session starting.")

    # Layla v3: explicitly frame the early trial phase.
    maturity_payload: dict = {}
    try:
        from services.maturity_engine import get_milestones_status, get_state, xp_needed_for_next

        ms = get_state()
        need = xp_needed_for_next(ms.rank)
        maturity_payload = {
            "rank": int(ms.rank),
            "xp": int(ms.xp),
            "phase": str(ms.phase),
            "xp_to_next": int(need) if need is not None else None,
            "milestones": get_milestones_status(ms.phase),
        }

        # Layla v3: growth delta line (compare to last wakeup rank; store in user_identity)
        try:
            from layla.memory.db import get_user_identity, set_user_identity

            prev_rank = get_user_identity("last_wakeup_rank") or ""
            try:
                prev_i = int(str(prev_rank).strip() or "0")
            except Exception:
                prev_i = 0
            delta = int(ms.rank) - int(prev_i)
            if delta > 0:
                greeting_parts.append(f"Growth delta: +{delta} mastery rank since last wakeup (MR {prev_i} → {int(ms.rank)}).")
            set_user_identity("last_wakeup_rank", str(int(ms.rank)))
        except Exception:
            pass

        if ms.phase == "awakening":
            greeting_parts.append(
                "Awakening: I'm in my early growth phase. I'll observe, ask clarifying questions, and build a profile of what you need."
            )
    except Exception:
        pass

    # Layla v3: cross-session continuity (journal + pending improvements)
    try:
        from layla.memory.db import list_improvements, list_journal_entries

        recent = list_journal_entries(limit=3)
        if recent:
            greeting_parts.append("Recent journal:")
            for e in recent[:3]:
                greeting_parts.append(
                    f"- {str(e.get('created_at') or '')[:16]} · {(e.get('entry_type') or 'note')}: {(e.get('content') or '')[:120]}"
                )
        pend = list_improvements(status="pending", limit=5)
        if pend:
            greeting_parts.append("Pending improvements:")
            for p in pend[:5]:
                greeting_parts.append(f"- #{p.get('id')}: {(p.get('title') or '')[:140]}")
    except Exception:
        pass

    # Layla v3: surface up to 2 recent plan reports in greeting (sandbox_root scan)
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        root = Path(str(cfg.get("sandbox_root") or Path.home())).expanduser().resolve()
        candidate_roots: list[Path] = []
        if root.is_dir():
            candidate_roots.append(root)
            try:
                # Shallow scan: root + its immediate child dirs (avoid expensive recursion)
                for p in list(root.iterdir())[:60]:
                    if p.is_dir() and not p.name.startswith("."):
                        candidate_roots.append(p)
            except Exception:
                pass

        reports: list[Path] = []
        for cr in candidate_roots:
            d = cr / ".layla" / "plan_reports"
            if not d.is_dir():
                continue
            try:
                for f in list(d.glob("*.md"))[:200]:
                    if f.is_file():
                        reports.append(f)
            except Exception:
                continue

        reports = sorted(reports, key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)[:2]
        if reports:
            greeting_parts.append("Recent plan reports:")
            for f in reports:
                try:
                    txt = f.read_text(encoding="utf-8", errors="replace")
                    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                    title = lines[0].lstrip("#").strip() if lines else f.name
                    status = next((ln for ln in lines if ln.lower().startswith("**status:**")), "")
                    goal = next((ln for ln in lines if ln.lower().startswith("**goal:**")), "")
                    snippet = " · ".join([x for x in (title, status, goal) if x])[:220]
                    greeting_parts.append(f"- {snippet} ({f.name})")
                except Exception:
                    greeting_parts.append(f"- {f.name}")
    except Exception:
        pass

    last_notes = (last_row or {}).get("notes", "")
    if last_notes:
        greeting_parts.append(f"Since we last spoke: {last_notes}")

    studied_topic_this_wakeup = None
    run_study = get_run_autonomous_study()
    if active_plans and run_study:
        use_capabilities = False
        try:
            import runtime_safety
            use_capabilities = bool(runtime_safety.load_config().get("scheduler_use_capabilities", False))
        except Exception as e:
            logger.debug("wakeup scheduler_use_capabilities failed: %s", e)
        plan = None
        domain_id = None
        try:
            from layla.memory import capabilities as cap_mod
            plan, domain_id = cap_mod.get_next_plan_for_study(active_plans, use_capabilities=use_capabilities)
        except Exception as e:
            logger.debug("wakeup get_next_plan_for_study failed: %s", e)
        if not plan:
            plan = min(active_plans, key=lambda p: (p.get("last_studied") or "") or "0000")
        try:
            summary = run_study(plan)
            studied_topic_this_wakeup = plan.get("topic")
            if domain_id:
                try:
                    from layla.memory import capabilities as cap_mod
                    from layla.memory.db import append_scheduler_history
                    usefulness = cap_mod.run_learning_validation(summary)
                    cap_mod.record_practice(domain_id, mission_id=plan.get("id"), usefulness_score=usefulness)
                    append_scheduler_history(domain_id, plan.get("id"))
                except Exception as e:
                    logger.warning("wakeup capability record failed: %s", e)
        except Exception as e:
            logger.warning("wakeup autonomous study failed: %s", e)
    try:
        active_plans = get_active_study_plans()
    except Exception as e:
        logger.debug("wakeup get_active_study_plans refresh failed: %s", e)

    for plan in active_plans[:3]:
        topic = plan.get("topic", "")
        last_studied = plan.get("last_studied")
        if last_studied:
            greeting_parts.append(f"Active study: '{topic}' (last studied: {last_studied}).")
        else:
            greeting_parts.append(f"Active study plan pending: '{topic}'.")
    if studied_topic_this_wakeup:
        greeting_parts.append(f"I looked into '{studied_topic_this_wakeup}' since we last talked.")

    # North Star §10+§14: optional proactive initiative (gated — text only, no auto-execution)
    try:
        cfg = __import__("runtime_safety", fromlist=["load_config"]).load_config()
        if cfg.get("wakeup_include_initiative", False):
            initiative = _wakeup_initiative_suggestion(active_plans, greeting_parts)
            if initiative:
                greeting_parts.append("Suggestion: " + initiative)
            if cfg.get("initiative_engine_enabled", False):
                try:
                    from services.initiative_engine import wakeup_engine_hints

                    for h in wakeup_engine_hints(active_plans, cfg):
                        if h:
                            greeting_parts.append("Initiative: " + h)
                except Exception as _ie:
                    logger.debug("wakeup initiative_engine failed: %s", _ie)
                if cfg.get("initiative_project_proposals_enabled", False):
                    try:
                        import runtime_safety
                        from services.initiative_engine import generate_project_proposals

                        props = generate_project_proposals(str(runtime_safety.REPO_ROOT), cfg)
                        if props:
                            p0 = props[0]
                            title = str(p0.get("title") or "").strip()
                            why = str(p0.get("why_now") or "").strip()
                            if title:
                                line = f"Project idea: {title}"
                                if why:
                                    line += f" — {why[:180]}"
                                greeting_parts.append(line)
                    except Exception as _pp:
                        logger.debug("wakeup project proposals failed: %s", _pp)
        # Optional one-liner from project discovery (tighter use of discovery)
        if cfg.get("wakeup_include_discovery_line", False):
            try:
                from services.project_discovery import run_project_discovery
                disc = run_project_discovery()
                opps = (disc.get("opportunities") or [])[:1]
                ideas = (disc.get("ideas") or [])[:1]
                line = (opps[0] if opps else ideas[0] if ideas else "").strip()
                if line and len(line) <= 200:
                    greeting_parts.append("Discovery: " + line)
            except Exception as e:
                logger.debug("wakeup project_discovery failed: %s", e)
        # Curiosity suggestions: surface knowledge gaps at wakeup (gated — text only)
        if cfg.get("wakeup_include_curiosity", False):
            try:
                from services.curiosity_engine import get_curiosity_suggestions
                gaps = get_curiosity_suggestions()
                if gaps:
                    greeting_parts.append("Knowledge gap: " + gaps[0].strip())
            except Exception as e:
                logger.debug("wakeup curiosity_engine failed: %s", e)
    except Exception as e:
        logger.debug("wakeup initiative/discovery config failed: %s", e)

    greeting_text = " ".join(greeting_parts)
    log_wakeup(greeting=greeting_text, notes="")

    return JSONResponse({
        "ok": True,
        "greeting": greeting_text,
        "aspect": "echo",
        "active_study_plans": [p.get("topic") for p in active_plans],
        "elapsed_hours": elapsed_hours,
        "studied_this_wakeup": studied_topic_this_wakeup,
        "maturity_rank": maturity_payload.get("rank") if isinstance(maturity_payload, dict) else None,
        "maturity_xp": maturity_payload.get("xp") if isinstance(maturity_payload, dict) else None,
        "maturity_phase": maturity_payload.get("phase") if isinstance(maturity_payload, dict) else None,
        "maturity": maturity_payload,
    })


@router.get("/aspects/{aspect_id}/title")
def get_aspect_title(aspect_id: str):
    from layla.memory.db import get_earned_title
    title = get_earned_title(aspect_id)
    return JSONResponse({"aspect_id": aspect_id, "title": title})


@router.post("/aspects/{aspect_id}/title")
def set_aspect_title(aspect_id: str, req: dict):
    from layla.memory.db import save_earned_title
    title = (req or {}).get("title", "").strip()[:200]
    if not title:
        return JSONResponse({"ok": False, "error": "No title"})
    save_earned_title(aspect_id, title)
    return JSONResponse({"ok": True, "aspect_id": aspect_id, "title": title})

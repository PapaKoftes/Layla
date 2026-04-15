"""
Root coordinator: unify task classification, execution mode, and dispatch to autonomous_run.

Optional: parallel subtasks (async), task-graph execution — see run_with_plan_graph.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("layla")

ExecutionMode = str  # "fast" | "deep" | "tool_heavy"


@dataclass
class TaskClassification:
    task_kind: str  # model_router: coding|reasoning|chat|default
    reasoning_depth: str  # none|light|deep
    execution_mode: ExecutionMode
    complexity_score: float  # 0..1 heuristic


def classify(goal: str, context: str, cfg: dict, *, research_mode: bool = False) -> TaskClassification:
    from services.model_router import classify_task_for_routing
    from services.reasoning_classifier import classify_reasoning_need

    task_kind = classify_task_for_routing(goal, context or "", cfg)
    rdepth = classify_reasoning_need(goal, context or "", research_mode=research_mode)
    g = (goal or "").strip()
    c = (context or "").strip()
    combined_len = len(g) + len(c)
    complexity_score = min(1.0, combined_len / 1200.0)
    if rdepth == "deep" or task_kind == "coding":
        complexity_score = max(complexity_score, 0.6)
    if rdepth == "none" and task_kind == "chat" and len(g) < 50:
        mode: ExecutionMode = "fast"
    elif task_kind == "coding" or "implement" in g.lower() or "fix" in g.lower():
        mode = "tool_heavy"
    elif rdepth == "deep":
        mode = "deep"
    else:
        mode = "deep" if complexity_score > 0.45 else "fast"
    return TaskClassification(
        task_kind=task_kind,
        reasoning_depth=rdepth,
        execution_mode=mode,
        complexity_score=complexity_score,
    )


def build_coordinator_trace(
    goal: str,
    context: str,
    cfg: dict,
    *,
    research_mode: bool = False,
    allow_write: bool = False,
    allow_run: bool = False,
) -> dict[str, Any]:
    tc = classify(goal, context, cfg, research_mode=research_mode)
    pref: str | None = None
    try:
        from layla.memory.strategy_stats import get_preferred_strategy

        _g = (goal or "").replace("\n", " ").strip()[:120] or "general"
        pref = get_preferred_strategy(_g, min_samples=int(cfg.get("strategy_preference_min_samples", 5) or 5))
    except Exception:
        pref = None
    out: dict[str, Any] = {
        "task_kind": tc.task_kind,
        "reasoning_depth": tc.reasoning_depth,
        "execution_mode": tc.execution_mode,
        "complexity_score": tc.complexity_score,
        "allow_write": allow_write,
        "allow_run": allow_run,
    }
    if pref:
        out["preferred_strategy"] = pref
    try:
        if bool(cfg.get("coordinator_task_budget_hint_enabled", True)):
            from services.task_budget import allocate_budget, profile_task

            prof = profile_task(
                goal,
                context or "",
                reasoning_mode=tc.reasoning_depth,
                research_mode=research_mode,
                allow_write=allow_write,
                allow_run=allow_run,
            )
            env = allocate_budget(prof, cfg)
            out["task_budget"] = {"profile": prof.to_trace_dict(), "envelope": env.to_trace_dict()}
    except Exception as _e:
        logger.debug("coordinator task_budget trace: %s", _e)
    return out


def dispatch_autonomous_run(
    run_fn: Callable[..., dict],
    goal: str,
    **kwargs: Any,
) -> dict:
    """
    Entry from HTTP/MCP: optionally record coordinator trace, then call autonomous_run.
    When kwargs already contain coordinator_trace (from coordinator.run), it is reused.
    """
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}
    if not bool(cfg.get("coordinator_enabled", True)):
        return run_fn(goal, **kwargs)
    context = str(kwargs.get("context") or "")
    conversation_id = str(kwargs.get("conversation_id") or "")
    research_mode = bool(kwargs.get("research_mode", False))
    allow_write = bool(kwargs.get("allow_write", False))
    allow_run = bool(kwargs.get("allow_run", False))
    trace = kwargs.get("coordinator_trace")
    if not isinstance(trace, dict) or trace.get("complexity_score") is None:
        trace = build_coordinator_trace(
            goal,
            context,
            cfg,
            research_mode=research_mode,
            allow_write=allow_write,
            allow_run=allow_run,
        )
        kwargs = dict(kwargs)
        kwargs["coordinator_trace"] = trace
    try:
        from shared_state import set_last_coordinator_trace

        set_last_coordinator_trace(conversation_id, trace)
    except Exception as _e:
        logger.debug("coordinator trace: %s", _e)
    task_id: str | None = None
    if bool(cfg.get("task_persistence_enabled", True)):
        try:
            from layla.memory.db import create_persistent_task

            task_id = create_persistent_task(goal=goal, conversation_id=conversation_id)
        except Exception as _te:
            logger.debug("task persist create: %s", _te)
    try:
        result = run_fn(goal, **kwargs)
    except Exception:
        if task_id:
            try:
                from layla.memory.db import update_persistent_task

                update_persistent_task(task_id, status="failed")
            except Exception:
                pass
        raise
    if task_id:
        try:
            from layla.memory.db import update_persistent_task

            st = result.get("status") if isinstance(result, dict) else None
            update_persistent_task(
                task_id,
                status=str(st or "unknown"),
                results=result.get("steps") if isinstance(result, dict) else None,
                execution_state=result if isinstance(result, dict) else None,
            )
        except Exception as _ue:
            logger.debug("task persist update: %s", _ue)
    try:
        if isinstance(result, dict):
            from shared_state import set_last_execution_snapshot

            snap = {
                "execution_id": result.get("execution_id"),
                "status": result.get("status"),
                "pipeline_stage": result.get("pipeline_stage"),
                "tool_calls": result.get("tool_calls"),
                "steps_preview": (result.get("steps") or [])[-12:],
                "coordinator_trace": trace,
            }
            if result.get("plan_execution_fallback") is not None:
                snap["plan_execution_fallback"] = result.get("plan_execution_fallback")
            if result.get("coordinator_retry_attempts") is not None:
                snap["coordinator_retry_attempts"] = result.get("coordinator_retry_attempts")
            set_last_execution_snapshot(conversation_id, snap)
    except Exception:
        pass
    try:
        if isinstance(result, dict) and cfg.get("execution_trace_log_enabled", True):
            from services.observability import log_execution_trace

            log_execution_trace(
                {
                    "execution_id": result.get("execution_id"),
                    "status": result.get("status"),
                    "pipeline_stage": result.get("pipeline_stage"),
                    "tool_calls": result.get("tool_calls"),
                    "steps": result.get("steps"),
                    "plan_execution_fallback": result.get("plan_execution_fallback") if isinstance(result, dict) else None,
                    "coordinator_retry_attempts": result.get("coordinator_retry_attempts") if isinstance(result, dict) else None,
                }
            )
    except Exception:
        pass
    return result


def run(run_fn: Callable[..., dict], goal: str, **kwargs: Any) -> dict:
    """
    Single outer entry from HTTP: resume merge, optional worktree, coordinator trace,
    then dispatch_autonomous_run. Nested plan steps call autonomous_run / run_fn directly.
    """
    worktree_path: str | None = None
    kw = dict(kwargs)
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    resume_id = str(kw.pop("resume_task_id", None) or kw.pop("resume_from_task_id", None) or "").strip()
    if resume_id:
        try:
            from layla.memory.db import get_persistent_task

            row = get_persistent_task(resume_id)
            if row:
                if not str(goal or "").strip():
                    goal = str(row.get("goal") or "")
                es = row.get("execution_state_json")
                if isinstance(es, dict) and es:
                    kw["resume_execution_state"] = es
                if not str(kw.get("conversation_id") or "").strip() and row.get("conversation_id"):
                    kw["conversation_id"] = str(row.get("conversation_id") or "")
        except Exception as e:
            logger.debug("coordinator.run resume: %s", e)

    context = str(kw.get("context") or "")
    conversation_id = str(kw.get("conversation_id") or "")
    research_mode = bool(kw.get("research_mode", False))
    allow_write = bool(kw.get("allow_write", False))
    allow_run = bool(kw.get("allow_run", False))
    trace = build_coordinator_trace(
        goal,
        context,
        cfg,
        research_mode=research_mode,
        allow_write=allow_write,
        allow_run=allow_run,
    )
    kw["coordinator_trace"] = trace
    try:
        from shared_state import set_last_coordinator_trace

        set_last_coordinator_trace(conversation_id, trace)
    except Exception:
        pass

    if bool(cfg.get("worktree_isolation_enabled", False)):
        if trace.get("task_kind") == "coding" or trace.get("execution_mode") == "tool_heavy":
            wr = str(kw.get("workspace_root") or "").strip() or str(cfg.get("sandbox_root") or "").strip()
            if wr:
                try:
                    from pathlib import Path

                    from services.worktree_manager import create_worktree

                    root = Path(wr).expanduser().resolve()
                    if root.is_dir() and (root / ".git").exists():
                        wt = create_worktree(str(root))
                        kw["workspace_root"] = str(wt)
                        worktree_path = str(wt)
                except Exception as e:
                    logger.debug("coordinator.run worktree: %s", e)

    try:
        max_attempts = int(cfg.get("coordinator_dispatch_max_attempts", 1) or 1)
    except (TypeError, ValueError):
        max_attempts = 1
    max_attempts = max(1, min(3, max_attempts))
    # Trust tiers: never allow multi-attempt coordinator retries unless explicitly operator-granted.
    try:
        if bool(cfg.get("autonomy_trust_tiers_enabled", False)):
            from services.maturity_engine import get_trust_tier

            if get_trust_tier(cfg) < 3:
                max_attempts = 1
    except Exception:
        pass
    retry_statuses_raw = cfg.get("coordinator_dispatch_retry_on_statuses", ["system_busy", "error"])
    if isinstance(retry_statuses_raw, list):
        retry_statuses = frozenset(str(x).strip() for x in retry_statuses_raw if str(x).strip())
    else:
        retry_statuses = frozenset({"system_busy", "error"})

    result: dict[str, Any] = {}
    try:
        from services.otel_export import maybe_span

        for attempt in range(max_attempts):
            if attempt > 0:
                try:
                    prev = str(result.get("status") or "unknown")
                except Exception:
                    prev = "unknown"
                ctx = str(kw.get("context") or "")
                hint = (
                    f"\n\n[Coordinator retry {attempt + 1}/{max_attempts}: last_status={prev}. "
                    "Change approach: verify assumptions with read/grep, avoid repeating the same tool path.]\n"
                )
                kw["context"] = (ctx + hint) if ctx else hint
            logger.info("coordinator_dispatch_attempt=%d/%d", attempt + 1, max_attempts)
            with maybe_span(cfg, "coordinator_dispatch_attempt", attempt=attempt + 1, max_attempts=max_attempts):
                result = dispatch_autonomous_run(run_fn, goal, **kw)
            if not isinstance(result, dict):
                return {"status": "unknown", "reply": str(result), "steps": []}
            if attempt + 1 >= max_attempts:
                result["coordinator_retry_attempts"] = attempt + 1
                break
            st = str(result.get("status") or "")
            if st not in retry_statuses:
                result["coordinator_retry_attempts"] = attempt + 1
                break
        return result
    finally:
        if worktree_path:
            try:
                from services.worktree_manager import cleanup_worktree

                cleanup_worktree(worktree_path)
            except Exception as e:
                logger.debug("worktree cleanup: %s", e)
        try:
            if bool(cfg.get("coordinator_strategy_feedback_enabled", False)) and isinstance(result, dict):
                if not bool(result.get("strategy_stats_recorded")):
                    pref = str((trace or {}).get("preferred_strategy") or "").strip()
                    if pref:
                        try:
                            from layla.memory.strategy_stats import record_strategy_stat

                            ok = bool(result.get("status") == "finished" or result.get("status") == "plan_completed")
                            _g = (goal or "").replace("\n", " ").strip()[:120] or "general"
                            record_strategy_stat(_g, pref, success=ok)
                            result["strategy_stats_recorded"] = True
                        except Exception as e:
                            logger.debug("coordinator strategy feedback failed: %s", e)
        except Exception:
            pass
        if conversation_id:
            try:
                from services.memory_consolidation import consolidate_session

                consolidate_session(conversation_id)
            except Exception:
                pass


async def run_parallel_subtasks(
    coro_factories: list[Callable[[], Any]],
    *,
    cfg: dict,
) -> list[Any]:
    """Run independent async subtasks (coordinator parallel path)."""
    if not bool(cfg.get("parallel_execution_enabled", False)):
        out: list[Any] = []
        for f in coro_factories:
            out.append(await f())
        return out
    try:
        from services.worker_pool import max_parallel_workers

        cap = max(1, min(len(coro_factories), max_parallel_workers(cfg, len(coro_factories))))
    except Exception:
        cap = min(4, len(coro_factories))
    sem = asyncio.Semaphore(cap)

    async def _bounded(f: Callable[[], Any]) -> Any:
        async with sem:
            return await f()

    return list(await asyncio.gather(*[_bounded(f) for f in coro_factories]))


def run_with_plan_graph(
    *,
    plan_steps: list[dict],
    step_runner: Callable[[dict], dict],
    cfg: dict,
) -> dict:
    """
    Execute a plan as a task graph when coordinator + graph execution enabled.
    step_runner: callable taking a plan step dict, returns result dict.
    """
    if not bool(cfg.get("coordinator_graph_execution_enabled", False)):
        return {"ok": False, "reason": "graph_disabled", "results": []}
    try:
        import uuid

        from services.task_graph import GraphExecutor, plan_steps_to_task_graph

        norm: list[dict] = []
        for s in plan_steps:
            if not isinstance(s, dict):
                continue
            d = dict(s)
            sid = str(d.get("id") or d.get("step") or "").strip()
            if not sid:
                sid = str(uuid.uuid4())[:8]
            d["id"] = sid
            norm.append(d)
        graph = plan_steps_to_task_graph(norm)

        def _executor_fn(node_id: str, task: str, tools: list[str]) -> dict:
            return step_runner({"step": node_id, "task": task, "tools": tools, "role": ""})

        ex = GraphExecutor(graph, executor_fn=_executor_fn)
        results = ex.run_until_complete_parallel()
        return {"ok": True, "results": results}
    except Exception as e:
        logger.warning("run_with_plan_graph failed: %s", e)
        return {"ok": False, "error": str(e), "results": []}


def merge_outputs(results: list[dict]) -> dict:
    """Merge subtask outputs into one payload (best-effort)."""
    texts: list[str] = []
    for r in results:
        if isinstance(r, dict):
            t = (r.get("response") or r.get("summary") or "").strip()
            if t:
                texts.append(t)
    return {"merged_text": "\n\n---\n\n".join(texts), "parts": results}


def resume_from_task(task_id: str, cfg: dict | None = None) -> dict[str, Any]:
    """Load persisted execution snapshot (operator / tooling). Does not auto-run the loop."""
    try:
        import runtime_safety

        c = cfg or runtime_safety.load_config()
    except Exception:
        c = {}
    try:
        from layla.memory.db import get_persistent_task

        row = get_persistent_task((task_id or "").strip())
        if not row:
            return {"ok": False, "reason": "not_found"}
        return {"ok": True, "task": row, "graph_resume_hint": bool(c.get("coordinator_graph_execution_enabled", False))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def spawn_subtasks(goal: str, plan: list[dict] | None) -> list[dict]:
    """Derive subtask rows from a plan (read-only structure)."""
    if not plan:
        return [{"task": goal, "tools": [], "role": "executor"}]
    out: list[dict] = []
    for i, p in enumerate(plan):
        if isinstance(p, dict):
            out.append({
                "step": p.get("step", i + 1),
                "task": p.get("task", ""),
                "tools": p.get("tools") if isinstance(p.get("tools"), list) else [],
                "role": p.get("role", "executor"),
            })
    return out or [{"task": goal, "tools": [], "role": "executor"}]

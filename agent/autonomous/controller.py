from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from autonomous.aggregator import aggregate, aggregate_prefetch_hit
from autonomous.audit import AuditLog
from autonomous.budget import Budget, BudgetExceeded
from autonomous.chroma_retrieval import try_chroma_retrieval
from autonomous.context import ContextState, compress_tool_result, normalize_path_for_tracking
from autonomous.investigation_reuse import maybe_append_investigation_reuse
from autonomous.planner import Planner
from autonomous.policy import Policy, PolicyViolation
from autonomous.read_cache import get_cross_run_read_cache
from autonomous.reuse_retrieval import try_reuse_retrieval
from autonomous.types import AutonomousTask, StepRecord
from autonomous.value_gate import evaluate_value_gate
from autonomous.wiki import build_candidate, write_wiki_entry
from autonomous.wiki_retrieval import try_wiki_retrieval
from layla.tools.registry import TOOLS

logger = logging.getLogger("layla")


def _budget_hint(budget: Budget) -> str:
    return f"steps_remaining={budget.remaining_steps()} time_remaining_seconds={int(budget.remaining_seconds())}"


def _maybe_export_wiki_markdown(
    *,
    task: AutonomousTask,
    cfg: dict[str, Any],
    final: dict[str, Any],
    unique_files: int,
) -> dict[str, Any] | None:
    """Optional persistence to .layla/wiki — gated by config + task.allow_write."""
    if not task.allow_write:
        return None
    if not bool(cfg.get("autonomous_wiki_enabled")) or not bool(cfg.get("autonomous_wiki_export_enabled")):
        return None
    if str(final.get("confidence") or "").strip().lower() != "high":
        return None
    if unique_files < 2:
        return None
    title = (task.goal or "").strip()[:120] or "Investigation"
    parts: list[str] = [
        "## Summary\n\n",
        str(final.get("summary") or "")[:8000],
        "\n\n## Findings\n\n",
    ]
    for fd in final.get("findings") or []:
        if not isinstance(fd, dict):
            continue
        parts.append(f"- {str(fd.get('insight') or '')[:600]}\n")
        ev = fd.get("evidence")
        if isinstance(ev, list) and ev:
            parts.append(f"  - Evidence: {', '.join(str(x) for x in ev[:10])}\n")
    cand = build_candidate(title=title, content_md="".join(parts))
    return write_wiki_entry(
        workspace_root=task.workspace_root,
        candidate=cand,
        allow_write=task.allow_write,
        cfg=cfg,
    )


def run_autonomous_task(
    *,
    task: AutonomousTask,
    cfg: dict[str, Any],
    tool_call_hook: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Tier-0 investigation: read-only tools; optional gated wiki markdown export (no shell).
    """
    gate = evaluate_value_gate(task.goal)
    value_gate = {"ok": gate.ok, "reason": gate.reason, "score": gate.score}
    if not gate.ok:
        return aggregate(
            goal=task.goal,
            steps=[],
            value_gate=value_gate,
            stopped_reason="value_gate_reject",
            final_override={
                "ok": False,
                "error": "value_gate_reject",
                "message": (
                    "Autonomous investigation is for multi-step repo analysis only. "
                    "Use POST /agent for direct edits, shell commands, or short single-step tasks."
                ),
                "use_post_agent": True,
                "source": "blocked",
                "reused": False,
            },
            wiki_candidates=None,
            files_accessed=None,
        )

    agent_dir = Path(__file__).resolve().parents[1]
    audit = AuditLog(agent_dir=agent_dir)
    run_id = str(uuid.uuid4())

    if cfg.get("autonomous_prefetch_enabled", True):
        hit = try_reuse_retrieval(goal=task.goal, workspace_root=task.workspace_root, cfg=cfg)
        if hit:
            meta_keys = frozenset({"matched_run_id", "matched_ts", "match_score"})
            pf = {k: v for k, v in hit.items() if k not in meta_keys}
            meta = {k: hit[k] for k in meta_keys if k in hit}
            final = aggregate_prefetch_hit(
                goal=task.goal,
                value_gate=value_gate,
                stopped_reason="reuse_hit",
                prefetch_final=pf,
                source="reuse",
                prefetch_meta=meta,
            )
            try:
                pm = str(cfg.get("model_filename") or cfg.get("model_path") or "")[:500]
            except Exception:
                pm = ""
            final["planner_model"] = pm or "router_default"
            final["budget_counters"] = {
                "steps_used": 0,
                "max_steps": task.max_steps,
                "elapsed_seconds": 0.0,
                "timeout_seconds": task.timeout_seconds,
            }
            audit.write_final(run_id=run_id, final=final)
            logger.debug(
                "autonomous_prefetch: reuse_hit run_id=%s — wiki and chroma not evaluated this request",
                run_id,
            )
            return final

        w_hit = try_wiki_retrieval(goal=task.goal, workspace_root=task.workspace_root, cfg=cfg)
        if w_hit:
            meta_keys = frozenset({"wiki_path", "wiki_title", "wiki_slug", "match_score"})
            pf = {k: v for k, v in w_hit.items() if k not in meta_keys}
            meta = {k: w_hit[k] for k in meta_keys if k in w_hit}
            final = aggregate_prefetch_hit(
                goal=task.goal,
                value_gate=value_gate,
                stopped_reason="wiki_hit",
                prefetch_final=pf,
                source="wiki",
                prefetch_meta=meta,
            )
            try:
                pm = str(cfg.get("model_filename") or cfg.get("model_path") or "")[:500]
            except Exception:
                pm = ""
            final["planner_model"] = pm or "router_default"
            final["budget_counters"] = {
                "steps_used": 0,
                "max_steps": task.max_steps,
                "elapsed_seconds": 0.0,
                "timeout_seconds": task.timeout_seconds,
            }
            audit.write_final(run_id=run_id, final=final)
            logger.debug(
                "autonomous_prefetch: wiki_hit run_id=%s — chroma not evaluated this request",
                run_id,
            )
            return final

        c_hit = try_chroma_retrieval(goal=task.goal, workspace_root=task.workspace_root, cfg=cfg)
        if c_hit:
            meta_keys = frozenset({"embedding_id", "match_score"})
            pf = {k: v for k, v in c_hit.items() if k not in meta_keys}
            meta = {k: c_hit[k] for k in meta_keys if k in c_hit}
            final = aggregate_prefetch_hit(
                goal=task.goal,
                value_gate=value_gate,
                stopped_reason="chroma_hit",
                prefetch_final=pf,
                source="chroma",
                prefetch_meta=meta,
            )
            try:
                pm = str(cfg.get("model_filename") or cfg.get("model_path") or "")[:500]
            except Exception:
                pm = ""
            final["planner_model"] = pm or "router_default"
            final["budget_counters"] = {
                "steps_used": 0,
                "max_steps": task.max_steps,
                "elapsed_seconds": 0.0,
                "timeout_seconds": task.timeout_seconds,
            }
            audit.write_final(run_id=run_id, final=final)
            logger.debug(
                "autonomous_prefetch: chroma_hit run_id=%s — planner prefetch skipped",
                run_id,
            )
            return final

        logger.debug(
            "autonomous_prefetch: miss on reuse, wiki, and chroma run_id=%s — continuing to planner",
            run_id,
        )

    budget = Budget(max_steps=task.max_steps, timeout_seconds=task.timeout_seconds)
    policy = Policy.from_config(cfg)
    planner = Planner(tool_allowlist=sorted(policy.tool_allowlist))
    ctx = ContextState(goal=task.goal)

    steps: list[StepRecord] = []
    stopped_reason = "unknown"
    files_accessed_unique: set[str] = set()
    xrc = get_cross_run_read_cache(cfg)

    try:
        for i in range(task.max_steps):
            budget.consume_step()
            decision = planner.decide(
                goal=task.goal, context=ctx.summarize_for_planner(), budget_hint=_budget_hint(budget)
            )
            if decision.type == "final":
                steps.append(StepRecord(i=i, decision=decision, tool_ok=True, tool_result=decision.final))
                stopped_reason = "planner_final"
                break

            tool = decision.tool
            args = decision.args or {}
            rec = StepRecord(i=i, decision=decision)

            try:
                policy.validate_tool_call(tool, args)

                cached = ctx.maybe_get_cached(tool, args)
                if cached is None and tool == "read_file":
                    cached = ctx.dedupe_file_reads((args or {}).get("path"))
                if cached is None and tool == "read_file" and xrc:
                    rp = str((args or {}).get("path") or "").strip()
                    if rp:
                        cached = xrc.get(rp)
                        if cached is not None:
                            ctx.set_cached(tool, args, cached)
                            ctx.record_read_file_result(args, cached)
                if cached is not None:
                    rec.tool_ok = True
                    rec.tool_result = cached
                else:
                    if tool_call_hook:
                        tool_call_hook(tool, args)
                    fn = (TOOLS.get(tool) or {}).get("fn")
                    if not fn:
                        raise PolicyViolation("tool_missing_fn")
                    result = fn(**args)
                    if not isinstance(result, dict):
                        result = {"ok": True, "result": result}
                    ctx.set_cached(tool, args, result)
                    if tool == "read_file":
                        ctx.record_read_file_result(args, result)
                        if xrc:
                            xrc.put(str((args or {}).get("path") or "").strip(), result)
                    rec.tool_ok = True
                    rec.tool_result = result

                if tool == "read_file":
                    pk = normalize_path_for_tracking((args or {}).get("path"))
                    tr = rec.tool_result if isinstance(rec.tool_result, dict) else {}
                    if pk and tr.get("ok") is not False:
                        files_accessed_unique.add(pk)

                ctx.last_result_summary = compress_tool_result(tool, rec.tool_result or {})
                ctx.record_progress(ctx.last_result_summary)
            except PolicyViolation as e:
                rec.error = str(e)
                rec.tool_ok = False
                rec.tool_result = {"ok": False, "error": str(e)}
                stopped_reason = "policy_violation"
                steps.append(rec)
                audit.write_step(run_id=run_id, step=rec)
                break
            except Exception as e:
                rec.error = f"tool_error:{type(e).__name__}:{e}"
                rec.tool_ok = False
                rec.tool_result = {"ok": False, "error": rec.error}
                steps.append(rec)
                audit.write_step(run_id=run_id, step=rec)
                stopped_reason = "tool_error"
                break

            steps.append(rec)
            audit.write_step(run_id=run_id, step=rec)
        else:
            stopped_reason = "max_steps_loop_end"
    except BudgetExceeded as e:
        stopped_reason = str(e)

    final = aggregate(
        goal=task.goal,
        steps=steps,
        value_gate=value_gate,
        stopped_reason=stopped_reason,
        final_override=None,
        wiki_candidates=None,
        files_accessed=sorted(files_accessed_unique),
    )
    try:
        pm = str(cfg.get("model_filename") or cfg.get("model_path") or "")[:500]
    except Exception:
        pm = ""
    final["planner_model"] = pm or "router_default"
    final["budget_counters"] = {
        "steps_used": getattr(budget, "steps_used", 0),
        "max_steps": getattr(budget, "max_steps", task.max_steps),
        "elapsed_seconds": round(budget.elapsed_seconds(), 2),
        "timeout_seconds": getattr(budget, "timeout_seconds", task.timeout_seconds),
    }
    reuse = maybe_append_investigation_reuse(
        cfg=cfg,
        workspace_root=task.workspace_root,
        goal=task.goal,
        summary=str(final.get("summary") or ""),
        findings=list(final.get("findings") or []),
        confidence=str(final.get("confidence") or ""),
        run_id=run_id,
    )
    if reuse:
        final["investigation_reuse"] = reuse
    wiki_res = _maybe_export_wiki_markdown(
        task=task,
        cfg=cfg,
        final=final,
        unique_files=len(files_accessed_unique),
    )
    if wiki_res:
        final["wiki_export"] = wiki_res
    audit.write_final(run_id=run_id, final=final)
    return final

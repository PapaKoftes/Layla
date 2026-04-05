"""
Subprocess entrypoint for background / spawn jobs (hard cancel via parent SIGTERM/kill).

Run from repo: python background_job_worker.py < job.json
Or: LAYLA_JOB_FILE=/path/to/job.json python background_job_worker.py

Writes one JSON object to stdout (autonomous_run result subset); logs to stderr only.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

logger = logging.getLogger("layla.worker")


def _load_job() -> dict:
    path = (os.environ.get("LAYLA_JOB_FILE") or "").strip()
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    try:
        job = _load_job()
    except Exception as e:
        err = {"ok": False, "error": "invalid_job_json", "detail": str(e)}
        print(json.dumps(err, ensure_ascii=False), flush=True)
        return 1

    _worker_cfg: dict = {}
    try:
        import runtime_safety

        _worker_cfg = runtime_safety.load_config()
    except Exception:
        pass
    try:
        from services.worker_os_limits import apply_background_worker_posix_rlimits

        apply_background_worker_posix_rlimits(_worker_cfg)
    except Exception:
        logging.getLogger("layla.worker").debug("posix rlimits skipped", exc_info=True)

    sand = str(job.get("sandbox_root") or "").strip()
    if sand:
        from layla.tools.registry import set_effective_sandbox

        set_effective_sandbox(sand)

    hist = job.get("conversation_history") or []
    if not isinstance(hist, list):
        hist = []

    from agent_loop import autonomous_run

    try:
        _prog_on = bool(_worker_cfg.get("background_progress_stream_enabled", True))

        def _emit_bg_progress(ev: dict) -> None:
            try:
                line = json.dumps({"type": "progress", **ev}, default=str, ensure_ascii=False)
                print(line, file=sys.stderr, flush=True)
            except Exception:
                pass

        _prog_cb = _emit_bg_progress if _prog_on else None

        def _effective_allows_job() -> tuple[bool, bool]:
            aw = bool(job.get("allow_write"))
            ar = bool(job.get("allow_run"))
            if bool(_worker_cfg.get("planning_strict_mode")):
                apid = str(job.get("active_plan_id") or "").strip()
                if not apid or not job.get("plan_approved"):
                    return False, False
            return aw, ar

        def _run_once() -> dict:
            aw, ar = _effective_allows_job()
            fpid = str(job.get("file_plan_id") or "").strip()
            if fpid:
                from services.engine_plans import run_plan_iteration

                pl = dict(job)
                pl["allow_write"] = aw
                pl["allow_run"] = ar
                pl["conversation_history"] = hist
                pl["client_abort_event"] = None
                pl["background_progress_callback"] = _prog_cb
                return run_plan_iteration(
                    str(job.get("workspace_root") or ""),
                    fpid,
                    planning_strict_mode=bool(_worker_cfg.get("planning_strict_mode")),
                    payload=pl,
                )
            return autonomous_run(
                str(job.get("goal") or ""),
                context=str(job.get("context") or ""),
                workspace_root=str(job.get("workspace_root") or ""),
                allow_write=aw,
                allow_run=ar,
                conversation_history=hist,
                aspect_id=str(job.get("aspect_id") or ""),
                show_thinking=bool(job.get("show_thinking", False)),
                priority=int(job.get("schedule_priority", 2)),
                persona_focus=str(job.get("persona_focus") or "").strip(),
                conversation_id=str(job.get("conversation_id") or "").strip(),
                cognition_workspace_roots=job.get("cognition_workspace_roots")
                if isinstance(job.get("cognition_workspace_roots"), list)
                else None,
                client_abort_event=None,
                background_progress_callback=_prog_cb,
                active_plan_id=str(job.get("active_plan_id") or ""),
                plan_approved=bool(job.get("plan_approved")),
            )

        continuous = bool(job.get("continuous"))
        max_iter = max(1, min(500, int(job.get("max_iterations") or 20)))
        delay_s = max(0.0, float(job.get("iteration_delay_seconds") or 1.0))

        if continuous:
            wr = str(job.get("workspace_root") or "").strip()
            root = Path(wr).expanduser().resolve() if wr else None
            if str(job.get("file_plan_id") or "").strip():
                from services.engine_plans import run_file_plan_background_loop

                pl = dict(job)
                pl["conversation_history"] = hist
                result = run_file_plan_background_loop(
                    str(job.get("task_id") or ""),
                    pl,
                    None,
                    _prog_cb,
                    max_iter,
                    delay_s,
                )
            else:
                from services.project_memory import load_project_memory

                aggregate_steps: list = []
                result = {}
                completed_iterations = 0
                for i in range(max_iter):
                    if _prog_cb:
                        _prog_cb(
                            {
                                "phase": "continuous",
                                "iteration": i,
                                "max_iterations": max_iter,
                                "message": f"continuous iteration {i + 1}/{max_iter}",
                            }
                        )
                    result = _run_once()
                    completed_iterations += 1
                    for s in result.get("steps") or []:
                        if isinstance(s, dict):
                            aggregate_steps.append(s)
                    if len(aggregate_steps) > 500:
                        aggregate_steps = aggregate_steps[-500:]
                    if result.get("status") == "client_abort":
                        break
                    if root is not None and root.is_dir():
                        try:
                            mem = load_project_memory(root)
                            if isinstance(mem, dict):
                                pst = (mem.get("plan") or {}).get("status")
                                if pst in ("done", "blocked"):
                                    break
                        except Exception:
                            pass
                    if i < max_iter - 1 and delay_s > 0:
                        time.sleep(delay_s)
                result = dict(result)
                result["continuous_iterations"] = completed_iterations
                result["steps"] = aggregate_steps[-300:] if aggregate_steps else result.get("steps", [])
        else:
            result = _run_once()
    except Exception as e:
        logger.exception("autonomous_run failed")
        err = {"ok": False, "error": "worker_exception", "detail": str(e)}
        print(json.dumps(err, ensure_ascii=False), flush=True)
        return 2

    # Serializable snapshot for parent (full steps may be large; parent may cap read)
    payload = {
        "ok": True,
        "status": result.get("status"),
        "response": result.get("response"),
        "steps": result.get("steps"),
        "aspect": result.get("aspect"),
        "aspect_name": result.get("aspect_name"),
        "reasoning_mode": result.get("reasoning_mode"),
        "refused": result.get("refused"),
        "refusal_reason": result.get("refusal_reason"),
        "memory_influenced": result.get("memory_influenced"),
        "ux_states": result.get("ux_states"),
        "continuous_iterations": result.get("continuous_iterations"),
    }
    print(json.dumps(payload, default=str, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

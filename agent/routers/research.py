"""Research mission and read-only research endpoints. Mounted at / by main."""
import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import (
    autonomous_run,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)
from layla.time_utils import utcnow
from research_lab import (
    AGENT_DIR,
    RESEARCH_BRAIN,
    RESEARCH_LAB_WORKSPACE,
    RESEARCH_OUTPUT,
    copy_source_to_lab,
    default_mission_state,
    ensure_research_lab_dirs,
    get_allowed_brain_files,
    get_default_output_structure,
    load_mission_preset,
)
from shared_state import get_append_history, get_history, get_touch_activity

logger = logging.getLogger("layla")
router = APIRouter(tags=["research"])

_RESEARCH_PREFIX = (
    "Research mode: only read and analyze. Do not modify any files or run any commands. "
    "Use read_file, list_dir, grep_code, glob_files, git_status, git_log, git_diff as needed. "
    "Then answer the user's question.\n\nUser request: "
)


@router.post("/research_mission")
async def research_mission(request: Request):
    try:
        req = await request.json()
    except Exception:
        req = {}
    response_text = ""
    result = {}
    stages_to_run = []
    report_format = "technical_report"
    try:
        get_touch_activity()()
        _history = get_history()
        _wr = (req or {}).get("workspace_root") if isinstance(req, dict) else None
        workspace_root = (_wr.strip() if isinstance(_wr, str) else "") or ""
        mission_type = (req or {}).get("mission_type", "repo_analysis") if isinstance(req, dict) else "repo_analysis"
        mission_type = (mission_type or "repo_analysis").strip() or "repo_analysis"
        _ctx = (req or {}).get("context") if isinstance(req, dict) else None
        context = (_ctx if isinstance(_ctx, str) else "") or ""
        report_format = ((req or {}).get("report_format") or "technical_report").strip() if isinstance(req, dict) else "technical_report"
        raw_depth = (req or {}).get("mission_depth") if isinstance(req, dict) else None
        if raw_depth is not None and isinstance(raw_depth, str):
            raw_depth = raw_depth.strip().lower()
        if raw_depth in ("map", "deep", "full"):
            mission_depth = raw_depth
        else:
            mission_depth = None
        next_stage = bool((req or {}).get("next_stage", False)) if isinstance(req, dict) else False

        lab_workspace = None
        if workspace_root:
            lab_workspace = copy_source_to_lab(workspace_root)
        if not lab_workspace:
            ensure_research_lab_dirs()
            lab_workspace = str(RESEARCH_LAB_WORKSPACE)
        Path(lab_workspace).mkdir(parents=True, exist_ok=True) if lab_workspace else None

        stages_to_run = []
        if mission_depth is not None:
            from research_stages import (
                STAGE_RUNNERS,
                ensure_research_brain_dirs,
                load_mission_state,
                save_mission_state,
                stages_for_depth,
            )
            ensure_research_brain_dirs()
            stages_to_run = stages_for_depth(mission_depth, next_stage)
            if not (AGENT_DIR / ".research_brain" / "mission_state.json").exists():
                save_mission_state({"stage": None, "progress": {}, "completed": []})

        max_mission_runtime_seconds = 14400
        if stages_to_run:
            from research_stages import load_mission_state, save_mission_state
            if not next_stage:
                # Fresh mission: reset state
                save_mission_state({"stage": None, "progress": {}, "completed": []})
            # else: preserve existing state so completed stages are not re-run
            conv = list(_history)
            combined_md = []
            result = {"steps": [], "status": "finished"}
            start_time = time.time()
            consecutive_no_progress = 0
            mission_status = "complete"
            for stage_name in stages_to_run:
                if time.time() - start_time > max_mission_runtime_seconds:
                    mission_status = "stopped"
                    try:
                        inc_path = AGENT_DIR / ".research_brain" / "strategic" / "incomplete.md"
                        inc_path.parent.mkdir(parents=True, exist_ok=True)
                        _state = load_mission_state()
                        _done = _state.get("completed") or []
                        inc_path.write_text(
                            f"Mission stopped: runtime limit ({max_mission_runtime_seconds}s) reached.\n"
                            f"Completed stages: {_done}\n"
                            f"Time: {utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    break
                runner = STAGE_RUNNERS.get(stage_name)
                if not runner:
                    continue
                res = await runner(
                    lab_workspace=lab_workspace,
                    context=context,
                    conversation_history=conv,
                    stage_name=stage_name,
                )
                if len(res) == 3:
                    md, _, status = res
                else:
                    md, _ = res
                    status = "ok"
                combined_md.append(f"## {stage_name.title()}\n\n{md or '(no output)'}")
                if status == "no_progress":
                    consecutive_no_progress += 1
                    if consecutive_no_progress >= 2:
                        mission_status = "partial"
                        break
                else:
                    consecutive_no_progress = 0
            response_text = "\n\n---\n\n".join(combined_md) if combined_md else ""
            if not response_text and mission_depth is not None:
                response_text = "No stage output this run. See .research_brain/ for prior outputs."
            state = load_mission_state()
            state["last_run"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            state["completed"] = state.get("completed") or []
            state["status"] = mission_status
            save_mission_state(state)
        else:
            preset = load_mission_preset(mission_type)
            objective = preset.get("objective", "Research the repository.")
            output_parts = preset.get("output_structure", [])
            if not output_parts:
                output_instruction = get_default_output_structure()
            else:
                output_instruction = "Produce: " + ", ".join(output_parts) + "."

            goal = (
                "Research mission (sandbox). Source code is in source_copy/. "
                "You may write only inside .research_lab (e.g. notes/, experiments/). "
                "You may run Python only with cwd inside .research_lab. "
                "Use read_file, list_dir, grep_code, fetch_url as needed. "
                f"Objective: {objective} "
                f"{output_instruction}\n\n"
                "Do not modify anything outside .research_lab.\n\n"
                "This is an autonomous mission.\n"
                "Do not ask follow-up questions.\n"
                "Do not return partial exploration.\n"
                "Continue working until ALL of the following sections are produced:\n"
                "- System Understanding\n"
                "- Weakness Map\n"
                "- Upgrade Opportunities\n"
                "- Lens Case Study\n"
                "- Suggested Roadmap\n\n"
                "The mission is not complete until these sections exist."
            )

            result = await asyncio.to_thread(
                autonomous_run,
                goal,
                context=context,
                workspace_root=lab_workspace,
                allow_write=True,
                allow_run=True,
                conversation_history=list(_history),
                aspect_id="",
                show_thinking=False,
                stream_final=False,
                research_mode=True,
            )

            steps = result.get("steps") or []
            final = steps[-1].get("result", "") if steps else ""
            response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
            if not response_text and result.get("status") == "system_busy":
                response_text = "System is under load. Try again in a moment."
            elif not response_text and result.get("status") == "timeout":
                response_text = "Request took too long."

        citations = {}
        report = ""
        if response_text:
            out_dir = RESEARCH_OUTPUT
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                from services.research_report import extract_citations, format_research_report

                citations = extract_citations(result if isinstance(result, dict) else {}, text_fallback=response_text)
                report = format_research_report(
                    response_text,
                    (result.get("steps") or []) if isinstance(result, dict) else [],
                    report_format,
                    title=f"Research mission ({mission_type})",
                    citations=citations,
                )
                out_dir.joinpath("last_research_raw.md").write_text(
                    f"# Research mission ({mission_type}) — raw\n\n**Workspace:** {workspace_root or 'lab only'}\n\n---\n\n{response_text}",
                    encoding="utf-8",
                )
                out_dir.joinpath("last_research.md").write_text(report, encoding="utf-8")
                ts = utcnow().strftime("%Y%m%d_%H%M%S")
                out_dir.joinpath(f"research_{ts}.md").write_text(
                    report,
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning("save research mission output failed: %s", e)

        # Layla v3: maturity XP for completing a research mission (best-effort).
        if response_text:
            try:
                from services.maturity_engine import award_xp

                award_xp(50, reason=f"research_mission:{(mission_type or 'mission')[:60]}")
            except Exception:
                pass

        return JSONResponse({
            "response": response_text,
            "report": report or response_text,
            "citations": citations,
            "report_format": report_format,
            "state": result,
            "mission_type": mission_type,
            "workspace_root": workspace_root,
            "lab_workspace": lab_workspace,
            "mission_depth": mission_depth if stages_to_run else None,
            "stages_run": stages_to_run if stages_to_run else None,
        })
    except Exception as e:
        logger.exception("research_mission failed: %s", e)
        _r = req or {}
        _w = _r.get("workspace_root") if isinstance(_r, dict) else None
        _err_workspace = (_w.strip() if isinstance(_w, str) else "") or ""
        return JSONResponse({
            "response": "Research mission failed: " + str(e),
            "error": str(e),
            "state": result,
            "mission_type": (_r.get("mission_type") or "repo_analysis") if isinstance(_r, dict) else "repo_analysis",
            "workspace_root": _err_workspace,
            "lab_workspace": "",
            "mission_depth": _r.get("mission_depth") if isinstance(_r, dict) else None,
            "stages_run": None,
        }, status_code=500)


@router.get("/research_mission/state")
def research_mission_state():
    default = default_mission_state()
    path = RESEARCH_BRAIN / "mission_state.json"
    if not path.exists():
        return JSONResponse(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        out = dict(default)
        out["stage"] = data.get("stage") if "stage" in data else default["stage"]
        out["completed"] = data.get("completed") if isinstance(data.get("completed"), list) else default["completed"]
        out["status"] = data.get("status") if data.get("status") is not None else default["status"]
        out["last_run"] = data.get("last_run") if data.get("last_run") is not None else default["last_run"]
        if isinstance(data.get("progress"), dict):
            out["progress"] = data["progress"]
        return JSONResponse(out)
    except Exception:
        return JSONResponse(default)


@router.get("/research_output/last")
def research_output_last():
    path = RESEARCH_OUTPUT / "last_research.md"
    if not path.exists():
        return JSONResponse({"content": ""})
    try:
        return JSONResponse({"content": path.read_text(encoding="utf-8")})
    except Exception:
        return JSONResponse({"content": ""})


@router.get("/research_brain/file")
def research_brain_file(path: str = ""):
    if path not in get_allowed_brain_files():
        return JSONResponse({"content": ""}, status_code=400)
    full = RESEARCH_BRAIN / path
    if not full.exists():
        return JSONResponse({"content": ""})
    try:
        return JSONResponse({"content": full.read_text(encoding="utf-8")})
    except Exception:
        return JSONResponse({"content": ""})


@router.get("/research_mission/debug")
def research_mission_debug():
    mission_state_exists = (RESEARCH_BRAIN / "mission_state.json").exists()
    brain_exists = RESEARCH_BRAIN.exists()
    last_stage = None
    completed_count = 0
    if mission_state_exists:
        try:
            data = json.loads((RESEARCH_BRAIN / "mission_state.json").read_text(encoding="utf-8"))
            last_stage = data.get("stage")
            completed_count = len(data.get("completed") or [])
        except Exception:
            pass
    try:
        from research_stages import STAGE_RUNNERS
        stages_available = list(STAGE_RUNNERS.keys())
    except Exception:
        stages_available = []
    return JSONResponse({
        "mission_state_exists": mission_state_exists,
        "brain_exists": brain_exists,
        "stages_available": stages_available,
        "last_stage": last_stage,
        "completed_count": completed_count,
    })


@router.get("/research_mission/verify")
def research_mission_verify():
    state_path = RESEARCH_BRAIN / "mission_state.json"
    map_path = RESEARCH_BRAIN / "maps" / "system_map.json"
    last_path = RESEARCH_OUTPUT / "last_research.md"
    state_ok = state_path.exists()
    map_ok = map_path.exists()
    last_ok = last_path.exists()
    completed_count = 0
    completed_list = []
    if state_ok:
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            completed_list = data.get("completed") or []
            completed_count = len(completed_list)
        except Exception:
            pass
    mapping_done = "mapping" in completed_list
    pipeline_ready = state_ok and last_ok and (not mapping_done or map_ok)
    message = (
        "MISSION PIPELINE READY FOR 24H AUTONOMOUS RUN"
        if pipeline_ready
        else "Pipeline not ready: run a mission first (map/deep/full) and ensure mission_state.json, last_research.md exist."
    )
    return JSONResponse({
        "pipeline_ready": pipeline_ready,
        "message": message,
        "mission_state.json": state_ok,
        "maps/system_map.json": map_ok,
        "last_research.md": last_ok,
        "completed_stages": completed_count,
    })


@router.post("/research")
async def research(req: dict):
    get_touch_activity()()
    _history = get_history()
    _append_history = get_append_history()
    raw_message = (req or {}).get("message", "").strip()
    repo_path = (req or {}).get("repo_path", "") or (req or {}).get("workspace_root", "") or ""
    aspect_id = (req or {}).get("aspect_id", "") or ""
    show_thinking = bool((req or {}).get("show_thinking", False))
    stream = bool((req or {}).get("stream", False))
    report_format = ((req or {}).get("report_format") or "technical_report").strip()
    goal = (_RESEARCH_PREFIX + raw_message) if raw_message else "Research mode: explore the workspace (read-only) and summarize what you find."
    context = (req or {}).get("context", "") or ""

    result = await asyncio.to_thread(
        autonomous_run,
        goal,
        context=context,
        workspace_root=repo_path,
        allow_write=False,
        allow_run=False,
        conversation_history=list(_history),
        aspect_id=aspect_id,
        show_thinking=show_thinking,
        stream_final=stream,
        research_mode=True,
    )

    if stream and result.get("status") == "stream_pending":
        goal_for_stream = result.get("goal_for_stream", goal)

        def gen():
            full = []
            try:
                for token in stream_reason(
                    goal_for_stream,
                    context=context,
                    conversation_history=list(_history),
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    skip_self_reflection=(result.get("reasoning_mode") or "light") in ("none", "light"),
                ):
                    full.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                text = truncate_at_next_user_turn(strip_junk_from_reply("".join(full)))
                report = ""
                citations = {}
                try:
                    from services.research_report import extract_citations, format_research_report

                    citations = extract_citations(result, text_fallback=text)
                    report = format_research_report(
                        text,
                        (result.get("steps") or []) if isinstance(result, dict) else [],
                        report_format,
                        title="Research output",
                        citations=citations,
                    )
                except Exception:
                    report = ""
                    citations = {}
                _append_history("user", raw_message or "Research this repo.")
                _append_history("assistant", report or text)
                if text:
                    try:
                        out_dir = RESEARCH_OUTPUT
                        out_dir.mkdir(parents=True, exist_ok=True)
                        out_dir.joinpath("last_research_raw.md").write_text(
                            f"# Research output — raw\n\n**Request:** {raw_message[:200]}...\n\n---\n\n{text}",
                            encoding="utf-8",
                        )
                        out_dir.joinpath("last_research.md").write_text(
                            report or text,
                            encoding="utf-8",
                        )
                        ts = utcnow().strftime("%Y%m%d_%H%M%S")
                        out_dir.joinpath(f"research_{ts}.md").write_text(
                            report or text,
                            encoding="utf-8",
                        )
                    except Exception as e:
                        logger.debug("save research output failed: %s", e)
                yield f"data: {json.dumps({'done': True, 'content': text, 'report': report or text, 'citations': citations, 'report_format': report_format, 'reasoning_mode': result.get('reasoning_mode')})}\n\n"
            except Exception as e:
                logger.exception("stream_reason failed")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    steps = result.get("steps") or []
    final = steps[-1].get("result", "") if steps else ""
    response_text = final if isinstance(final, str) else json.dumps(final) if final else ""
    if not response_text and result.get("status") == "system_busy":
        response_text = "System is under load. Try again in a moment."
    elif not response_text and result.get("status") == "timeout":
        response_text = "Request took too long. Try a shorter message or try again."

    _append_history("user", raw_message or "Research this repo.")
    citations = {}
    report = ""
    if result.get("status") in ("system_busy", "timeout") and response_text:
        _append_history("assistant", "I couldn't reply just then.")
    else:
        try:
            from services.research_report import extract_citations, format_research_report

            citations = extract_citations(result, text_fallback=response_text)
            report = format_research_report(
                response_text,
                (result.get("steps") or []) if isinstance(result, dict) else [],
                report_format,
                title="Research output",
                citations=citations,
            )
        except Exception:
            citations = {}
            report = ""
        _append_history("assistant", report or response_text)

    if response_text and result.get("status") not in ("system_busy", "timeout"):
        try:
            out_dir = RESEARCH_OUTPUT
            out_dir.mkdir(parents=True, exist_ok=True)
            out_dir.joinpath("last_research_raw.md").write_text(
                f"# Research output — raw\n\n**Request:** {raw_message[:200]}...\n\n---\n\n{response_text}",
                encoding="utf-8",
            )
            out_dir.joinpath("last_research.md").write_text(
                report or response_text,
                encoding="utf-8",
            )
            ts = utcnow().strftime("%Y%m%d_%H%M%S")
            out_dir.joinpath(f"research_{ts}.md").write_text(
                report or response_text,
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("save research output failed: %s", e)

    return JSONResponse({
        "response": response_text,
        "report": report or response_text,
        "citations": citations,
        "report_format": report_format,
        "state": result,
        "aspect": result.get("aspect", ""),
        "aspect_name": result.get("aspect_name", "Layla"),
        "ux_states": result.get("ux_states", []),
        "memory_influenced": result.get("memory_influenced", []),
        "reasoning_mode": result.get("reasoning_mode"),
    })

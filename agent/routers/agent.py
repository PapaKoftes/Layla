"""Agent and learn endpoints. Mounted at / by main."""
import asyncio
import base64
import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent_loop import (
    _quick_reply_for_trivial_turn,
    stream_reason,
    strip_junk_from_reply,
    truncate_at_next_user_turn,
)
from schemas.requests import AgentRequest, SteerRequest
from services.infrastructure.output_polish import polish_output
from services.infrastructure.resource_manager import PRIORITY_CHAT, classify_load
from shared_state import (
    append_conv_history,
    get_append_history,
    get_conv_history,
    get_history,
    get_touch_activity,
)

logger = logging.getLogger("layla")
router = APIRouter(tags=["agent"])


def _dispatch_autonomous_run(goal, **kwargs):
    """Late-bind to agent_loop.autonomous_run; coordinator.run is the outer HTTP entry (resume, worktree, consolidation)."""
    import agent_loop as _al
    from services.planning.coordinator import run as coordinator_run

    return coordinator_run(_al.autonomous_run, goal, **kwargs)


async def _watch_client_disconnect(http_request: Request, ev: threading.Event) -> None:
    """Set ev when the HTTP client disconnects (streaming /agent only)."""
    try:
        while not ev.is_set():
            if await http_request.is_disconnected():
                ev.set()
                return
            await asyncio.sleep(0.2)
    except Exception:
        return


from services.infrastructure.agent_task_runner import (
    _build_reasoning_tree_summary,
    _compute_background_job_sandbox,
    _json_safe,
    _resolve_plan_binding_from_request,
    _run_background_subprocess_task,
    enqueue_threaded_autonomous,
)
from services.infrastructure.resource_manager import PRIORITY_BACKGROUND

from .learn import router as _learn_router

router.include_router(_learn_router)
# NOTE: agent_tasks is mounted once, directly in main.py (app.include_router). Do not
# also self-include it here or its routes register twice (duplicate-route hazard).


def _get_image_context(image_url: str = "", image_base64: str = "", workspace_root: str = "") -> str:
    """
    Process attached image: fetch or decode, run describe_image/ocr_image, return context string.
    Returns empty string on failure. Saves temp file inside sandbox so tools accept it.
    """
    tmp_path = None
    try:
        try:
            import runtime_safety
            sandbox = Path(runtime_safety.load_config().get("sandbox_root", str(Path.home()))).expanduser().resolve()
        except Exception:
            sandbox = Path.home()
        if workspace_root:
            sandbox = Path(workspace_root).expanduser().resolve()
        tmp_dir = sandbox / ".layla_temp_images"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        if image_base64:
            data = image_base64
            if "," in data:
                data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
            ext = ".png"
            if image_base64.startswith("data:image/jpeg") or image_base64.startswith("data:image/jpg"):
                ext = ".jpg"
            elif image_base64.startswith("data:image/webp"):
                ext = ".webp"
            elif image_base64.startswith("data:image/gif"):
                ext = ".gif"
            import uuid
            tmp_path = str(tmp_dir / f"img_{uuid.uuid4().hex[:12]}{ext}")
            Path(tmp_path).write_bytes(raw)
        elif image_url and image_url.startswith("http"):
            import urllib.request
            import uuid
            # SSRF mitigation: only http/https, block private/localhost
            try:
                from urllib.parse import urlparse
                parsed = urlparse(image_url)
                if parsed.scheme not in ("http", "https"):
                    raise ValueError("Invalid scheme")
                host = (parsed.hostname or "").lower()
                if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                    raise ValueError("Private host blocked")
                if host.startswith("127.") or host.startswith("10.") or host.startswith("169.254.") or host.startswith("192.168."):
                    raise ValueError("Private host blocked")
                if host.startswith("172."):
                    parts = host.split(".")
                    if len(parts) >= 2:
                        try:
                            b = int(parts[1])
                        except ValueError:
                            b = -1
                        if 16 <= b <= 31:
                            raise ValueError("Private host blocked")
            except Exception as e:
                logger.debug("image_url validation failed: %s", e)
            else:
                tmp_path = str(tmp_dir / f"img_{uuid.uuid4().hex[:12]}.png")
                with urllib.request.urlopen(image_url, timeout=15) as resp:
                    Path(tmp_path).write_bytes(resp.read())
        if not tmp_path or not Path(tmp_path).exists():
            return ""
        from layla.tools.registry import TOOLS
        desc = TOOLS.get("describe_image", {}).get("fn")
        ocr = TOOLS.get("ocr_image", {}).get("fn")
        caption = ""
        if desc:
            try:
                r = desc(path=tmp_path, detail="brief")
                if isinstance(r, dict) and r.get("ok"):
                    caption = (r.get("caption") or "").strip()
                    if r.get("ocr_text", "").strip():
                        caption += f" [OCR text: {r['ocr_text'][:300]}]"
            except Exception as e:
                logger.debug("describe_image failed: %s", e)
        if not caption and ocr:
            try:
                r = ocr(path=tmp_path, lang="eng")
                if isinstance(r, dict) and r.get("ok"):
                    caption = (r.get("text") or "").strip()[:500]
            except Exception as e:
                logger.debug("ocr_image failed: %s", e)
        if caption:
            return f"[Image context: {caption}]"
    except Exception as e:
        logger.debug("image context failed: %s", e)
    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass
    return ""


def _extract_artifacts(text: str) -> list[dict]:
    """
    Parse markdown code blocks from a response string into artifact dicts.
    Returns: [{id, lang, content, lines}]  (max 20 artifacts, >2 lines each)
    """
    import hashlib
    import re
    artifacts = []
    # Line-based fence scan (replaces a greedy `\`\`\`(\w*)\n...\`\`\`` regex that: dropped blocks
    # whose fence carried an info string like "\`\`\`python title=x" because `\w*` stopped at the
    # space before the required `\n`; dropped the final block when a max_tokens-truncated reply left
    # an UNCLOSED trailing fence; and paired a stray mid-prose fence with a later block's close by
    # matching `\`\`\`` anywhere. The close is now required on its OWN line).
    src_lines = (text or "").split("\n")
    n = len(src_lines)
    i = 0
    while i < n and len(artifacts) < 20:
        m = re.match(r"^\s*(```+|~~~+)(.*)$", src_lines[i])   # ``` or ~~~ (CommonMark both fence chars)
        if not m:
            i += 1
            continue
        _fence = m.group(1)[0]   # the fence CHAR ('`' or '~'); close must use the SAME char
        info = (m.group(2) or "").strip()
        lang = (info.split()[0] if info else "text") or "text"   # first token of the info string
        body: list[str] = []
        j = i + 1
        closed = False
        while j < n:
            if re.match(rf"^\s*{re.escape(_fence)}{{3,}}\s*$", src_lines[j]):   # bare close, same fence char
                closed = True
                break
            body.append(src_lines[j])
            j += 1
        content = "\n".join(body)
        if closed and body:
            content += "\n"  # the newline that preceded the closing fence (parity with the old capture)
        if content.strip():
            n_lines = content.rstrip("\n").count("\n") + 1
            if n_lines >= 2:  # skip trivial one-liners
                art = {
                    "id": "art_" + hashlib.md5(content.encode()).hexdigest()[:8],
                    "lang": lang,
                    "content": content,
                    "lines": n_lines,
                }
                if not closed:
                    art["truncated"] = True   # reply cut at max_tokens before the closing fence
                artifacts.append(art)
        i = (j + 1) if closed else n
    return artifacts


def _aspect_extra_names(result) -> tuple:
    """The active aspect's display name (for a CUSTOM aspect this is the operator-chosen name),
    so strip_junk_from_reply also strips a leading 'CustomName:' speaker label — the built-in name
    list only covers the six stock aspects. Built-in names are already covered, so passing them is
    harmless; 'Layla' is always in the base set."""
    try:
        n = str((result or {}).get("aspect_name") or "").strip()
        return (n,) if n and n.lower() != "layla" else ()
    except Exception:
        return ()


def _model_ready_message() -> str | None:
    """Return error message if model/LLM is not ready, else None."""
    try:
        from services.llm.llm_gateway import model_loaded_status
        status = model_loaded_status()
        err = status.get("error")
        if err:
            return f"Model not ready: {err}. Run python agent/first_run.py or configure runtime_config.json. See MODELS.md."
    except Exception:
        pass
    return None


def _no_model_response(message: str) -> JSONResponse:
    """Standard shape when no GGUF / remote model is configured (UI opens setup)."""
    return JSONResponse(
        {
            "error": "no_model",
            "action": "open_setup",
            "response": message,
            "state": {"status": "no_model", "steps": []},
            "aspect": "",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
        },
        status_code=503,
    )


def _maybe_synth_title(conversation_id: str, user_msg: str, assistant_text: str) -> None:
    """On the FIRST exchange, async-polish the auto title into an LLM-synthesized topic name.

    Non-blocking (background thread) so it never adds latency to the reply — the instant
    extractive title from _auto_name_conversation already shows in the rail; this replaces it
    with a crisper name that lands on the next rail refresh. Flag-gated; safe no-op on failure.
    """
    cid = (conversation_id or "").strip()
    if not cid or not (user_msg or "").strip():
        return
    try:
        import runtime_safety
        if not runtime_safety.load_config().get("conversation_title_synthesis_enabled", True):
            return
        from layla.memory.db import get_conversation
        conv = get_conversation(cid) or {}
        # first exchange only (user + assistant just persisted → count ~2); don't clobber later
        if int(conv.get("message_count") or 0) > 2:
            return

        def _bg() -> None:
            try:
                from services.agent.title_synthesizer import synthesize_conversation_title
                t = synthesize_conversation_title(user_msg, assistant_text)
                if t:
                    from layla.memory.db import rename_conversation
                    rename_conversation(cid, t)
            except Exception as _tx:
                logger.debug("title synth bg failed: %s", _tx)

        threading.Thread(target=_bg, daemon=True, name="title-synth").start()
    except Exception as _te:
        logger.debug("title synth gate failed: %s", _te)


def _mem_receipt(user_msg: str) -> str:
    """Persist any durable fact the user stated this turn; return a receipt for the done-frame.

    Fast (regex only) so it's fine synchronously in the done-path. Powers the 'memory updated'
    chip and makes the durable fact show up in the About-you panel. Flag-gated; '' on nothing.
    """
    try:
        import runtime_safety
        if not runtime_safety.load_config().get("identity_capture_enabled", True):
            return ""
        from services.memory.identity_extractor import capture_identity_from_turn
        return capture_identity_from_turn(user_msg or "")
    except Exception as _me:
        logger.debug("identity capture failed: %s", _me)
        return ""


@router.get("/agent/decision_trace")
def get_decision_trace(conversation_id: str = "default"):
    """Last run decision policy trace (caps + tool samples) for debugging."""
    from shared_state import get_last_decision_trace

    return {"ok": True, "conversation_id": conversation_id, "trace": get_last_decision_trace(conversation_id) or []}


@router.post("/agent/steer")
def agent_steer(req: SteerRequest):
    """Queue a short operator redirect for the in-flight run on this conversation (next decision tick)."""
    get_touch_activity()()
    hint = req.effective_hint()
    conversation_id = (req.conversation_id or "").strip()
    if not hint:
        return JSONResponse({"ok": False, "error": "hint required"}, status_code=400)
    from shared_state import push_agent_steer_hint

    push_agent_steer_hint(conversation_id, hint)
    return JSONResponse({"ok": True})


@router.post("/agent")
async def agent(req: AgentRequest, request: Request):
    get_touch_activity()()
    _history = get_history()
    _append_history = get_append_history()
    goal = req.message
    context = req.context or ""
    workspace_root = req.workspace_root or ""
    image_url = req.image_url or ""
    image_base64 = req.image_base64 or ""
    allow_write = req.allow_write
    allow_run = req.allow_run
    # A remote caller must not self-grant write/execute via the request body
    # (same guard as /v1). Honored only for a direct local caller; fail-closed.
    try:
        from services.safety.auth import is_direct_local
        if not is_direct_local(request.headers, request.client.host if request.client else None):
            allow_write = False
            allow_run = False
    except Exception:
        allow_write = False
        allow_run = False
    aspect_id = req.aspect_id or ""
    persona_focus = req.effective_persona_focus()
    show_thinking = req.show_thinking
    plan_mode = req.plan_mode
    understand_mode = req.understand_mode
    stream = req.stream
    model_override = req.model_override or ""
    reasoning_effort = "high" if req.reasoning_effort == "high" else None
    conversation_id = (req.conversation_id or "").strip() or str(uuid.uuid4())
    _active_plan_id, _plan_approved_flag = _resolve_plan_binding_from_request(req.plan_id or "")
    conv_history = get_conv_history(conversation_id)
    cfg = {}
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
    except Exception:
        cfg = {}

    try:
        if (workspace_root or "").strip():
            from services.workspace.workspace_awareness import refresh_for_workspace

            refresh_for_workspace(str(workspace_root).strip(), cfg)
    except Exception:
        pass

    _ep_enabled = bool(cfg.get("engineering_pipeline_enabled"))
    _raw_epm = req.engineering_pipeline_mode
    if _raw_epm is None or (isinstance(_raw_epm, str) and not str(_raw_epm).strip()):
        _ep_mode = str(cfg.get("engineering_pipeline_default_mode") or "chat").strip().lower()
    else:
        _ep_mode = str(_raw_epm).strip().lower()
    if _ep_mode not in ("chat", "plan", "execute"):
        _ep_mode = "chat"
    clarification_reply = (req.clarification_reply or "").strip()

    cognition_workspace_roots: list[str] = []
    project_id = (req.project_id or "").strip()
    if project_id:
        try:
            import json as _json

            from layla.memory.db import get_project, set_conversation_project

            pr = get_project(project_id)
            if pr:
                if not (workspace_root or "").strip() and (pr.get("workspace_root") or "").strip():
                    workspace_root = str(pr["workspace_root"]).strip()
                pre = (pr.get("system_preamble") or "").strip()
                if pre:
                    pname = (pr.get("name") or "project").strip()
                    context = f"[Active project: {pname}]\n{pre}\n\n" + (context or "")
                ad = (pr.get("aspect_default") or "").strip()
                if ad and not (aspect_id or "").strip():
                    aspect_id = ad
                ex = (pr.get("cognition_extra_roots") or "").strip()
                if ex:
                    try:
                        parsed = _json.loads(ex)
                        if isinstance(parsed, list):
                            cognition_workspace_roots.extend(
                                str(x).strip() for x in parsed if str(x).strip()
                            )
                    except Exception:
                        pass
            try:
                set_conversation_project(conversation_id, project_id)
            except Exception:
                pass
        except Exception:
            pass
    raw_cog = req.cognition_workspace_roots
    if isinstance(raw_cog, list):
        for x in raw_cog:
            s = str(x).strip()
            if s and s not in cognition_workspace_roots:
                cognition_workspace_roots.append(s)

    # Image context: if user attached image, process and prepend to context
    if image_url or image_base64:
        img_ctx = await asyncio.to_thread(_get_image_context, image_url, image_base64, workspace_root)
        if img_ctx:
            context = (img_ctx + "\n\n" + context).strip() if context else img_ctx

    # Empty message: avoid running the full loop (understand_mode may use workspace only)
    if not (goal or "").strip() and not understand_mode:
        return JSONResponse({
            "response": "Please type a message.",
            "state": {"status": "empty_message", "steps": []},
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
            "conversation_id": conversation_id,
            "load": _json_safe(classify_load()),
        }, status_code=200)

    # Understand mode: deterministic repo map + cognition sync (no full LLM loop)
    if understand_mode:
        if not (workspace_root or "").strip():
            return JSONResponse(
                {"ok": False, "error": "workspace_root required for understand_mode"},
                status_code=400,
            )
        from pathlib import Path

        from layla.tools.registry import inside_sandbox
        from services.memory.project_memory import scan_workspace_into_memory
        from services.workspace.repo_cognition import sync_repo_cognition

        root = Path(str(workspace_root).strip()).expanduser().resolve()
        if not inside_sandbox(root):
            return JSONResponse(
                {"ok": False, "error": "workspace_root outside sandbox"},
                status_code=400,
            )
        idx_sem = req.understand_index_semantic
        mf = int(cfg.get("project_memory_max_file_entries", 500) or 500)
        mb = int(cfg.get("project_memory_max_bytes", 1_500_000) or 1_500_000)

        def _understand_sync() -> tuple[dict, dict]:
            scan = scan_workspace_into_memory(root, dry_run=False, max_files=mf, max_bytes=mb)
            syn = sync_repo_cognition([str(root)], index_semantic=idx_sem)
            return scan, syn

        scan_out, sync_out = await asyncio.to_thread(_understand_sync)
        reply = (goal or "").strip() or "Repository map and cognition snapshot updated."
        return JSONResponse(
            {
                "response": reply,
                "state": {"status": "understand_done", "steps": []},
                "status": "understand_done",
                "aspect": aspect_id or "morrigan",
                "aspect_name": "Layla",
                "refused": False,
                "refusal_reason": "",
                "ux_states": ["understand_done"],
                "memory_influenced": [],
                "cited_sources": [],
                "conversation_id": conversation_id,
                "load": _json_safe(classify_load()),
                "scan_repo": _json_safe(scan_out),
                "sync_repo_cognition": _json_safe(sync_out),
            },
            status_code=200,
        )

    # Plan mode: structured plan without executing (engineering pipeline plan path when enabled)
    _plan_light = _ep_enabled and (plan_mode or _ep_mode == "plan")
    if _plan_light and (goal or "").strip():
        try:
            from services.planning.engineering_pipeline import run_plan_light

            pr = await asyncio.to_thread(
                run_plan_light,
                goal,
                context,
                workspace_root or "",
                conversation_id,
                cfg,
                clarification_reply,
                aspect_id or "morrigan",
            )
            if pr.get("status") == "pipeline_needs_input":
                return JSONResponse({
                    "status": "pipeline_needs_input",
                    "pipeline_status": "needs_input",
                    "questions": pr.get("questions") or [],
                    "response": pr.get("response") or "",
                    "goal": goal,
                    "conversation_id": conversation_id,
                    "aspect": aspect_id or "morrigan",
                    "aspect_name": "Layla",
                    "refused": False,
                    "refusal_reason": "",
                    "ux_states": ["pipeline_needs_input"],
                    "memory_influenced": [],
                    "cited_sources": [],
                    "load": _json_safe(classify_load()),
                })
            return JSONResponse({
                "status": "plan_ready",
                "pipeline_status": pr.get("pipeline_status", "plan_ready"),
                "plan": pr.get("plan"),
                "plan_id": pr.get("plan_id"),
                "plan_steps": pr.get("plan_steps"),
                "goal": goal,
                "response": "",
                "aspect": aspect_id or "morrigan",
                "aspect_name": "Layla",
                "refused": False,
                "refusal_reason": "",
                "ux_states": pr.get("ux_states") or ["plan_ready"],
                "memory_influenced": [],
                "cited_sources": [],
                "load": _json_safe(classify_load()),
            })
        except Exception:
            logger.exception("plan generation failed")
            return JSONResponse({"ok": False, "error": "Plan generation failed. Check the server logs for details."}, status_code=500)

    if plan_mode and (goal or "").strip() and not _ep_enabled:
        try:
            from pathlib import Path

            from layla.tools.registry import inside_sandbox
            from services.memory.project_memory import persist_plan_to_memory
            from services.planning.planner import create_plan

            digest = ""
            if (workspace_root or "").strip():
                try:
                    from services.planning.plan_workspace_store import prior_plans_digest

                    digest = prior_plans_digest(str(workspace_root).strip(), limit=8)
                except Exception:
                    digest = ""
            plan_steps = await asyncio.to_thread(create_plan, goal, 6, cfg, digest)
            from layla.memory.db import create_layla_plan, get_layla_plan
            from services.planning.engine_plans import normalize_planner_steps

            steps_norm = normalize_planner_steps(plan_steps)
            plan_row_id = create_layla_plan(
                goal,
                context=context,
                steps=steps_norm,
                workspace_root=workspace_root or "",
                conversation_id=conversation_id,
                status="draft",
            )
            prow = get_layla_plan(plan_row_id)
            if prow:
                try:
                    from services.planning.plan_workspace_store import mirror_sqlite_plan

                    mirror_sqlite_plan(prow)
                except Exception:
                    pass
            if (workspace_root or "").strip() and cfg.get("project_memory_persist_plan", True):
                try:
                    wrp = Path(str(workspace_root).strip()).expanduser().resolve()
                    if inside_sandbox(wrp):
                        await asyncio.to_thread(persist_plan_to_memory, wrp, goal, plan_steps)
                except Exception:
                    pass
            return JSONResponse({
                "status": "plan_ready",
                "plan": plan_steps,
                "plan_id": plan_row_id,
                "plan_steps": steps_norm,
                "goal": goal,
                "response": "",
                "aspect": aspect_id or "morrigan",
                "aspect_name": "Layla",
                "refused": False,
                "refusal_reason": "",
                "ux_states": ["plan_ready"],
                "memory_influenced": [],
                "cited_sources": [],
            })
        except Exception:
            logger.exception("plan generation failed")
            return JSONResponse({"ok": False, "error": "Plan generation failed. Check the server logs for details."}, status_code=500)

    try:
        from layla.memory.db import save_session_prompt
        save_session_prompt(goal, aspect_id or "morrigan")
    except Exception:
        pass

    # Fast path for trivial greetings/acks: avoid full orchestration overhead.
    fast_reply = _quick_reply_for_trivial_turn(goal)
    if (
        fast_reply
        and not context
        and not image_url
        and not image_base64
        and not show_thinking
        and not (_ep_enabled and _ep_mode in ("plan", "execute"))
    ):
        fast_summary = {
            "mode": "summary_only",
            "goal": (goal or "")[:300],
            "status": "fast_path",
            "reasoning_mode": "none",
            "ux_states": ["fast_path"],
            "nodes": [{"id": "step_1", "phase": "reasoning", "action": "reason", "outcome_summary": (fast_reply or "")[:200]}],
            "final_summary": (fast_reply or "")[:280],
        }
        append_conv_history(conversation_id, "user", goal)
        append_conv_history(conversation_id, "assistant", fast_reply)
        try:
            from layla.memory.db import append_conversation_message, create_conversation

            create_conversation(conversation_id, aspect_id=aspect_id or "morrigan")
            append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id or "morrigan")
            append_conversation_message(conversation_id, "assistant", fast_reply, aspect_id=aspect_id or "morrigan")
            _maybe_synth_title(conversation_id, goal, fast_reply)
        except Exception:
            pass
        _append_history("user", goal)
        _append_history("assistant", fast_reply)
        return JSONResponse({
            "response": fast_reply,
            "state": {
                "status": "fast_path",
                "reasoning_mode": "none",
                "reasoning_tree_summary": fast_summary,
                "steps": [],
            },
            "aspect": aspect_id or "morrigan",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": ["fast_path"],
            "memory_influenced": [],
            "cited_sources": [],
            "reasoning_mode": "none",
            "conversation_id": conversation_id,
            "reasoning_tree_summary": fast_summary,
            "load": _json_safe(classify_load()),
        }, status_code=200)

    cache_enabled = bool(cfg.get("response_cache_enabled", False))
    cache_ttl = int(cfg.get("response_cache_ttl_seconds", 300) or 0)
    cache_max_entries = int(cfg.get("response_cache_max_entries", 300) or 300)
    # The response cache is keyed ONLY on (goal, aspect). A reply generated WITH conversation
    # history is not a pure function of (goal, aspect) — caching it would replay one conversation's
    # context into another that merely repeats the same message text (cross-conversation bleed). So
    # the cache is restricted to STATELESS turns (no prior history); once a conversation has history
    # it is never read from / written to the shared cache.
    _cache_stateless = not conv_history
    # The cache key is ONLY (goal, aspect). Any request field that SHAPES the reply — a per-turn
    # model override, thinking/deliberation mode, persona focus, reasoning effort, research mode —
    # would make the stored payload (its text AND its tool-trace `steps`/reasoning_tree_summary)
    # replay to a later same-goal turn that asked for none of it. Only cache plain default-shaped turns.
    _cache_shaped = bool(model_override) or bool(show_thinking) or bool(persona_focus) or bool(reasoning_effort) or bool(getattr(req, "research_mode", False))
    if (
        cache_enabled
        and _cache_stateless
        and not _cache_shaped
        and not stream
        and not allow_write
        and not allow_run
        and not context
        and not image_url
        and not image_base64
        and not (_ep_enabled and _ep_mode in ("plan", "execute"))
    ):
        try:
            from services.retrieval.response_cache import get_cached_response
            cached = get_cached_response(goal, aspect_id or "morrigan", cache_ttl)
            if cached:
                cached.setdefault("state", {})
                if isinstance(cached["state"], dict):
                    cached["state"]["status"] = "cache_hit"
                    cached["state"].setdefault("steps", [])
                # Re-stamp the CURRENT request's conversation_id — the cached payload carries the
                # original requester's id, which would misattribute this reply to another conversation.
                cached["conversation_id"] = conversation_id
                _append_history("user", goal)
                _append_history("assistant", cached.get("response", ""))
                return JSONResponse(cached, status_code=200)
        except Exception:
            pass

    # Pre-check: model must be ready before we block on a long run
    model_err = _model_ready_message()
    if model_err and goal.strip():
        return _no_model_response(model_err)

    if stream:
        import runtime_safety as _rs_stream

        _cfg_stream = _rs_stream.load_config()
        try:
            _pulse_sec = float(_cfg_stream.get("ui_stream_keepalive_seconds", 20) or 20)
        except (TypeError, ValueError):
            _pulse_sec = 20.0
        if _pulse_sec < 0:
            _pulse_sec = 0.0

        # ── Self-contained Q&A fast-path ──────────────────────────────────────────────
        # A general how-to / explain / code-gen question (no concrete file/repo, no write/exec)
        # is answerable directly. Stream it straight from the reason model and SKIP the whole
        # agentic pipeline (coordinator / planning / tools) — on a small local model that pipeline
        # thrashes to the tool limit and can't stream, so a plain question would otherwise take
        # 60-90s and return "Stopped after maximum tool calls" instead of a direct answer. This is
        # upstream of every planning entry point, so no downstream gate can re-route it.
        _fast_reason = False
        try:
            from services.agent.response_builder import is_self_contained_question as _isq_r
            _fast_reason = bool(
                _isq_r(goal or "")
                and not plan_mode and not understand_mode
                and not show_thinking  # thinking mode = deliberation; use the full pipeline
                and not (workspace_root or "").strip()
                and not allow_write and not allow_run
                and not (clarification_reply or "").strip()
                and not (req.project_id or "").strip()
                and (_ep_mode == "chat")
            )
        except Exception:
            _fast_reason = False

        if _fast_reason:
            _client_abort_fast = threading.Event()

            async def agen_fast():
                watch_task = asyncio.create_task(_watch_client_disconnect(request, _client_abort_fast))
                try:
                    yield f"data: {json.dumps({'ux_state': 'thinking'})}\n\n"
                    try:
                        from services.llm.llm_gateway import model_is_loaded
                        if not model_is_loaded():
                            yield f"data: {json.dumps({'ux_state': 'loading_model'})}\n\n"
                    except Exception:
                        pass
                    from services.agent.response_builder import stream_safe_prefix
                    tok_q: queue.Queue = queue.Queue()
                    full: list = []
                    _emitted = 0
                    _fast_delib_meta = None

                    def _worker() -> None:
                        try:
                            for t in stream_reason(
                                goal,
                                context=context,
                                conversation_history=list(conv_history) if conv_history else list(_history),
                                aspect_id=aspect_id,
                                show_thinking=show_thinking,
                                model_override=model_override or None,
                                skip_self_reflection=True,
                                reasoning_mode_override="light",
                                persona_focus=persona_focus or "",
                            ):
                                tok_q.put(t)
                        except Exception as ex:
                            logger.warning("fast stream_reason worker: %s", ex)
                        finally:
                            tok_q.put(None)

                    threading.Thread(target=_worker, daemon=True).start()
                    _empty = object()
                    _last = time.monotonic()
                    while True:
                        def _get():
                            try:
                                return tok_q.get(timeout=0.25)
                            except queue.Empty:
                                return _empty
                        got = await asyncio.to_thread(_get)
                        if got is _empty:
                            if _pulse_sec > 0 and (time.monotonic() - _last) >= _pulse_sec:
                                yield f"data: {json.dumps({'pulse': True})}\n\n"
                                _last = time.monotonic()
                            continue
                        if got is None:
                            break
                        _last = time.monotonic()
                        # Intercept the deliberation trace marker (reaches the fast path only
                        # when the always-on deliberation_enabled flag is set) so the thinking
                        # trace still renders instead of being silently dropped.
                        if isinstance(got, str) and got.startswith("__DELIB_META__"):
                            try:
                                _dm_json = got.split("__DELIB_META__")[1].split("__DELIB_END__")[0]
                                _fast_delib_meta = json.loads(_dm_json)  # noqa: F841 — used in done frame
                                yield f"data: {json.dumps({'deliberation': _fast_delib_meta})}\n\n"
                            except Exception:
                                pass
                            continue
                        full.append(got)
                        # Stream only marker-safe text: hold back an unclosed "[" and strip any
                        # complete [MARKER …] so control tags never flash mid-stream.
                        _delta, _emitted = stream_safe_prefix("".join(full), _emitted)
                        if _delta:
                            yield f"data: {json.dumps({'token': _delta})}\n\n"
                    text = polish_output(truncate_at_next_user_turn(strip_junk_from_reply("".join(full))), cfg)
                    if not text.strip():
                        text = "Sorry — I couldn't generate a response just then. Please try again."
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", text)
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    try:
                        from layla.memory.db import append_conversation_message, create_conversation
                        create_conversation(conversation_id, aspect_id=aspect_id or "")
                        append_conversation_message(conversation_id, "user", goal, aspect_id=aspect_id or "")
                        append_conversation_message(conversation_id, "assistant", text, aspect_id=aspect_id or "")
                        _maybe_synth_title(conversation_id, goal, text)
                    except Exception:
                        pass
                    _fast_done = {'done': True, 'content': text, 'ux_states': [], 'memory_influenced': [], 'reasoning_mode': 'light', 'conversation_id': conversation_id, 'memory_updated': _mem_receipt(goal)}
                    _fast_arts = _extract_artifacts(text)
                    if _fast_arts:
                        _fast_done["artifacts"] = _fast_arts   # hardened server extraction for the panel
                    if _fast_delib_meta:
                        _fast_done["deliberation"] = _fast_delib_meta
                    yield f"data: {json.dumps(_fast_done)}\n\n"
                except Exception:
                    logger.exception("fast agen failed")
                    yield f"data: {json.dumps({'done': True, 'content': 'Sorry — something went wrong generating a reply. Please try again.', 'ux_states': [], 'memory_influenced': []})}\n\n"
                finally:
                    watch_task.cancel()
                    try:
                        await watch_task
                    except Exception:
                        pass

            return StreamingResponse(
                agen_fast(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # ── Multi-agent orchestration ─────────────────────────────────────────────────
        # A compound task ("research X and refactor Y") is decomposed into subtasks, each run
        # through the agent loop, then the answers are synthesized. Gated by
        # multi_agent_orchestration_enabled (auto-tune turns it on only for GPU tiers). Recursion
        # is structurally impossible: subtasks call autonomous_run directly, never this router.
        _use_ma = False
        try:
            from services.planning.multi_agent import run_multi_agent, should_use_multi_agent
            _use_ma = should_use_multi_agent(goal, cfg)
        except Exception:
            _use_ma = False
        if _use_ma:
            _ma_abort = threading.Event()

            async def agen_ma():
                watch_task = asyncio.create_task(_watch_client_disconnect(request, _ma_abort))
                try:
                    yield f"data: {json.dumps({'ux_state': 'thinking'})}\n\n"
                    # Surface a cold model load so the UI shows "Loading model…" rather than a
                    # generic wait — multi-agent runs are heavy and cold-start is the worst case.
                    try:
                        from services.llm.llm_gateway import model_is_loaded
                        if not model_is_loaded():
                            yield f"data: {json.dumps({'ux_state': 'loading_model'})}\n\n"
                    except Exception:
                        pass
                    yield f"data: {json.dumps({'ux_state': 'multi_agent'})}\n\n"
                    try:
                        agg = await run_multi_agent(goal, cfg=cfg)
                    except Exception:
                        logger.exception("multi_agent run failed")
                        agg = {"summary": "", "subtask_results": []}
                    text = polish_output(truncate_at_next_user_turn(strip_junk_from_reply(agg.get("summary") or "")), cfg) \
                        or "I couldn't complete that multi-part request. Try splitting it into separate messages."
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", text)
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    _subs = [{"description": r.get("description"), "ok": bool(r.get("ok"))}
                             for r in agg.get("subtask_results", [])]
                    _ma_done = {'done': True, 'content': text, 'ux_states': [], 'memory_influenced': [], 'reasoning_mode': 'multi_agent', 'conversation_id': conversation_id, 'subtasks': _subs}
                    _ma_arts = _extract_artifacts(text)
                    if _ma_arts:
                        _ma_done["artifacts"] = _ma_arts
                    yield f"data: {json.dumps(_ma_done)}\n\n"
                finally:
                    watch_task.cancel()
                    try:
                        await watch_task
                    except Exception:
                        pass

            return StreamingResponse(
                agen_ma(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        ux_state_queue = queue.Queue()
        result_holder = []
        error_holder = []
        client_abort = threading.Event()

        def run_agent():
            try:
                r = _dispatch_autonomous_run(
                    goal,
                    context=context,
                    workspace_root=workspace_root,
                    allow_write=allow_write,
                    allow_run=allow_run,
                    conversation_history=list(conv_history) if conv_history else list(_history),
                    aspect_id=aspect_id,
                    show_thinking=show_thinking,
                    stream_final=True,
                    ux_state_queue=ux_state_queue,
                    model_override=model_override or None,
                    reasoning_effort=reasoning_effort,
                    priority=PRIORITY_CHAT,
                    persona_focus=persona_focus,
                    conversation_id=conversation_id,
                    cognition_workspace_roots=cognition_workspace_roots or None,
                    client_abort_event=client_abort,
                    active_plan_id=_active_plan_id,
                    plan_approved=_plan_approved_flag,
                    engineering_pipeline_mode=_ep_mode if _ep_enabled else "chat",
                    clarification_reply=clarification_reply,
                )
                result_holder.append(r)
            except Exception as e:
                error_holder.append(e)

        thread = threading.Thread(target=run_agent)
        thread.start()

        async def agen():
            watch_task = asyncio.create_task(_watch_client_disconnect(request, client_abort))
            try:
                yield f"data: {json.dumps({'ux_state': 'thinking'})}\n\n"
                # If no model is resident yet, tell the client it's LOADING (not just
                # "thinking"), so a cold first-load shows a truthful state instead of an
                # ambiguous spinner (and the client's stall/hard timers reflect a real load).
                try:
                    from services.llm.llm_gateway import model_is_loaded
                    if not model_is_loaded():
                        yield f"data: {json.dumps({'ux_state': 'loading_model'})}\n\n"
                except Exception:
                    pass
                _last_stream_activity = time.monotonic()
                while thread.is_alive() or not ux_state_queue.empty():
                    try:
                        ux = await asyncio.to_thread(lambda: ux_state_queue.get(timeout=0.15))
                    except queue.Empty:
                        if (
                            _pulse_sec > 0
                            and thread.is_alive()
                            and (time.monotonic() - _last_stream_activity) >= _pulse_sec
                        ):
                            yield f"data: {json.dumps({'pulse': True})}\n\n"
                            _last_stream_activity = time.monotonic()
                        if not thread.is_alive():
                            break
                        continue
                    _last_stream_activity = time.monotonic()
                    if isinstance(ux, dict) and ux.get("_type") == "tool_start":
                        yield f"data: {json.dumps({'tool_start': ux['tool'], 'type': 'tool_step', 'phase': 'start', 'tool': ux['tool']})}\n\n"
                    elif isinstance(ux, dict) and ux.get("_type") == "think":
                        yield f"data: {json.dumps({'think': ux.get('content', ''), 'think_step': ux.get('step', 0), 'type': 'thinking', 'text': ux.get('content', ''), 'step': ux.get('step', 0)})}\n\n"
                    elif isinstance(ux, dict) and ux.get("_type") == "tool_step":
                        payload = {"type": "tool_step"}
                        payload.update({k: v for k, v in ux.items() if k != "_type"})
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif isinstance(ux, dict) and ux.get("_type") == "ctx_warn":
                        yield f"data: {json.dumps({'ux_state': ux.get('ux_state'), 'ctx_pct': ux.get('ctx_pct')})}\n\n"
                    else:
                        yield f"data: {json.dumps({'ux_state': ux})}\n\n"
                thread.join(timeout=0.5)
                if error_holder:
                    err = str(error_holder[0])
                    if "model" in err.lower() or "path" in err.lower():
                        err = f"Model error: {err}. Configure runtime_config.json. See MODELS.md."
                    _append_history("user", goal)
                    _append_history("assistant", err)
                    yield f"data: {json.dumps({'done': True, 'content': err, 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                result = result_holder[0] if result_holder else {}
                if result.get("status") == "system_busy":
                    _append_history("user", goal)
                    _append_history("assistant", "I couldn't reply just then.")
                    yield f"data: {json.dumps({'done': True, 'content': 'System is under load (CPU or RAM). Try again in a moment.', 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                if result.get("status") == "timeout":
                    _append_history("user", goal)
                    _append_history("assistant", "I couldn't reply just then.")
                    yield f"data: {json.dumps({'done': True, 'content': 'Request took too long and was stopped. Try a shorter message or try again.', 'ux_states': [], 'memory_influenced': []})}\n\n"
                    return
                if result.get("status") == "client_abort":
                    msg = result.get("response") or "Request cancelled (client disconnected)."
                    _append_history("user", goal)
                    _append_history("assistant", msg)
                    yield f"data: {json.dumps({'done': True, 'content': msg, 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'status': 'client_abort'})}\n\n"
                    return
                if result.get("status") == "pipeline_needs_input":
                    msg = result.get("response") or "More information needed."
                    _append_history("user", goal)
                    _append_history("assistant", msg)
                    yield f"data: {json.dumps({'done': True, 'content': msg, 'questions': result.get('questions') or [], 'ux_states': result.get('ux_states', []), 'memory_influenced': result.get('memory_influenced', []), 'status': 'pipeline_needs_input', 'reasoning_mode': result.get('reasoning_mode'), 'conversation_id': conversation_id})}\n\n"
                    return
                if result.get("status") == "stream_pending":
                    goal_for_stream = result.get("goal_for_stream", goal)
                    full = []
                    _emitted = 0  # chars already streamed marker-safe (see stream_safe_prefix)
                    from services.agent.response_builder import stream_safe_prefix as _ssp
                    tok_q: queue.Queue = queue.Queue()

                    def _stream_worker() -> None:
                        try:
                            for t in stream_reason(
                                goal_for_stream,
                                context=context,
                                conversation_history=list(conv_history) if conv_history else list(_history),
                                aspect_id=aspect_id,
                                show_thinking=show_thinking,
                                model_override=model_override or None,
                                skip_self_reflection=(result.get("reasoning_mode") or "light") in ("none", "light"),
                                reasoning_mode_override=result.get("reasoning_mode_for_stream"),
                                precomputed_recall=result.get("precomputed_recall_for_stream"),
                                persona_focus=result.get("persona_focus_for_stream") or "",
                                workspace_root=result.get("stream_workspace_root") or workspace_root,
                                cognition_workspace_roots=result.get("cognition_workspace_roots_for_stream"),
                                budget_retrieval_depth=str(result.get("budget_retrieval_depth") or ""),
                            ):
                                tok_q.put(t)
                        except Exception as ex:
                            logger.warning("stream_reason worker: %s", ex)
                        finally:
                            tok_q.put(None)

                    threading.Thread(target=_stream_worker, daemon=True).start()
                    _tok_empty = object()
                    _last_tok_activity = time.monotonic()
                    while True:
                        def _tok_get():
                            try:
                                return tok_q.get(timeout=0.25)
                            except queue.Empty:
                                return _tok_empty

                        _got = await asyncio.to_thread(_tok_get)
                        if _got is _tok_empty:
                            if (
                                _pulse_sec > 0
                                and (time.monotonic() - _last_tok_activity) >= _pulse_sec
                            ):
                                yield f"data: {json.dumps({'pulse': True})}\n\n"
                                _last_tok_activity = time.monotonic()
                            continue
                        token = _got
                        if token is None:
                            break
                        _last_tok_activity = time.monotonic()
                        # Intercept deliberation metadata marker from debate engine
                        if isinstance(token, str) and token.startswith("__DELIB_META__"):
                            try:
                                _dm_json = token.split("__DELIB_META__")[1].split("__DELIB_END__")[0]
                                result["_deliberation_meta"] = json.loads(_dm_json)
                                yield f"data: {json.dumps({'deliberation': result['_deliberation_meta']})}\n\n"
                            except Exception:
                                pass
                            continue
                        full.append(token)
                        # Stream only marker-safe text (hold an unclosed "[", strip complete
                        # [MARKER …] / [⚔ MORRIGAN] tags) so control/aspect scaffolding never
                        # flashes live while the header already shows "Layla ⚔ Morrigan".
                        _delta, _emitted = _ssp("".join(full), _emitted)
                        if _delta:
                            yield f"data: {json.dumps({'token': _delta})}\n\n"
                    try:
                        import runtime_safety

                        cfg = runtime_safety.load_config()
                    except Exception:
                        cfg = {}
                    text = polish_output(
                        truncate_at_next_user_turn(strip_junk_from_reply("".join(full), _aspect_extra_names(result))),
                        cfg,
                    )
                    # Empty cleaned reply must NOT ship as empty done-frame content: the client's
                    # done handler keeps the RAW streamed text (with any leaked scaffolding) when
                    # content is blank, and TTS would then speak it. Give this branch the same
                    # standby the fast path uses so done.content is always non-empty and clean.
                    if not (text or "").strip():
                        text = "Sorry — I couldn't generate a response just then. Please try again."
                    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", text)
                    try:
                        from layla.memory.db import append_conversation_message, create_conversation

                        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "assistant", text, aspect_id=result.get("aspect", ""))
                        _maybe_synth_title(conversation_id, goal, text)
                    except Exception:
                        pass
                    _append_history("user", goal)
                    _append_history("assistant", text)
                    _steps_safe = []
                    try:
                        import json as _j
                        _steps_safe = [{"action": s.get("action",""), "result": s.get("result")} for s in (result.get("steps") or [])]
                        _j.dumps(_steps_safe)  # verify serialisable
                    except Exception:
                        _steps_safe = []
                    _done_stream = {
                        "done": True,
                        "content": text,
                        "aspect_name": result.get("aspect_name", "Layla"),
                        "ux_states": result.get("ux_states", []),
                        "memory_influenced": result.get("memory_influenced", []),
                        "reasoning_mode": result.get("reasoning_mode"),
                        "conversation_id": conversation_id,
                        "reasoning_tree_summary": result.get("reasoning_tree_summary"),
                        "steps": _steps_safe,
                        "run_budget_summary": result.get("run_budget_summary") or {},
                        "confidence": result.get("confidence") or {},
                        "memory_updated": _mem_receipt(goal),
                    }
                    if _cfg_stream.get("ui_decision_trace_enabled"):
                        _done_stream["decision_trace"] = (result.get("decision_trace") or [])[-15:]
                    _st_arts = _extract_artifacts(text)
                    if _st_arts:
                        _done_stream["artifacts"] = _st_arts
                    # Include deliberation metadata if available (streaming path)
                    _dm = result.get("_deliberation_meta")
                    if _dm:
                        _done_stream["deliberation"] = _dm
                    yield f"data: {json.dumps(_done_stream)}\n\n"
                else:
                    steps = result.get("steps") or []
                    final = steps[-1].get("result", "") if steps else ""
                    # Prefer the run's synthesized prose answer. NEVER json.dumps a raw tool-result
                    # dict into the reply — that leaked internal payloads like
                    # {"ok": true, "memories": [...]} straight to the user as the message.
                    response_text = (result.get("response") or result.get("reply") or "").strip()
                    if not response_text and isinstance(final, str):
                        response_text = final.strip()
                    # Clean the synthesized answer the SAME way the token-streaming branch does
                    # (line ~1071). This tool-using done-frame previously applied only .strip(), so a
                    # leaked leading speaker label / control tag in a tool-run answer reached the
                    # client, the DB, and next-turn context uncleaned. Guard: only take the cleaned
                    # text when non-empty, so a degenerate reply still falls through to the standby.
                    if response_text:
                        try:
                            _rc = polish_output(truncate_at_next_user_turn(strip_junk_from_reply(response_text, _aspect_extra_names(result))), _cfg_stream)
                            if _rc.strip():
                                response_text = _rc
                        except Exception:
                            pass
                    if not response_text and result.get("status") == "tool_limit":
                        response_text = "Stopped after maximum tool calls. Try a simpler request or say 'continue'."
                    if not response_text and result.get("status") == "parse_failed":
                        response_text = "I couldn't understand the request. Please rephrase."
                    if not response_text:
                        response_text = "No response. Try again or rephrase."
                    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)
                    append_conv_history(conversation_id, "user", goal)
                    append_conv_history(conversation_id, "assistant", response_text)
                    try:
                        from layla.memory.db import append_conversation_message, create_conversation

                        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
                        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
                        _maybe_synth_title(conversation_id, goal, response_text)
                    except Exception:
                        pass
                    _append_history("user", goal)
                    _append_history("assistant", response_text)
                    _done_ns = {
                        "done": True,
                        "content": response_text,
                        "aspect_name": result.get("aspect_name", "Layla"),
                        "ux_states": result.get("ux_states", []),
                        "memory_influenced": result.get("memory_influenced", []),
                        "reasoning_mode": result.get("reasoning_mode"),
                        "conversation_id": conversation_id,
                        "reasoning_tree_summary": result.get("reasoning_tree_summary"),
                        "run_budget_summary": result.get("run_budget_summary") or {},
                        "confidence": result.get("confidence") or {},
                    }
                    if _cfg_stream.get("ui_decision_trace_enabled"):
                        _done_ns["decision_trace"] = (result.get("decision_trace") or [])[-15:]
                    _ns_arts = _extract_artifacts(response_text)
                    if _ns_arts:
                        _done_ns["artifacts"] = _ns_arts
                    # Include deliberation metadata if available (non-streaming path)
                    _dm_ns = result.get("deliberation_result")
                    if _dm_ns:
                        _done_ns["deliberation"] = _dm_ns
                    yield f"data: {json.dumps(_done_ns)}\n\n"
            except Exception as e:
                logger.exception("stream_agent failed")
                # Detail logged server-side; do not stream raw exception text to the client.
                low = str(e).lower()
                if "model" in low or "path" in low:
                    err = "Model error: the LLM could not be loaded. Set model_filename in runtime_config.json and ensure the .gguf file exists. See MODELS.md."
                else:
                    err = "The request failed while processing. Check the server logs for details."
                yield f"data: {json.dumps({'done': True, 'content': err, 'ux_states': [], 'memory_influenced': []})}\n\n"
            finally:
                watch_task.cancel()
                try:
                    await watch_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        return StreamingResponse(
            agen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = await asyncio.to_thread(
            _dispatch_autonomous_run,
            goal,
            context=context,
            workspace_root=workspace_root,
            allow_write=allow_write,
            allow_run=allow_run,
            conversation_history=list(conv_history) if conv_history else list(_history),
            aspect_id=aspect_id,
            show_thinking=show_thinking,
            stream_final=stream,
            model_override=model_override or None,
            reasoning_effort=reasoning_effort,
            priority=PRIORITY_CHAT,
            persona_focus=persona_focus,
            conversation_id=conversation_id,
            cognition_workspace_roots=cognition_workspace_roots,
            active_plan_id=_active_plan_id,
            plan_approved=_plan_approved_flag,
            engineering_pipeline_mode=_ep_mode if _ep_enabled else "chat",
            clarification_reply=clarification_reply,
        )
    except Exception as e:
        logger.exception("agent run failed")
        # Detail is logged server-side; never echo raw exception text / internal paths
        # to the client (info disclosure). Keep the actionable model-config hint only.
        low = str(e).lower()
        if "model" in low or "path" in low or "file" in low:
            err_msg = "Model error: the LLM could not be loaded. Set model_filename in runtime_config.json and ensure the .gguf file exists. See MODELS.md."
        else:
            err_msg = "The request failed while processing. Check the server logs for details."
        _append_history("user", goal)
        _append_history("assistant", "I couldn't reply - see the message above.")
        return JSONResponse({
            "response": err_msg,
            "state": {"status": "error", "steps": []},
            "aspect": "",
            "aspect_name": "Layla",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
            "cited_sources": [],
        }, status_code=500)

    steps = result.get("steps") or []
    final = steps[-1].get("result", "") if steps else ""
    _raw_final = final if isinstance(final, str) else json.dumps(final) if final else ""
    _extra_names = _aspect_extra_names(result)
    # truncate_at_next_user_turn (parity with the streaming paths) — the non-stream JSON path omitted
    # it, so a fabricated "User: …" next-turn the small model hallucinated leaked into the reply.
    response_text = truncate_at_next_user_turn(strip_junk_from_reply(_raw_final, _extra_names))
    if not response_text:
        _raw_alt = (result.get("response") or result.get("reply") or "").strip()
        response_text = truncate_at_next_user_turn(strip_junk_from_reply(_raw_alt, _extra_names))
    # When the model generated only echo (stripped to empty), substitute a graceful standby line
    # rather than the generic error. This happens when a small model starts with ## CONTEXT or
    # similar section headers and the stop sequence / junk stripper removes everything.
    _was_all_echo = (not response_text) and bool(_raw_final or _raw_alt if '_raw_alt' in dir() else _raw_final)
    if not response_text and result.get("status") == "system_busy":
        response_text = "System is under load (CPU or RAM). Try again in a moment."
    elif not response_text and result.get("status") == "timeout":
        response_text = "Request took too long and was stopped. Try a shorter message or try again."
    elif not response_text and result.get("status") == "client_abort":
        response_text = result.get("response") or "Request cancelled (client disconnected)."
    elif not response_text and result.get("status") == "tool_limit":
        response_text = "Stopped after maximum tool calls. Try a simpler request or say 'continue'."
    elif not response_text and result.get("status") == "parse_failed":
        response_text = "I couldn't understand the request. Please rephrase."
    elif not response_text:
        # When the raw output was all-echo (model echoed system prompt sections), it was
        # stripped to empty. Return a neutral standby rather than a confusing error.
        response_text = "Ready. What do you need?"

    if result.get("status") == "finished":
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
        response_text = polish_output(response_text, cfg)
    result["reasoning_tree_summary"] = _build_reasoning_tree_summary(result)

    # Post-model safety floor (symmetric with check_input): a Tier-1/Tier-2 payload the
    # model produced is replaced with a safe message before it is persisted or returned.
    try:
        import runtime_safety as _rs_out
        from services.safety.content_guard import blocked_response as _blk_out
        from services.safety.content_guard import check_output as _cg_out
        _out = _cg_out(response_text, _rs_out.load_config())
        if _out.blocked:
            logger.warning("content_guard: /agent output blocked tier=%s cat=%s", _out.tier, _out.category)
            response_text = _blk_out(_out)
    except Exception:
        pass

    append_conv_history(conversation_id, "user", goal)
    append_conv_history(conversation_id, "assistant", response_text)
    try:
        from layla.memory.db import append_conversation_message, create_conversation

        create_conversation(conversation_id, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "user", goal, aspect_id=result.get("aspect", ""))
        append_conversation_message(conversation_id, "assistant", response_text, aspect_id=result.get("aspect", ""))
    except Exception:
        pass
    _append_history("user", goal)
    if result.get("status") in ("system_busy", "timeout") and response_text:
        _append_history("assistant", "I couldn't reply just then.")
    else:
        _append_history("assistant", response_text)

    _state_out = _json_safe(result)
    if isinstance(_state_out, dict):
        _state_out.setdefault("steps", [])

    response_payload = {
        "response": response_text,
        "state": _state_out,
        "aspect": result.get("aspect", ""),
        "aspect_name": result.get("aspect_name", "Layla"),
        "refused": result.get("refused", False),
        "refusal_reason": _json_safe(result.get("refusal_reason", "")),
        "ux_states": _json_safe(result.get("ux_states", [])),
        "memory_influenced": _json_safe(result.get("memory_influenced", [])),
        "cited_sources": _json_safe(result.get("cited_knowledge_sources", [])),
        "reasoning_mode": result.get("reasoning_mode"),
        "conversation_id": conversation_id,
        "load": _json_safe(classify_load()),
        "reasoning_tree_summary": _json_safe(result.get("reasoning_tree_summary", {})),
        "run_budget_summary": _json_safe(result.get("run_budget_summary", {})),
        "confidence": _json_safe(result.get("confidence", {})),
    }
    # Phase 0.4: inject last model routing decision for operator audit
    try:
        from services.llm.model_router import get_last_routing_decision
        _rd = get_last_routing_decision()
        if _rd:
            response_payload["model_selection"] = _json_safe(_rd)
    except Exception:
        pass
    try:
        import runtime_safety as _rs_dt

        if _rs_dt.load_config().get("ui_decision_trace_enabled"):
            response_payload["decision_trace"] = _json_safe((result.get("decision_trace") or [])[-15:])
    except Exception:
        pass
    if result.get("questions") is not None:
        response_payload["questions"] = _json_safe(result.get("questions"))
    if result.get("pipeline_plan_id"):
        response_payload["pipeline_plan_id"] = str(result.get("pipeline_plan_id"))
    if result.get("failure_report"):
        response_payload["failure_report"] = str(result.get("failure_report"))
    if result.get("pipeline_status"):
        response_payload["pipeline_status"] = str(result.get("pipeline_status"))
    # Server-side artifact extraction (Item #11): parse code blocks from response
    # so the UI can immediately render the artifacts panel without client-side JS scanning.
    try:
        _artifacts = _extract_artifacts(response_text)
        if _artifacts:
            response_payload["artifacts"] = _artifacts
    except Exception:
        pass
    if (
        cache_enabled
        and _cache_stateless  # never cache a history-conditioned reply (cross-conversation bleed)
        and not _cache_shaped  # nor a reply shaped by per-turn model/thinking/persona/research params
        and not stream
        and not allow_write
        and not allow_run
        and not context
        and not image_url
        and not image_base64
        and not (_ep_enabled and _ep_mode in ("plan", "execute"))
    ):
        try:
            from services.retrieval.response_cache import put_cached_response
            # Key on the REQUEST's aspect_id (same fallback the read uses: `aspect_id or "morrigan"`).
            # Keying the WRITE on the resolved response aspect instead made the write/read keys
            # asymmetric for auto-selected turns, so the cache never hit (goal='hi' + empty aspect
            # stored under 'nyx' but looked up under 'morrigan').
            put_cached_response(goal, aspect_id or "morrigan", response_payload, max_entries=cache_max_entries)
        except Exception:
            pass
    return JSONResponse(response_payload)


import json
import logging
import queue
import threading
import time
from pathlib import Path
import psutil
logger = logging.getLogger("layla")

import runtime_safety
import orchestrator
from decision_schema import parse_decision as _parse_decision
from jinx.tools.registry import TOOLS, set_effective_sandbox
from jinx.memory.db import migrate as _db_migrate, get_recent_learnings as _db_get_learnings, get_aspect_memories as _db_get_aspect_memories, save_aspect_memory as _db_save_aspect_memory
from services.llm_gateway import run_completion, get_stop_sequences, llm_serialize_lock

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_LAB_ROOT = AGENT_DIR / ".research_lab"


def _path_under_lab(path: str | Path, lab_root: str) -> bool:
    """True if path resolves under lab_root (for research_mode write/run gating)."""
    if not lab_root or not path:
        return False
    try:
        p = Path(path).resolve()
        lab = Path(lab_root).resolve()
        p.relative_to(lab)
        return True
    except ValueError:
        return False
    except Exception:
        return False


def _research_response_asks_user(text: str) -> bool:
    """True if response looks like asking the user a question (research_mode: treat as incomplete)."""
    if not text or len(text.strip()) < 20:
        return False
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    phrases = (
        "what would you like",
        "what's the first thing",
        "would you like me to",
        "would you like to",
        "shall i ",
        "do you want me to",
        "do you want to",
        "should i ",
        "what do you want",
        "how would you like",
        "which would you",
        "let me know what",
        "tell me what",
        "ask you",
        "your preference",
    )
    return any(p in t for p in phrases)


# Placeholder for sanitized assistant turns in convo_block (never use "I replied." — model repeats it)
_SANITIZED_PLACEHOLDER = "[...]"

# UX interaction states (UI layer only; no change to decision logic)
UX_STATE_THINKING = "thinking"
UX_STATE_VERIFYING = "verifying"
UX_STATE_CHANGING_APPROACH = "changing_approach"
UX_STATE_REFRAMING_OBJECTIVE = "reframing_objective"


def _emit_ux(state: dict, ux_state_queue: queue.Queue | None, label: str) -> None:
    """Append UX state for this turn and optionally push to queue for live SSE."""
    state.setdefault("ux_states", []).append(label)
    if ux_state_queue is not None:
        try:
            ux_state_queue.put(label, block=False)
        except Exception:
            pass


def _is_junk_reply(content: str) -> bool:
    """True if content is the repeated junk we must never feed back (e.g. 'assistant: I replied.' or just 'I replied.')."""
    if not content or not content.strip():
        return True
    import re as _re_junk
    s = content.strip().lower()
    if s == "i replied." or s == "assistant: i replied.":
        return True
    # Remove all "assistant: i replied." (with flexible spacing); if nothing left, it's junk
    remainder = _re_junk.sub(r"\s*assistant\s*:\s*i\s+replied\.\s*", " ", s, flags=_re_junk.IGNORECASE).strip()
    if len(remainder) < 15 and ("assistant" in s and "i replied" in s):
        return True
    return False


def truncate_at_next_user_turn(text: str) -> str:
    """Keep only the first reply; cut at the first 'User:' so we don't save/show the model continuing the dialogue."""
    if not text or not text.strip():
        return (text or "").strip()
    import re as _re
    t = text.strip()
    # If model echoed the prompt and started with "User: ...", keep only from the first aspect reply (e.g. "Eris: ...")
    if _re.match(r"^\s*User\s*:", t, _re.IGNORECASE):
        m = _re.search(r"^\s*User\s*:[^\n]*?\s+([A-Za-z]+)\s*:", t, _re.IGNORECASE)
        if m:
            t = t[m.start(1) :].strip()  # from "Eris:" (or aspect name) onward
        else:
            # no "Name:" on first line; drop the first line and keep the rest
            first_line_end = t.find("\n")
            if first_line_end != -1:
                t = t[first_line_end + 1 :].strip()
            else:
                t = ""
    # Cut at newline followed by "User:" (start of next user turn)
    m = _re.search(r"\n\s*User\s*:", t, _re.IGNORECASE)
    if m:
        return t[: m.start()].strip()
    # Cut at " User:" mid-line (e.g. "blah. User:")
    m = _re.search(r"\s+User\s*:", t, _re.IGNORECASE)
    if m:
        return t[: m.start()].strip()
    return t


def strip_junk_from_reply(text: str) -> str:
    """Remove repeated 'assistant: I replied.' and other junk from a reply before saving/displaying."""
    if not text or not text.strip():
        return (text or "").strip()
    import re as _re
    t = text.strip()
    for _ in range(50):
        prev = t
        t = _re.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", t, count=1, flags=_re.IGNORECASE).strip()
        if t == prev:
            break
    if _is_junk_reply(t):
        return ""
    return t


# Ensure DB tables exist before first request
_db_migrate()

def stream_reason(
    goal: str,
    context: str = "",
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
):
    """
    Build the same prompt as the reason path and yield token strings from streaming completion.
    Used when the client requests stream=True; no refusal/earned_title parsing.
    """
    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    head = _build_system_head(goal=goal, aspect=active_aspect)
    convo_block = ""
    try:
        convo_turns = max(0, int(runtime_safety.load_config().get("convo_turns", 0)))
    except (TypeError, ValueError):
        convo_turns = 0
    if convo_turns > 0 and conversation_history:
        name = active_aspect.get("name", "Layla")
        turns = conversation_history[-convo_turns:]
        lines = []
        for t in turns:
            role = t.get("role", "")
            content_t = (t.get("content") or "")[:300].strip()
            if role == "user":
                lines.append(f"User: {content_t}")
            else:
                if "system is under load" in content_t.lower():
                    content_t = "I couldn't reply just then."
                elif (content_t.startswith("[") and "You are" in content_t) or ("you are layla" in content_t.lower() and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())):
                    content_t = _SANITIZED_PLACEHOLDER
                elif _is_junk_reply(content_t):
                    content_t = _SANITIZED_PLACEHOLDER
                lines.append(f"{name}: {content_t}")
        convo_block = "\n".join(lines)
    deliberate = show_thinking or orchestrator.should_deliberate(goal, active_aspect)
    if deliberate:
        prompt = orchestrator.build_deliberation_prompt(
            message=goal, active_aspect=active_aspect, context=_enrich_deliberation_context(context),
        )
        if head:
            prompt = head + "\n\n" + prompt
        if convo_block:
            prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"
    else:
        prompt = orchestrator.build_standard_prompt(
            message=goal, aspect=active_aspect, context=context,
            head=head, convo_block=convo_block,
        )
    cfg = runtime_safety.load_config()
    temperature = cfg.get("temperature", 0.2)
    max_tok = cfg.get("completion_max_tokens", 256)
    stop = get_stop_sequences()
    gen = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=True, stop=stop)
    buffer = ""
    for token in gen:
        buffer += token
        if any(s in buffer for s in stop):
            break
        yield token


def _write_pending(tool: str, args: dict) -> str:
    """Write a pending approval entry and return its UUID. Exposes risk_level from registry for UI."""
    import uuid as _uuid
    from datetime import datetime
    gov_path = Path(__file__).resolve().parent / ".governance"
    gov_path.mkdir(parents=True, exist_ok=True)
    pending_file = gov_path / "pending.json"
    try:
        data = json.loads(pending_file.read_text(encoding="utf-8")) if pending_file.exists() else []
    except Exception:
        data = []
    entry_id = str(_uuid.uuid4())
    risk = (TOOLS.get(tool) or {}).get("risk_level") or "medium"
    data.append({
        "id": entry_id,
        "tool": tool,
        "args": args,
        "requested_at": datetime.utcnow().isoformat(),
        "status": "pending",
        "risk_level": risk,
    })
    pending_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return entry_id


def _load_learnings(aspect_id: str = "") -> str:
    try:
        n = runtime_safety.load_config().get("learnings_n", 30)
        rows = _db_get_learnings(n=n, aspect_id=aspect_id or None)
        return "\n".join(r["content"] for r in rows if r.get("content"))
    except Exception:
        return ""


def _semantic_recall(query: str, k: int = 5) -> str:
    """Return top-k semantically similar learnings as a text block."""
    try:
        from jinx.memory.vector_store import embed, search_similar
        vec = embed(query)
        results = search_similar(vec, k=k)
        if not results:
            return ""
        lines = [r.get("content", "") for r in results if r.get("content")]
        return "\n".join(lines)
    except Exception:
        return ""


def _decompose_goal(goal: str) -> list:
    """If objective is broad, return 2-3 sub-objectives; else return []."""
    if not goal or len(goal.strip()) < 20:
        return []
    g = goal.lower().strip()
    broad_keywords = (
        "production ready", "refactor", "fix everything", "improve", "complete", "full",
        "make this repo", "get this ready", "clean up", "overhaul", "rewrite",
    )
    is_broad = len(goal) > 80 or any(kw in g for kw in broad_keywords)
    if not is_broad:
        return []
    try:
        cfg = runtime_safety.load_config()
        prompt = (
            f"Objective: {goal[:500]}\n\n"
            "Output exactly one JSON line: a JSON array of 2-3 concrete sub-objectives (short strings). "
            "Example: [\"Add tests\", \"Fix lint\", \"Update README\"]. No other text.\n"
        )
        out = run_completion(prompt, max_tokens=120, temperature=0.2, stream=False)
        if isinstance(out, dict):
            raw = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
        else:
            raw = ""
        for line in (raw or "").strip().splitlines():
            line = line.strip()
            if line.startswith("["):
                arr = json.loads(line)
                if isinstance(arr, list) and len(arr) >= 1:
                    subs = [str(x).strip() for x in arr[:3] if x]
                    return subs[:3]
        return []
    except Exception as e:
        logger.debug("decompose_goal failed: %s", e)
        return []


def _get_repo_structure(workspace_root: str | Path, max_entries: int = 40) -> str:
    """Top-level repo structure for workspace context. No tool call, filesystem only."""
    ws = str(workspace_root).strip() if workspace_root else ""
    if not ws:
        return ""
    try:
        root = Path(ws).resolve()
        if not root.exists() or not root.is_dir():
            return ""
        entries = []
        for p in sorted(root.iterdir())[:max_entries]:
            name = p.name
            if name.startswith(".") and name not in (".git",):
                continue
            entries.append(name + ("/" if p.is_dir() else ""))
        if not entries:
            return "(empty directory)"
        return ", ".join(entries[:max_entries])
    except Exception:
        return ""


def _enrich_deliberation_context(context: str) -> str:
    """Append project context and Echo patterns so deliberation has real workspace awareness."""
    extra = []
    try:
        from jinx.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("lifecycle_stage"):
            proj_parts = [f"Project: {pc.get('project_name') or '—'}", f"Lifecycle: {pc.get('lifecycle_stage') or '—'}"]
            if pc.get("goals"):
                proj_parts.append(f"Goals: {(pc.get('goals') or '')[:200]}")
            extra.append("Project context: " + "; ".join(proj_parts))
    except Exception:
        pass
    try:
        learnings = _db_get_learnings(n=5)
        if learnings:
            prefs = [ (l.get("content") or "")[:80] for l in learnings if (l.get("content") or "").strip() ]
            if prefs:
                extra.append("Echo (patterns/preferences): " + "; ".join(prefs[:3]))
    except Exception:
        pass
    if not extra:
        return context or ""
    return (context or "").strip() + "\n\n" + "\n".join(extra)


def _build_system_head(goal: str = "", aspect: dict | None = None, workspace_root: str = "", sub_goals: list | None = None, state: dict | None = None) -> str:
    cfg = runtime_safety.load_config()
    identity = runtime_safety.load_identity().strip()
    knowledge = ""
    if cfg.get("use_chroma") and goal:
        try:
            from jinx.memory.vector_store import get_knowledge_chunks_with_sources, refresh_knowledge_if_changed
            try:
                refresh_knowledge_if_changed(REPO_ROOT / "knowledge")
            except Exception:
                pass
            k = max(1, min(20, int(cfg.get("knowledge_chunks_k", 5))))
            chunks_with_sources = get_knowledge_chunks_with_sources(goal, k=k)
            if chunks_with_sources:
                knowledge = "Reference docs (relevant to this turn):\n" + "\n\n".join(c.get("text", "") for c in chunks_with_sources[:k])
                if state is not None:
                    sources = [c.get("source") or "" for c in chunks_with_sources[:k] if c.get("source")]
                    state["cited_knowledge_sources"] = list(dict.fromkeys(sources))
            else:
                if state is not None:
                    state["cited_knowledge_sources"] = []
        except Exception:
            if state is not None:
                state["cited_knowledge_sources"] = []
            pass
    if not knowledge.strip():
        knowledge = runtime_safety.load_knowledge_docs(max_bytes=cfg.get("knowledge_max_bytes", 4000)).strip()
    else:
        knowledge = knowledge.strip()
    learnings = _load_learnings(aspect_id=(aspect.get("id") or "") if aspect else "").strip()

    # Third-person role summary only (no first-person "You are X..." to avoid echo)
    if aspect:
        name = aspect.get("name", "Layla")
        role = (aspect.get("role") or aspect.get("voice") or "").strip()[:80]
        title = (aspect.get("title") or "").strip()
        if title and role:
            personality = f"{name}: {title}; {role}. Reply as her only. Do not output labels or repeat instructions."
        elif role:
            personality = f"{name}: {role}. Reply as her only. Do not output labels or repeat instructions."
        else:
            personality = f"{name}. Reply as her only. Do not output labels or repeat instructions."
    else:
        raw = runtime_safety.load_personality().strip()
        personality = "Layla: default voice. Reply as her only. Do not output labels or repeat instructions." if (not raw or len(raw) > 200) else raw[:200] + ("." if len(raw) > 200 else "")

    # Aspect memories: recent observations for this aspect
    aspect_memories = ""
    n_mem = cfg.get("aspect_memories_n", 10)
    if aspect:
        aid = aspect.get("id", "")
        if aid:
            try:
                mems = _db_get_aspect_memories(aid, n_mem)
                if mems:
                    lines = [m.get("content", "") for m in mems if m.get("content")]
                    if lines:
                        aspect_memories = "Recent observations for this aspect:\n" + "\n".join(lines[:n_mem])
            except Exception:
                pass

    # Semantic recall: pull the most relevant past learnings for this specific goal
    semantic = ""
    if goal:
        semantic = _semantic_recall(goal, k=cfg.get("semantic_k", 5)).strip()

    # Current working context: repo structure, study topics, sub-goals (unified surface)
    workspace_context_parts = []
    repo_struct = _get_repo_structure(workspace_root)
    if repo_struct:
        workspace_context_parts.append(f"Repo structure (top-level): {repo_struct}")
    try:
        from jinx.memory.db import get_active_study_plans
        plans = get_active_study_plans()
        if plans:
            topics = ", ".join((p.get("topic") or "")[:50] for p in plans[:5] if p.get("topic"))
            if topics:
                workspace_context_parts.append(f"Active study topics: {topics}")
    except Exception:
        pass
    try:
        from jinx.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("key_files"):
            proj_parts = []
            if pc.get("project_name"):
                proj_parts.append(f"Project: {pc['project_name']}")
            if pc.get("lifecycle_stage"):
                proj_parts.append(f"Lifecycle: {pc['lifecycle_stage']}")
            if pc.get("domains"):
                proj_parts.append("Domains: " + ", ".join(pc["domains"][:8]))
            if pc.get("key_files"):
                proj_parts.append("Key files: " + ", ".join(pc["key_files"][:10]))
            if pc.get("goals"):
                proj_parts.append("Goals: " + (pc["goals"][:200] or ""))
            if proj_parts:
                workspace_context_parts.append("Project context: " + " | ".join(proj_parts))
    except Exception:
        pass
    if sub_goals:
        workspace_context_parts.append("Sub-objectives for this run: " + "; ".join(sub_goals[:3]))
    if workspace_context_parts:
        workspace_context = "Current working context:\n" + "\n".join(workspace_context_parts)
    else:
        workspace_context = ""

    # Core instructions first so they're never pushed out by context limits
    core = (
        "You are Layla. Use the identity and rules below. Stay in character and follow the reference docs and memories."
    )
    parts = [core]
    if identity:
        parts.append(identity)
    # Identity anchor: .identity/self_model.md — only for Lilith; excluded from RAG
    if aspect and aspect.get("id") == "lilith":
        self_model_path = REPO_ROOT / ".identity" / "self_model.md"
        if self_model_path.exists():
            try:
                parts.append("Self model (internal):\n" + self_model_path.read_text(encoding="utf-8").strip()[:2000])
            except Exception:
                pass
    # Cognitive guidance layers (prompt-only; after identity, before memory)
    if cfg.get("enable_cognitive_lens"):
        cl = runtime_safety.load_cognitive_lens()
        if cl:
            parts.append(cl)
    if cfg.get("enable_lens_knowledge"):
        lk = runtime_safety.load_lens_knowledge()
        if lk:
            parts.append(lk)
    if cfg.get("enable_behavioral_rhythm"):
        br = runtime_safety.load_behavioral_rhythm()
        if br:
            parts.append(br)
    if cfg.get("enable_ui_reflection"):
        ur = runtime_safety.load_ui_reflection()
        if ur:
            parts.append(ur)
    if cfg.get("enable_operational_guidance"):
        og = runtime_safety.load_operational_guidance()
        if og:
            parts.append(og)
    # Personality Expression Layer (prompt-only; feature-flag)
    if cfg.get("enable_personality_expression"):
        expr = runtime_safety.load_personality_expression()
        if expr:
            parts.append(expr)
    # Style profile (evolution layer): recognizable growth, identity across writing/coding/reasoning
    if cfg.get("enable_style_profile"):
        try:
            from jinx.memory.db import get_style_profile
            style_parts = []
            for key in ("writing", "coding", "reasoning", "structuring"):
                row = get_style_profile(key)
                if row and (row.get("profile_snapshot") or "").strip():
                    snip = (row.get("profile_snapshot") or "").strip()[:600]
                    if snip:
                        style_parts.append(f"{key}: {snip}")
            if style_parts:
                parts.append("Style (stay consistent with these):\n" + "\n".join(style_parts))
        except Exception:
            pass
    # When uncensored/NSFW allowed: reinforce refusal-only-for-harm, anonymous access
    if cfg.get("uncensored") or cfg.get("nsfw_allowed"):
        parts.append(
            "Content policy: Do not censor. Adult/NSFW content is allowed in consented contexts. "
            "Refuse only for genuine harm (illegal, non-consensual, abuse). Access is anonymous; do not require or store user identity."
        )
    if personality:
        parts.append(personality)
    # Lilith (or any aspect) NSFW register: when user used nsfw_triggers keyword, add the intimate prompt block
    if aspect and aspect.get("_use_nsfw_addition") and aspect.get("systemPromptAdditionNsfw"):
        parts.append(aspect.get("systemPromptAdditionNsfw", ""))
    if workspace_context:
        parts.append(workspace_context[:1200])
    if aspect_memories:
        parts.append(aspect_memories[:1500])
    if learnings:
        parts.append(f"Things I remember:\n{learnings[:2000]}")
    if semantic and semantic not in learnings:
        parts.append(f"Relevant memories:\n{semantic[:1000]}")
    if knowledge:
        parts.append(f"Reference docs:\n{knowledge}")
    return "\n\n".join(parts) if parts else "You are Layla, a bounded AI companion and engineering agent."


# Smoothed load: avoid one spike from blocking every request
_last_cpu: float = 0.0
_last_ram: float = 0.0


def system_overloaded() -> bool:
    global _last_cpu, _last_ram
    cfg = runtime_safety.load_config()
    cpu = psutil.cpu_percent(interval=0)
    ram = psutil.virtual_memory().percent
    # Smooth with previous sample so a single spike does not block
    smooth_cpu = (cpu + _last_cpu) / 2.0 if _last_cpu else cpu
    smooth_ram = (ram + _last_ram) / 2.0 if _last_ram else ram
    _last_cpu, _last_ram = cpu, ram
    return smooth_cpu > cfg.get("max_cpu_percent", 90) or smooth_ram > cfg.get("max_ram_percent", 90)


# Valid tool names for LLM decision (must match TOOLS registry)
_VALID_TOOLS = frozenset(TOOLS.keys())

# ─────────────────────────────────────────────────────────────
# Auto file probe (planning layer only)
# ─────────────────────────────────────────────────────────────
MAX_SAFE_READ_BYTES = 250 * 1024  # planning signal only
LARGE_FILE_HINT_LINES = 2000      # planning signal only


def _probe_store(state: dict) -> dict:
    cm = state.setdefault("context_memory", {})
    cm.setdefault("file_probed", {})
    cm.setdefault("file_probe_hints", {})
    return cm


def _maybe_preprobe_file(state: dict, path: str) -> dict | None:
    """
    Run file_info once per path (no approval, does not count toward tool_calls).
    Records as an internal step: action=pre_read_probe.
    """
    if not path:
        return None
    cm = _probe_store(state)
    probed = cm.get("file_probed") or {}
    if path in probed:
        return probed.get(path)
    try:
        result = TOOLS["file_info"]["fn"](path=path)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    cm["file_probed"][path] = result
    state.setdefault("steps", []).append({"action": "pre_read_probe", "path": path, "result": result})
    try:
        runtime_safety.log_execution("file_info", {"path": path, "tag": "pre_read_probe"})
    except Exception:
        pass
    return result


def _apply_probe_guidance(state: dict, intent: str, path: str, probe: dict | None) -> bool:
    """
    Soft planning gate before file operations.
    Returns True if the caller should proceed with the original tool; False to skip it for this loop.
    """
    if not isinstance(probe, dict) or not probe.get("ok"):
        return True
    is_text = probe.get("is_text")
    size = probe.get("size_bytes") or 0
    lines_sample = probe.get("line_count_sample")

    # Hard avoidance only for clearly binary files (avoid unsafe/bad UX).
    if is_text is False and intent in ("read_file", "apply_patch"):
        state.setdefault("steps", []).append({
            "action": intent,
            "result": {
                "ok": False,
                "reason": "binary_file",
                "message": "Probe indicates this file is binary; avoiding read/patch. Prefer grep_code on text sources or use a specialized extractor.",
            },
        })
        return False

    hints = []
    if isinstance(size, int) and size > MAX_SAFE_READ_BYTES:
        hints.append(f"Large file ({size} bytes): prefer grep_code first; if you must read, read narrowly and avoid dumping whole file.")
    if isinstance(lines_sample, int) and lines_sample >= LARGE_FILE_HINT_LINES:
        hints.append(f"Many lines (sample >= {lines_sample}): prefer grep-first; consider chunking strategy.")
    if hints:
        cm = _probe_store(state)
        cm["file_probe_hints"][path] = hints
    return True

# Tools that get a self-verification step (progress_made / retry_suggested)
_VERIFY_TOOLS = frozenset({
    "run_python", "apply_patch", "shell", "write_file",
    "git_status", "git_diff", "git_log", "git_branch",
})


def _verify_tool_progress(
    objective: str,
    steps_text: str,
    tool_name: str,
    result: dict,
) -> dict | None:
    """
    LLM evaluates whether the tool step moved the objective closer.
    Returns {"progress_made": bool, "retry_suggested": bool} or None.
    """
    obj_short = (objective or "")[:400]
    res_short = str(result)[:500]
    prompt = (
        f"Objective: {obj_short}\n\nLast tool: {tool_name}\nResult: {res_short}\n\n"
        "Did this step move the objective closer? Output exactly one JSON line, no other text. "
        'Format: {"progress_made": true or false, "retry_suggested": true or false}. '
        "retry_suggested true only if a different approach might help.\n"
    )
    try:
        out = run_completion(prompt, max_tokens=60, temperature=0.1, stream=False)
        if isinstance(out, dict):
            text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
        else:
            text = ""
        for line in (text or "").strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                if isinstance(data, dict):
                    return {
                        "progress_made": bool(data.get("progress_made", True)),
                        "retry_suggested": bool(data.get("retry_suggested", False)),
                    }
        return None
    except Exception as e:
        logger.debug("verify_tool_progress parse failed: %s", e)
        return None


def _observe_environment(tool_name: str, result: dict, workspace: str) -> bool:
    """
    Lightweight environment checks after a tool run. Returns True if observed state
    aligns with success (e.g. file changed, artifacts exist, command side-effects).
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return False
    try:
        workspace_path = Path(workspace or ".").resolve()
        if tool_name == "run_python":
            # Tests / scripts: returncode 0; optional stdout suggests execution
            rc = result.get("returncode", -1)
            return rc == 0
        if tool_name == "apply_patch":
            # Patch applied: target path exists
            p = result.get("path") or result.get("original_path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists()
        if tool_name == "shell":
            # Command side-effect: returncode 0
            return result.get("returncode", -1) == 0
        if tool_name == "write_file":
            # File written: path exists and non-empty
            p = result.get("path")
            if not p:
                return True
            path = Path(p)
            if not path.is_absolute():
                path = workspace_path / path
            return path.exists() and path.stat().st_size >= 0
        if tool_name in ("git_status", "git_diff", "git_log", "git_branch"):
            # Git: ok and we got output (or at least ok)
            return True
    except Exception as e:
        logger.debug("observe_environment failed: %s", e)
        return False
    return True


def _classify_failure_and_recovery(state: dict) -> None:
    """North Star §8: classify failure type and set structured recovery hint (stringify at prompt assembly)."""
    consecutive = state.get("consecutive_no_progress", 0)
    if consecutive == 0:
        state.pop("recovery_hint", None)
        return
    last_tool = state.get("last_tool_used") or ""
    if last_tool in ("read_file", "list_dir", "grep_code", "glob_files", "file_info", "get_project_context", "understand_file"):
        state["recovery_hint"] = {
            "type": "planning_gap",
            "message": "Consider breaking the goal into smaller steps or asking the user to clarify. Try a different inspection or reply (reason).",
            "source": "failure_classifier",
        }
    elif last_tool in ("write_file", "run_python", "apply_patch", "shell"):
        state["recovery_hint"] = {
            "type": "execution_issue",
            "message": "Execution may have failed or been blocked. Check tool result; suggest a fix or ask the user. Prefer read_file to verify state before retrying.",
            "source": "failure_classifier",
        }
    else:
        state["recovery_hint"] = {
            "type": "workflow_breakdown",
            "message": "Workflow may be stuck. Consider replying (reason) to summarize what was tried and suggest next steps, or propose a revised objective.",
            "source": "failure_classifier",
        }


def _format_recovery_hint_for_prompt(recovery_hint: dict) -> str:
    """Stringify structured recovery hint for injection into decision prompt."""
    if not recovery_hint or not isinstance(recovery_hint, dict):
        return ""
    t = recovery_hint.get("type") or ""
    msg = recovery_hint.get("message") or ""
    if not t and not msg:
        return ""
    return f"Failure type: {t}. Assist recovery: {msg} "


def _run_verification_after_tool(state: dict, tool_name: str, result: dict, workspace: str = "") -> None:
    """If tool is verifiable and succeeded, run verification and environment observation; update state."""
    if tool_name not in _VERIFY_TOOLS or not (isinstance(result, dict) and result.get("ok")):
        return
    objective = state.get("objective") or state.get("original_goal") or ""
    steps_text = _format_steps(state.get("steps") or [])
    ver = _verify_tool_progress(objective, steps_text, tool_name, result)
    if ver is not None:
        state["last_verification"] = ver
        if not ver.get("progress_made", True):
            state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
        else:
            state["consecutive_no_progress"] = 0

    # Post-verification observation: real system state
    state["environment_aligned"] = _observe_environment(tool_name, result, workspace)
    # If verification said progress but environment does not align, treat as no progress
    if ver and ver.get("progress_made") and not state.get("environment_aligned", True):
        state["consecutive_no_progress"] = state.get("consecutive_no_progress", 0) + 1
    # North Star §8: classify failure and set recovery hint when no progress
    if state.get("consecutive_no_progress", 0) > 0:
        _classify_failure_and_recovery(state)


def _llm_decision(
    goal: str,
    state: dict,
    context: str,
    active_aspect: dict,
    show_thinking: bool,
    conversation_history: list,
) -> dict | None:
    """
    Ask the model for a structured decision: action (tool|reason), tool name, objective_complete.
    Returns parsed dict or None to fall back to classify_intent.
    """
    steps_text = _format_steps(state.get("steps") or [])
    objective = (state.get("objective") or goal).strip()
    if steps_text:
        prompt_context = f"Objective: {objective[:500]}\n\nTool results so far:\n{steps_text[:1200]}\n\n"
    else:
        prompt_context = f"Objective: {objective[:800]}\n\n"
    sub_goals = state.get("sub_goals") or []
    if sub_goals:
        prompt_context += "Sub-objectives (guide tool choice): " + "; ".join(sub_goals[:3]) + "\n\n"

    # File probe awareness (planning-only): surface hints without forcing a hard stop.
    try:
        cm = state.get("context_memory") or {}
        hints = cm.get("file_probe_hints") or {}
        if hints:
            lines = []
            for p, hs in list(hints.items())[:3]:
                if isinstance(hs, list) and hs:
                    lines.append(f"- {p}: " + " ".join(str(x)[:160] for x in hs[:2]))
            if lines:
                prompt_context += "File probe hints:\n" + "\n".join(lines) + "\n\n"
    except Exception:
        pass

    aspect_block = ""
    if show_thinking:
        try:
            aspects = orchestrator._load_aspects()
            roster = getattr(orchestrator, "_DELIBERATION_ROSTER", ["morrigan", "nyx", "echo"])
            for aid in roster[:3]:
                a = next((x for x in aspects if x.get("id") == aid), None)
                if a and aid != active_aspect.get("id"):
                    name = a.get("name", aid)
                    role = (a.get("role") or a.get("voice") or "")[:60]
                    aspect_block += f"{name}: {role}\n"
            if aspect_block:
                aspect_block = "Aspects may suggest a tool; unify to one decision.\n" + aspect_block + "\n"
        except Exception:
            pass

    bias = orchestrator.get_decision_bias(active_aspect)
    bias_hint = ""
    if bias:
        bias_hint = f"Decision bias: {', '.join(bias)}. Prefer tools and approach that match.\n"

    no_progress_hint = ""
    last_ver = state.get("last_verification")
    if last_ver and not last_ver.get("progress_made") and last_ver.get("retry_suggested"):
        no_progress_hint = "Last tool step did not make progress; consider a different approach or reply (reason). "
    if state.get("environment_aligned") is False:
        no_progress_hint += "Environment check did not confirm success; consider different approach or reply (reason). "
    # North Star §8: failure awareness (structured hint stringified here)
    rh = state.get("recovery_hint")
    if rh and isinstance(rh, dict):
        no_progress_hint += _format_recovery_hint_for_prompt(rh)
    consecutive = state.get("consecutive_no_progress", 0)
    if consecutive >= 2:
        shift_count = state.get("strategy_shift_count", 0)
        if shift_count == 1:
            last_tool = state.get("last_tool_used") or "unknown"
            no_progress_hint += (
                f"Strategy shift: try a different class of action. Avoid repeating the same tool (last was {last_tool}). "
                "Prefer high-impact inspection tools: read_file, grep_code, git_diff. "
            )
        else:
            no_progress_hint += "Several steps made no progress; consider replying (reason) to explain or suggest next steps. "

    reframe_candidate = (
        consecutive >= 2
        and state.get("strategy_shift_count", 0) >= 2
        and not state.get("objective_complete")
    )
    reframe_instruction = ""
    if reframe_candidate:
        reframe_instruction = (
            "Alternatively propose a revised objective to solve the right problem: "
            'add "revised_objective": "one clear sentence" to your JSON. '
            "Prefer reframing toward higher-impact, achievable objective. "
            "If you reframe, we will continue with the new objective. "
        )

    priority_context = ""
    prev_priority = state.get("priority_level")
    prev_risk = state.get("risk_estimate")
    if prev_priority or prev_risk:
        priority_context = f"Previous step priority: {prev_priority or 'unknown'}. "
        if prev_priority == "low":
            priority_context += "Avoid low-impact retries; prefer higher-impact pivots or reply (reason). "
        else:
            priority_context += "Prefer high-impact pivots. "
        if prev_risk and "high" in str(prev_risk).lower():
            priority_context += "Risk was high; bias toward safer paths (read_file, list_dir, grep_code, git_*). "
        elif prev_priority:
            priority_context += "When risk is high prefer safer paths (read, inspect). "

    tools_list = ", ".join(sorted(_VALID_TOOLS - {"reason"}))
    prompt = (
        f"{aspect_block}"
        f"{bias_hint}"
        f"{prompt_context}"
        f"{priority_context}"
        f"{no_progress_hint}"
        f"{reframe_instruction}"
        "Choose one: run one tool to make progress, or reply (reason). "
        f"Tools: {tools_list}. "
        "Output exactly one JSON line, no other text. "
        'Format: {"action":"tool","tool":"read_file","priority_level":"high"} or {"action":"reason","objective_complete":true}. '
        "Include priority_level: \"low\" or \"medium\" or \"high\" for the chosen action. "
        "Optionally impact_estimate, effort_estimate, risk_estimate (brief). "
        "Use objective_complete true only when you have enough to answer.\n"
    )
    try:
        cfg = runtime_safety.load_config()
        max_tok = 120 if reframe_candidate else 80
        retry_prompt_suffix = " Output only a single JSON line, no other text or commentary.\n"
        for attempt in range(2):
            out = run_completion(
                prompt + (retry_prompt_suffix if attempt > 0 else ""),
                max_tokens=max_tok,
                temperature=0.1,
                stream=False,
            )
            if isinstance(out, dict):
                text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
            else:
                text = ""
            text = (text or "").strip()
            decision = _parse_decision(text, _VALID_TOOLS)
            if decision is not None:
                return decision
        return None
    except Exception as e:
        logger.debug("llm_decision parse failed: %s", e)
        return None


def classify_intent(goal: str) -> str:
    g = goal.lower()

    if any(kw in g for kw in ("create file", "write file", "save file", "create a file")):
        return "write_file"
    if any(kw in g for kw in ("read file", "open file", "show file", "content of", "contents of")):
        return "read_file"
    if any(kw in g for kw in ("list dir", "list files", "list folder", "ls ", "show files", "what files")):
        return "list_dir"
    if any(kw in g for kw in ("git status",)):
        return "git_status"
    if any(kw in g for kw in ("git diff",)):
        return "git_diff"
    if any(kw in g for kw in ("git log",)):
        return "git_log"
    if any(kw in g for kw in ("git branch", "current branch")):
        return "git_branch"
    if any(kw in g for kw in ("grep ", "search code", "find in code", "grep_code")):
        return "grep_code"
    if any(kw in g for kw in ("glob ", "find files", "glob files")):
        return "glob_files"
    if any(kw in g for kw in ("run python", "execute python", "run script", "run_python")):
        return "run_python"
    if any(kw in g for kw in ("apply patch", "patch file", "apply_patch")):
        return "apply_patch"
    if any(kw in g for kw in ("fetch url", "fetch http", "browse ", "scrape ", "look up http", "fetch_url", "http://", "https://")):
        return "fetch_url"
    if any(kw in g for kw in ("run ", "execute ", "install ", "npm ", "pip ", "python ", "bash ", "cmd ")):
        return "shell"

    return "reason"


def _extract_path(goal: str) -> str:
    """Pull a file/dir path from the goal text (very simple heuristic)."""
    words = goal.split()
    for w in words:
        if (":" in w or "/" in w or "\\" in w) and not w.startswith("http"):
            return w.strip("\"',")
    return ""


def _extract_file_and_content(goal: str):
    if "with content" in goal:
        parts = goal.split("with content", 1)
        left = parts[0]
        content = parts[1].strip()
        words = left.split()
        for w in words:
            if ":" in w or "\\" in w:
                return w.strip("\"',"), content
    return None, None


def _extract_shell_argv(goal: str):
    """Very simple: find a quoted command or treat the last part as the command."""
    import shlex
    try:
        # Try to find a quoted command block
        for delim in ('"', "'"):
            if delim in goal:
                inner = goal.split(delim)[1]
                return shlex.split(inner)
    except Exception:
        pass
    # Fallback: strip common preambles
    for prefix in ("run", "execute", "install", "please run", "please execute"):
        if goal.lower().startswith(prefix):
            remainder = goal[len(prefix):].strip()
            try:
                return shlex.split(remainder)
            except Exception:
                return remainder.split()
    return goal.split()


def _save_outcome_memory(state: dict) -> None:
    """
    After successful multi-step runs, store a short semantic summary (what was done, what worked).
    Uses existing learnings/memory; avoids logs and noise.
    """
    steps = state.get("steps") or []
    tool_steps = [s for s in steps if s.get("action") and s["action"] != "reason"]
    if not tool_steps or state.get("status") != "finished":
        return
    objective = (state.get("objective") or state.get("original_goal") or "")[:200]
    actions = ", ".join(s["action"] for s in tool_steps[:5])
    facts = []
    for s in tool_steps:
        r = s.get("result") or {}
        if isinstance(r, dict) and r.get("ok"):
            if r.get("path"):
                facts.append(f"path:{r.get('path', '')[:80]}")
            if r.get("entries") and isinstance(r["entries"], list):
                facts.append(f"listed {len(r['entries'])} items")
    summary = f"Objective: {objective}. Did: {actions}. " + (" ".join(facts[:3]) if facts else "Completed.")
    if len(summary) > 400:
        summary = summary[:397] + "..."
    try:
        from jinx.memory.db import save_learning
        save_learning(content=summary, kind="outcome")
    except Exception as e:
        logger.debug("outcome memory save failed: %s", e)


def _format_steps(steps: list) -> str:
    """Format tool steps for feeding back into the next iteration or reason prompt."""
    if not steps:
        return ""
    lines = []
    for s in steps:
        action = s.get("action", "")
        result = s.get("result", {})
        if isinstance(result, dict):
            summary = result.get("content") or result.get("output") or result.get("matches")
            if summary is None and result.get("entries"):
                summary = str(result["entries"])[:300]
            if summary is None:
                summary = "ok" if result.get("ok") else result.get("error", str(result)[:200])
            if isinstance(summary, (list, dict)):
                summary = str(summary)[:400]
            lines.append(f"{action}: {str(summary)[:600]}")
        else:
            lines.append(f"{action}: {str(result)[:600]}")
    return "\n".join(lines)


def _extract_patch_text(goal: str) -> str:
    """Extract only the patch/diff body from the message, not instructions or extra text."""
    g = (goal or "").strip()
    if not g:
        return g
    # Fenced block: ```patch ... ``` or ```diff ... ``` or ``` ... ```
    for marker in ("```patch", "```diff", "``` unified", "```"):
        if marker in g:
            parts = g.split(marker, 2)
            if len(parts) >= 3:
                body = parts[1].strip()
                if body:
                    return body
    # Unified diff: starts with --- or diff --git or Index:
    for line in g.splitlines():
        stripped = line.strip()
        if stripped.startswith("--- ") or stripped.startswith("diff --git") or stripped.startswith("Index:"):
            return g[g.find(line) :].strip()
    return g


def autonomous_run(
    goal: str,
    context: str = "",
    workspace_root: str = "",
    allow_write: bool = False,
    allow_run: bool = False,
    conversation_history: list = None,
    aspect_id: str = "",
    show_thinking: bool = False,
    stream_final: bool = False,
    ux_state_queue: queue.Queue | None = None,
    research_mode: bool = False,
) -> dict:
    with llm_serialize_lock:
        return _autonomous_run_impl(
            goal, context, workspace_root, allow_write, allow_run,
            conversation_history, aspect_id, show_thinking, stream_final,
            ux_state_queue, research_mode,
        )


def _autonomous_run_impl(
    goal: str,
    context: str,
    workspace_root: str,
    allow_write: bool,
    allow_run: bool,
    conversation_history: list,
    aspect_id: str,
    show_thinking: bool,
    stream_final: bool,
    ux_state_queue: queue.Queue | None,
    research_mode: bool,
) -> dict:
    cfg = runtime_safety.load_config()
    # Gate once at entry only: avoid refusing mid-run when our own LLM/embedder spiked CPU
    if system_overloaded():
        time.sleep(2.0)
        if system_overloaded():
            active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
            return {
                "status": "system_busy",
                "steps": [],
                "aspect": active_aspect.get("id", "layla"),
                "aspect_name": active_aspect.get("name", "Layla"),
                "refused": False,
                "refusal_reason": "",
                "ux_states": [],
                "memory_influenced": [],
            }
    active_aspect = orchestrator.select_aspect(goal, force_aspect=aspect_id)
    # Memory attribution: did we inject learnings or semantic recall into this run?
    memory_influenced = []
    if _load_learnings(aspect_id=active_aspect.get("id") or "").strip():
        memory_influenced.append("learnings")
    if goal and _semantic_recall(goal, k=cfg.get("semantic_k", 5)).strip():
        memory_influenced.append("semantic_recall")
    state = {
        "goal": goal,
        "original_goal": goal,
        "objective": goal,
        "objective_complete": False,
        "depth": 0,
        "steps": [],
        "status": "running",
        "start_time": time.time(),
        "tool_calls": 0,
        "aspect": active_aspect.get("id", "layla"),
        "aspect_name": active_aspect.get("name", "Layla"),
        "refused": False,
        "refusal_reason": "",
        "last_verification": None,
        "consecutive_no_progress": 0,
        "environment_aligned": None,
        "last_tool_used": None,
        "strategy_shift_count": 0,
        "priority_level": None,
        "impact_estimate": None,
        "effort_estimate": None,
        "risk_estimate": None,
        "ux_states": [],
        "memory_influenced": memory_influenced,
        "cited_knowledge_sources": [],
        "sub_goals": _decompose_goal(goal),
        "reflection_pending": False,
        "reflection_asked": False,
    }
    if research_mode:
        state["research_lab_root"] = str(RESEARCH_LAB_ROOT)
    workspace = (str(workspace_root).strip() if workspace_root else "") or runtime_safety.load_config().get("sandbox_root", r"C:\github")
    if research_mode:
        max_tool_calls = cfg.get("research_max_tool_calls", 20)
        max_runtime = cfg.get("research_max_runtime_seconds", 120)
    else:
        max_tool_calls = cfg.get("max_tool_calls", 5)
        max_runtime = cfg.get("max_runtime_seconds", 20)
    temperature = cfg.get("temperature", 0.2)

    if research_mode and workspace:
        set_effective_sandbox(workspace)
    while state["depth"] < 5:
        if time.time() - state["start_time"] > max_runtime:
            state["status"] = "timeout"
            break

        if state["tool_calls"] >= max_tool_calls:
            state["status"] = "tool_limit"
            break

        if state.get("consecutive_no_progress", 0) >= 2 and not state.get("objective_complete"):
            state["strategy_shift_count"] = state.get("strategy_shift_count", 0) + 1
            _emit_ux(state, ux_state_queue, UX_STATE_CHANGING_APPROACH)

        _emit_ux(state, ux_state_queue, UX_STATE_THINKING)
        decision = _llm_decision(
            goal, state, context, active_aspect, show_thinking, conversation_history or []
        )
        if decision:
            state["objective_complete"] = bool(decision.get("objective_complete", False))
            state["priority_level"] = decision.get("priority_level") or "medium"
            state["impact_estimate"] = decision.get("impact_estimate")
            state["effort_estimate"] = decision.get("effort_estimate")
            state["risk_estimate"] = decision.get("risk_estimate")
            if decision.get("action") == "reason" or state["objective_complete"]:
                intent = "reason"
            elif decision.get("action") == "tool" and decision.get("tool") and decision["tool"] in _VALID_TOOLS:
                intent = decision["tool"]
            else:
                intent = classify_intent(goal)
        else:
            intent = classify_intent(goal)

        consecutive = state.get("consecutive_no_progress", 0)
        objective_complete = state.get("objective_complete", False)
        revised_objective = decision.get("revised_objective") if decision else None
        if revised_objective and isinstance(revised_objective, str) and revised_objective.strip():
            _emit_ux(state, ux_state_queue, UX_STATE_REFRAMING_OBJECTIVE)
            state["reflection_pending"] = True
            state["objective"] = revised_objective.strip()
            state["consecutive_no_progress"] = 0
            state["strategy_shift_count"] = 0
            goal = state["objective"]
            continue
        if consecutive >= 2 and not objective_complete and state.get("strategy_shift_count", 0) >= 2:
            _emit_ux(state, ux_state_queue, UX_STATE_CHANGING_APPROACH)
            state["reflection_pending"] = True
            intent = "reason"

        # ------------------------------------------------
        # WRITE FILE
        # ------------------------------------------------
        if intent == "write_file":
            path, content = _extract_file_and_content(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            lab_root = state.get("research_lab_root") or ""
            if lab_root and workspace and not Path(path).is_absolute():
                path = str(Path(workspace) / path)
            if lab_root:
                if not _path_under_lab(path, lab_root):
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "write_file",
                        "result": {"ok": False, "reason": "research_lab_only", "message": "Writes allowed only inside .research_lab"},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                state["tool_calls"] += 1
                result = TOOLS["write_file"]["fn"](path=path, content=content)
                runtime_safety.log_execution("write_file", {"path": path})
                state["steps"].append({"action": "write_file", "result": result})
                state["last_tool_used"] = "write_file"
                _run_verification_after_tool(state, "write_file", result, workspace)
                _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_write or not runtime_safety.require_approval("write_file"):
                approval_id = _write_pending("write_file", {"path": path, "content": content})
                state["steps"].append({
                    "action": "write_file",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break

            target = Path(path)
            if runtime_safety.is_protected(target):
                if not runtime_safety.backup_file(target):
                    state["steps"].append({
                        "action": "write_file",
                        "result": {"ok": False, "reason": "backup_failed"},
                    })
                    state["status"] = "finished"
                    break

            state["tool_calls"] += 1
            result = TOOLS["write_file"]["fn"](path=path, content=content)
            runtime_safety.log_execution("write_file", {"path": path})
            state["steps"].append({"action": "write_file", "result": result})
            state["last_tool_used"] = "write_file"
            _run_verification_after_tool(state, "write_file", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # READ FILE
        # ------------------------------------------------
        if intent == "read_file":
            path = _extract_path(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            probe = _maybe_preprobe_file(state, path)
            if not _apply_probe_guidance(state, "read_file", path, probe):
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            state["tool_calls"] += 1
            result = TOOLS["read_file"]["fn"](path=path)
            runtime_safety.log_execution("read_file", {"path": path})
            state["steps"].append({"action": "read_file", "result": result})
            state["last_tool_used"] = "read_file"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # LIST DIR
        # ------------------------------------------------
        if intent == "list_dir":
            path = _extract_path(goal) or workspace
            state["tool_calls"] += 1
            result = TOOLS["list_dir"]["fn"](path=path)
            runtime_safety.log_execution("list_dir", {"path": path})
            state["steps"].append({"action": "list_dir", "result": result})
            state["last_tool_used"] = "list_dir"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # GIT STATUS / DIFF / LOG / BRANCH
        # ------------------------------------------------
        if intent == "git_status":
            state["tool_calls"] += 1
            result = TOOLS["git_status"]["fn"](repo=workspace)
            runtime_safety.log_execution("git_status", {"repo": workspace})
            state["steps"].append({"action": "git_status", "result": result})
            state["last_tool_used"] = "git_status"
            _run_verification_after_tool(state, "git_status", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_diff":
            state["tool_calls"] += 1
            result = TOOLS["git_diff"]["fn"](repo=workspace)
            runtime_safety.log_execution("git_diff", {"repo": workspace})
            state["steps"].append({"action": "git_diff", "result": result})
            state["last_tool_used"] = "git_diff"
            _run_verification_after_tool(state, "git_diff", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_log":
            state["tool_calls"] += 1
            result = TOOLS["git_log"]["fn"](repo=workspace, n=10)
            runtime_safety.log_execution("git_log", {"repo": workspace})
            state["steps"].append({"action": "git_log", "result": result})
            state["last_tool_used"] = "git_log"
            _run_verification_after_tool(state, "git_log", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "git_branch":
            state["tool_calls"] += 1
            result = TOOLS["git_branch"]["fn"](repo=workspace)
            runtime_safety.log_execution("git_branch", {"repo": workspace})
            state["steps"].append({"action": "git_branch", "result": result})
            state["last_tool_used"] = "git_branch"
            _run_verification_after_tool(state, "git_branch", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # GREP / GLOB
        # ------------------------------------------------
        if intent == "grep_code":
            import shlex as _shlex
            parts = goal.split()
            pattern = parts[-1] if parts else ""
            grep_path = workspace
            maybe_path = _extract_path(goal)
            # If user supplied a concrete file path, use it; probe it once for awareness.
            if maybe_path and Path(maybe_path).suffix:
                probe = _maybe_preprobe_file(state, maybe_path)
                _apply_probe_guidance(state, "grep_code", maybe_path, probe)
                grep_path = maybe_path
            state["tool_calls"] += 1
            result = TOOLS["grep_code"]["fn"](pattern=pattern, path=grep_path)
            runtime_safety.log_execution("grep_code", {"pattern": pattern, "path": grep_path})
            state["steps"].append({"action": "grep_code", "result": result})
            state["last_tool_used"] = "grep_code"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "glob_files":
            parts = goal.split()
            pattern = parts[-1] if parts else "*"
            state["tool_calls"] += 1
            result = TOOLS["glob_files"]["fn"](pattern=pattern, root=workspace)
            runtime_safety.log_execution("glob_files", {"pattern": pattern, "root": workspace})
            state["steps"].append({"action": "glob_files", "result": result})
            state["last_tool_used"] = "glob_files"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # RUN PYTHON
        # ------------------------------------------------
        if intent == "run_python":
            lab_root = state.get("research_lab_root") or ""
            if lab_root:
                if not allow_run:
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "run_python",
                        "result": {"ok": False, "reason": "disabled_in_research", "message": "run_python is disabled for this research stage. Use read_file, list_dir, grep_code instead."},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                if not _path_under_lab(workspace, lab_root):
                    state["tool_calls"] += 1
                    state["steps"].append({
                        "action": "run_python",
                        "result": {"ok": False, "reason": "research_lab_only", "message": "run_python allowed only with cwd inside .research_lab"},
                    })
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
                code = goal
                state["tool_calls"] += 1
                result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
                runtime_safety.log_execution("run_python", {"cwd": workspace})
                state["steps"].append({"action": "run_python", "result": result})
                state["last_tool_used"] = "run_python"
                _run_verification_after_tool(state, "run_python", result, workspace)
                _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            if not allow_run or not runtime_safety.require_approval("run_python"):
                approval_id = _write_pending("run_python", {"code": goal, "cwd": workspace})
                state["steps"].append({
                    "action": "run_python",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            code = goal
            state["tool_calls"] += 1
            result = TOOLS["run_python"]["fn"](code=code, cwd=workspace)
            runtime_safety.log_execution("run_python", {"cwd": workspace})
            state["steps"].append({"action": "run_python", "result": result})
            state["last_tool_used"] = "run_python"
            _run_verification_after_tool(state, "run_python", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # APPLY PATCH
        # ------------------------------------------------
        if intent == "apply_patch":
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "apply_patch",
                    "result": {"ok": False, "reason": "not_allowed_in_research", "message": "apply_patch not allowed in research missions"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            path = _extract_path(goal)
            patch_body = _extract_patch_text(goal)
            if path:
                probe = _maybe_preprobe_file(state, path)
                if not _apply_probe_guidance(state, "apply_patch", path, probe):
                    goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                    continue
            if not allow_write or not runtime_safety.require_approval("apply_patch"):
                approval_id = _write_pending("apply_patch", {"original_path": path or "", "patch_text": patch_body})
                state["steps"].append({
                    "action": "apply_patch",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            if not path:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            result = TOOLS["apply_patch"]["fn"](original_path=path, patch_text=patch_body)
            runtime_safety.log_execution("apply_patch", {"path": path})
            state["steps"].append({"action": "apply_patch", "result": result})
            state["last_tool_used"] = "apply_patch"
            _run_verification_after_tool(state, "apply_patch", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # FETCH URL
        # ------------------------------------------------
        if intent == "fetch_url":
            words = goal.split()
            url = next((w for w in words if w.startswith("http")), "")
            if not url:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            result = TOOLS["fetch_url"]["fn"](url=url)
            runtime_safety.log_execution("fetch_url", {"url": url})
            state["steps"].append({"action": "fetch_url", "result": result})
            state["last_tool_used"] = "fetch_url"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # SHELL
        # ------------------------------------------------
        if intent == "shell":
            if state.get("research_lab_root"):
                state["tool_calls"] += 1
                state["steps"].append({
                    "action": "shell",
                    "result": {"ok": False, "reason": "not_allowed_in_research", "message": "shell not allowed in research missions"},
                })
                goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
                continue
            argv = _extract_shell_argv(goal)
            if not argv:
                state["status"] = "parse_failed"
                break
            if not allow_run or not runtime_safety.require_approval("shell"):
                approval_id = _write_pending("shell", {"argv": argv, "cwd": workspace})
                state["steps"].append({
                    "action": "shell",
                    "result": {
                        "ok": False,
                        "reason": "approval_required",
                        "approval_id": approval_id,
                        "message": f"Run: layla approve {approval_id}",
                    },
                })
                state["status"] = "finished"
                break
            state["tool_calls"] += 1
            result = TOOLS["shell"]["fn"](argv=argv, cwd=workspace)
            runtime_safety.log_execution("shell", {"argv": argv, "cwd": workspace})
            state["steps"].append({"action": "shell", "result": result})
            state["last_tool_used"] = "shell"
            _run_verification_after_tool(state, "shell", result, workspace)
            _emit_ux(state, ux_state_queue, UX_STATE_VERIFYING)
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # PROJECT CONTEXT (agent-readable, agent-updatable)
        # ------------------------------------------------
        if intent == "get_project_context":
            state["tool_calls"] += 1
            result = TOOLS["get_project_context"]["fn"]()
            state["steps"].append({"action": "get_project_context", "result": result})
            state["last_tool_used"] = "get_project_context"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        if intent == "update_project_context":
            args = decision.get("args") or {} if decision else {}
            state["tool_calls"] += 1
            result = TOOLS["update_project_context"]["fn"](
                project_name=args.get("project_name", ""),
                domains=args.get("domains"),
                key_files=args.get("key_files"),
                goals=args.get("goals", ""),
                lifecycle_stage=args.get("lifecycle_stage", ""),
            )
            state["steps"].append({"action": "update_project_context", "result": result})
            state["last_tool_used"] = "update_project_context"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # FILE INTENT (read-only)
        # ------------------------------------------------
        if intent == "understand_file":
            path = (decision.get("args") or {}).get("path") if decision else None
            if not path:
                path = _extract_path(goal)
            if not path:
                state["status"] = "parse_failed"
                break
            state["tool_calls"] += 1
            result = TOOLS["understand_file"]["fn"](path=path)
            state["steps"].append({"action": "understand_file", "result": result})
            state["last_tool_used"] = "understand_file"
            goal = state["original_goal"] + "\n\n[Tool results so far]:\n" + _format_steps(state["steps"])
            continue

        # ------------------------------------------------
        # REASONING
        # ------------------------------------------------
        if intent == "reason":
            if stream_final:
                state["status"] = "stream_pending"
                state["goal_for_stream"] = goal
                return state
            head = _build_system_head(goal=goal, aspect=active_aspect, workspace_root=workspace, sub_goals=state.get("sub_goals"), state=state)

            # Inject conversation history (sanitize assistant messages that are echoed instructions)
            convo_block = ""
            try:
                convo_turns = max(0, int(cfg.get("convo_turns", 0)))
            except (TypeError, ValueError):
                convo_turns = 0
            if convo_turns > 0 and conversation_history:
                name = active_aspect.get("name", "Layla")
                turns = conversation_history[-convo_turns:]
                lines = []
                for t in turns:
                    role = t.get("role", "")
                    content_t = (t.get("content") or "")[:300].strip()
                    if role == "user":
                        lines.append(f"User: {content_t}")
                    else:
                        if "system is under load" in content_t.lower():
                            content_t = "I couldn't reply just then."
                        elif (content_t.startswith("[") and "You are" in content_t) or ("you are layla" in content_t.lower() and ("use the identity" in content_t.lower() or "rules below" in content_t.lower())):
                            content_t = _SANITIZED_PLACEHOLDER
                        elif _is_junk_reply(content_t):
                            content_t = _SANITIZED_PLACEHOLDER
                        lines.append(f"{name}: {content_t}")
                convo_block = "\n".join(lines)

            # Deliberation or standard prompt
            deliberate = show_thinking or orchestrator.should_deliberate(goal, active_aspect)
            if deliberate:
                prompt = orchestrator.build_deliberation_prompt(
                    message=goal,
                    active_aspect=active_aspect,
                    context=_enrich_deliberation_context(context),
                )
                if head:
                    prompt = head + "\n\n" + prompt
                if convo_block:
                    prompt = prompt + f"\n\nRecent conversation:\n{convo_block}"
            else:
                prompt = orchestrator.build_standard_prompt(
                    message=goal,
                    aspect=active_aspect,
                    context=context,
                    head=head,
                    convo_block=convo_block,
                )

            max_tok = cfg.get("completion_max_tokens", 256)
            out = run_completion(prompt, max_tokens=max_tok, temperature=temperature, stream=False)
            if isinstance(out, str):
                out = {"choices": [{"text": out}]}
            if isinstance(out, dict):
                text = (out.get("choices") or [{}])[0].get("text") or (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            else:
                text = ""
            text = (text or "").strip()
            text = truncate_at_next_user_turn(text)

            # Strip when model echoes the system head (e.g. "You are Layla. Use the identity..." or "nyou are Layla...")
            # Normalize leading junk (e.g. "n") so we detect the echo
            if text and text[0].lower() == "n" and len(text) > 4 and text[1:].strip().lower().startswith("you are layla"):
                text = text[1:].strip()
            paragraphs = text.split("\n\n")
            while paragraphs and paragraphs[0].strip():
                first = paragraphs[0].strip().lower()
                if first.startswith("you are layla") and ("use the identity" in first or "rules below" in first):
                    paragraphs.pop(0)
                else:
                    break
            text = "\n\n".join(paragraphs).strip()

            # Strip all echoed "[NAME] (You are...)" blocks (no "). " required; repeat until clean)
            import re as _re_echo
            # Match "[NAME] (You are ..." until "). " or next echo or "assistant:" or "\n\n" or end
            _echo_pat = _re_echo.compile(
                r"\s*\[[\w\s]+\]\s*\(You are[\s\S]*?(?=\)\.\s|\s*\[[\w\s]+\]\s*\(You are|\s*assistant\s*:|\n\n|\Z)",
                _re_echo.IGNORECASE | _re_echo.DOTALL,
            )
            for _ in range(20):
                prev = text
                text = _echo_pat.sub("", text, count=1).strip()
                if text == prev:
                    break
            # Strip leading "assistant: " if present
            if _re_echo.match(r"^\s*assistant\s*:\s*", text, _re_echo.IGNORECASE):
                text = _re_echo.sub(r"^\s*assistant\s*:\s*", "", text, count=1, flags=_re_echo.IGNORECASE).strip()
            # Strip repeated "assistant: I replied." so it never gets saved or shown
            for _ in range(50):
                prev = text
                text = _re_echo.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", text, count=1, flags=_re_echo.IGNORECASE).strip()
                if text == prev:
                    break
            if _is_junk_reply(text):
                text = ""
            # Strip line-by-line any remaining instruction-like lines at start
            lines = text.split("\n")
            while lines:
                first = lines[0].strip()
                if _re_echo.match(r"^\[[\w\s]+\]\s*\(?", first) or first.startswith("[ACTIVE ASPECT:"):
                    lines.pop(0)
                    continue
                if first.startswith("You are ") and ("aspect" in first.lower() or " the " in first[:80]):
                    lines.pop(0)
                    continue
                if first.lower() in ("assistant:", "assistant", "i replied."):
                    lines.pop(0)
                    continue
                if _is_junk_reply(first):
                    lines.pop(0)
                    continue
                break
            text = "\n".join(lines).strip()
            if not text or text.lower().strip() == "assistant:" or _is_junk_reply(text):
                text = ""

            # Refusal: if aspect can refuse and output starts with [REFUSED: ...], do not run tools
            refused = False
            refusal_reason = ""
            if active_aspect.get("can_refuse") or active_aspect.get("will_refuse"):
                import re as _re
                m = _re.match(r"^\s*\[REFUSED:\s*(.+?)\]\s*", text, _re.DOTALL | _re.IGNORECASE)
                if m:
                    refusal_reason = m.group(1).strip()
                    text = _re.sub(r"^\s*\[REFUSED:\s*.+?\]\s*", "", text, flags=_re.DOTALL | _re.IGNORECASE).strip()
                    refused = True
            state["refused"] = refused
            state["refusal_reason"] = refusal_reason

            # Reflection: once per run, after pivot/reframe, ask alignment (guidance only)
            if state.get("reflection_pending") and not state.get("reflection_asked") and text:
                text = text.rstrip() + "\n\nDoes this direction align with your goals?"
                state["reflection_asked"] = True

            # Earned title: if output ends with [EARNED_TITLE: ...], parse and save
            import re as _re_et
            et_match = _re_et.search(r"\[EARNED_TITLE:\s*(.+?)\]\s*$", text, _re_et.IGNORECASE)
            if et_match:
                from jinx.memory.db import save_earned_title
                try:
                    save_earned_title(active_aspect.get("id", ""), et_match.group(1).strip())
                except Exception:
                    pass
                text = _re_et.sub(r"\s*\[EARNED_TITLE:\s*.+?\]\s*$", "", text, flags=_re_et.IGNORECASE).strip()

            # Research mission: treat question-to-user as incomplete; continue until full output
            if state.get("research_lab_root") and not refused and state.get("status") != "timeout":
                if _research_response_asks_user(text):
                    goal = (
                        state["original_goal"]
                        + "\n\n[Tool results so far]:\n"
                        + _format_steps(state["steps"])
                        + "\n\n[System: Your last response asked the user a question. In this mission you must not ask questions. Produce the full structured output now: System Understanding, Weakness Map, Upgrade Opportunities, Lens Case Study, Suggested Roadmap.]"
                    )
                    continue

            state["steps"].append({
                "action": "reason",
                "result": text,
                "deliberated": deliberate,
                "aspect": active_aspect.get("id"),
            })
            state["status"] = "finished"

            # Save Echo aspect memory after a reply when active aspect is Echo
            if active_aspect.get("id") == "echo" and text and not refused:
                try:
                    summary = f"User said: {state['original_goal'][:100]}. I replied: {text[:200]}."
                    _db_save_aspect_memory("echo", summary)
                except Exception:
                    pass
            break

        state["depth"] += 1

    if state.get("status") == "finished":
        _save_outcome_memory(state)
        try:
            from jinx.memory.distill import run_distill_after_outcome
            run_distill_after_outcome(n=50)
        except Exception as e:
            logger.debug("distill after outcome failed: %s", e)
    if research_mode:
        set_effective_sandbox(None)
    return state

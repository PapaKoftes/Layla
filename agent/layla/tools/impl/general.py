"""Tool implementations — domain: general."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def get_project_context_tool() -> dict:
    """Return current project context (read-only for agent)."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import get_project_context
        return {"ok": True, **get_project_context()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def update_project_context_tool(
    project_name: str = "",
    domains: list | None = None,
    key_files: list | None = None,
    goals: str = "",
    lifecycle_stage: str = "",
    progress: str = "",
    blockers: str = "",
    last_discussed: str = "",
) -> dict:
    """Update project context. lifecycle_stage: idea|planning|prototype|iteration|execution|reflection. progress/blockers/last_discussed for companion recall."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import set_project_context
        set_project_context(
            project_name=project_name or "",
            domains=domains,
            key_files=key_files,
            goals=goals,
            lifecycle_stage=lifecycle_stage or "",
            progress=progress or "",
            blockers=blockers or "",
            last_discussed=last_discussed or "",
        )
        return {"ok": True, "message": "Project context updated."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_user_identity_tool() -> dict:
    """Return user/companion identity context (verbosity, humor, formality, response length, life narrative). Read-only."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import get_all_user_identity
        return {"ok": True, **get_all_user_identity()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def update_user_identity_tool(key: str, snapshot: str) -> dict:
    """Update user identity. key: verbosity|humor_tolerance|formality|response_length|life_narrative_summary. snapshot: description."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import USER_IDENTITY_KEYS, set_user_identity
        if key not in USER_IDENTITY_KEYS:
            return {"ok": False, "error": f"key must be one of: {USER_IDENTITY_KEYS}"}
        set_user_identity(key, snapshot)
        return {"ok": True, "message": f"User identity '{key}' updated."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def add_goal_tool(title: str, description: str = "", project_id: str = "") -> dict:
    """Add a long-term goal. project_id: optional project name to associate."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import add_goal
        gid = add_goal(title=title, description=description, project_id=project_id)
        return {"ok": True, "goal_id": gid, "message": "Goal added."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def add_goal_progress_tool(goal_id: str, note: str = "", progress_pct: float = 0) -> dict:
    """Record progress on a goal. progress_pct: 0-100."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import add_goal_progress
        add_goal_progress(goal_id, note=note, progress_pct=progress_pct)
        return {"ok": True, "message": "Progress recorded."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_active_goals_tool(project_id: str = "") -> dict:
    """Return active goals, optionally filtered by project_id."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import get_active_goals
        goals = get_active_goals(project_id=project_id)
        return {"ok": True, "goals": goals}
    except Exception as e:
        return {"ok": False, "error": str(e), "goals": []}

def structured_llm_task(
    instruction: str,
    schema_hint: str = "",
    max_tokens: int = 256,
) -> dict:
    """One bounded LLM step that should return JSON (OpenClaw llm-task style). No file writes."""
    import json as _json

    from services.llm_gateway import run_completion

    sh = (schema_hint or "").strip()
    prompt = (
        "You are a precise JSON generator. Output ONLY one JSON object, no markdown fences.\n"
        f"Task: {instruction}\n"
    )
    if sh:
        prompt += f"Expected shape / keys: {sh}\n"
    mt = min(512, max(32, int(max_tokens)))
    try:
        out = run_completion(prompt, max_tokens=mt, temperature=0.1, stream=False)
    except Exception as e:
        return {"ok": False, "error": f"LLM call failed: {e}"}
    text = ""
    if isinstance(out, dict):
        choices = out.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
    text = (text or "").strip()
    try:
        obj = _json.loads(text)
        return {"ok": True, "json": obj, "raw": text[:2000]}
    except Exception:
        return {"ok": True, "json": None, "raw": text[:4000], "parse_error": True}

def mcp_tools_call(
    mcp_server: str = "",
    tool_name: str = "",
    arguments: dict | None = None,
) -> dict:
    """Call one tool on a configured MCP stdio server (short session: initialize → tools/call)."""
    import runtime_safety
    from services.mcp_client import load_mcp_stdio_servers, mcp_session_call_tool

    cfg = runtime_safety.load_config()
    if not cfg.get("mcp_client_enabled"):
        return {
            "ok": False,
            "error": "mcp_client_enabled is false; enable it and configure mcp_stdio_servers in runtime_config.json",
        }
    specs = load_mcp_stdio_servers(cfg)
    name = (mcp_server or "").strip()
    tname = (tool_name or "").strip()
    if not name or not tname:
        return {"ok": False, "error": "mcp_server and tool_name are required"}
    spec = next((s for s in specs if s.name == name), None)
    if spec is None:
        return {
            "ok": False,
            "error": f"unknown MCP server {name!r}; add it to mcp_stdio_servers with a matching name",
        }
    out = mcp_session_call_tool(spec, tname, arguments)
    if out.get("ok"):
        return {"ok": True, "mcp": out.get("mcp"), "server": name, "tool": tname}
    return {"ok": False, "error": out.get("error", "mcp call failed"), "detail": out}

def mcp_list_mcp_tools(mcp_server: str = "") -> dict:
    """List tools advertised by a configured MCP stdio server (tools/list). Read-only discovery."""
    import runtime_safety
    from services.mcp_client import load_mcp_stdio_servers, mcp_session_list_tools

    cfg = runtime_safety.load_config()
    if not cfg.get("mcp_client_enabled"):
        return {
            "ok": False,
            "error": "mcp_client_enabled is false; enable it and configure mcp_stdio_servers in runtime_config.json",
        }
    specs = load_mcp_stdio_servers(cfg)
    name = (mcp_server or "").strip()
    if not name:
        return {"ok": False, "error": "mcp_server name is required"}
    spec = next((s for s in specs if s.name == name), None)
    if spec is None:
        return {
            "ok": False,
            "error": f"unknown MCP server {name!r}; add it to mcp_stdio_servers with a matching name",
        }
    out = mcp_session_list_tools(spec)
    if out.get("ok"):
        mcp = out.get("mcp") or {}
        tools = mcp.get("tools") if isinstance(mcp, dict) else None
        return {"ok": True, "server": name, "tools": tools if isinstance(tools, list) else [], "raw": mcp}
    return {"ok": False, "error": out.get("error", "mcp tools/list failed"), "detail": out}

def mcp_list_mcp_resources(mcp_server: str = "") -> dict:
    """List resources advertised by a configured MCP stdio server (resources/list). Read-only discovery."""
    import runtime_safety
    from services.mcp_client import load_mcp_stdio_servers, mcp_session_list_resources

    cfg = runtime_safety.load_config()
    if not cfg.get("mcp_client_enabled"):
        return {
            "ok": False,
            "error": "mcp_client_enabled is false; enable it and configure mcp_stdio_servers in runtime_config.json",
        }
    specs = load_mcp_stdio_servers(cfg)
    name = (mcp_server or "").strip()
    if not name:
        return {"ok": False, "error": "mcp_server name is required"}
    spec = next((s for s in specs if s.name == name), None)
    if spec is None:
        return {
            "ok": False,
            "error": f"unknown MCP server {name!r}; add it to mcp_stdio_servers with a matching name",
        }
    out = mcp_session_list_resources(spec)
    if out.get("ok"):
        mcp = out.get("mcp") or {}
        resources = mcp.get("resources") if isinstance(mcp, dict) else None
        return {
            "ok": True,
            "server": name,
            "resources": resources if isinstance(resources, list) else [],
            "raw": mcp,
        }
    return {"ok": False, "error": out.get("error", "mcp resources/list failed"), "detail": out}

def mcp_read_mcp_resource(mcp_server: str = "", uri: str = "") -> dict:
    """Read one resource from a configured MCP stdio server (resources/read)."""
    import runtime_safety
    from services.mcp_client import load_mcp_stdio_servers, mcp_session_read_resource

    cfg = runtime_safety.load_config()
    if not cfg.get("mcp_client_enabled"):
        return {
            "ok": False,
            "error": "mcp_client_enabled is false; enable it and configure mcp_stdio_servers in runtime_config.json",
        }
    specs = load_mcp_stdio_servers(cfg)
    name = (mcp_server or "").strip()
    u = (uri or "").strip()
    if not name or not u:
        return {"ok": False, "error": "mcp_server and uri are required"}
    spec = next((s for s in specs if s.name == name), None)
    if spec is None:
        return {
            "ok": False,
            "error": f"unknown MCP server {name!r}; add it to mcp_stdio_servers with a matching name",
        }
    out = mcp_session_read_resource(spec, u)
    if out.get("ok"):
        return {"ok": True, "server": name, "uri": u, "mcp": out.get("mcp")}
    return {"ok": False, "error": out.get("error", "mcp resources/read failed"), "detail": out}

def mcp_operator_auth_hint() -> dict:
    """
    Discoverability: Layla does not perform OAuth inside the agent. Operators authenticate
    with each MCP server (CLI, browser, env) then configure mcp_stdio_servers in runtime_config.
    """
    return {
        "ok": True,
        "in_agent_oauth": False,
        "message": (
            "Authenticate with your MCP server using its documented flow (often a CLI login or browser). "
            "Then set mcp_client_enabled and mcp_stdio_servers (name, command, args) in runtime_config.json. "
            "Use mcp_list_mcp_tools / mcp_tools_call after the server process can start authenticated."
        ),
        "see_also": "docs/CCUNPACKED_ALIGNMENT.md (MCP / OAuth row), agent/runtime_config.example.json",
    }

def notebook_read_cells(path: str, max_cells: int = 80) -> dict:
    """Return code/markdown cell sources from a .ipynb (nbformat). Requires: pip install nbformat."""
    target = Path(path).expanduser().resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if target.suffix.lower() != ".ipynb":
        return {"ok": False, "error": "Expected a .ipynb notebook path"}
    if not target.is_file():
        return {"ok": False, "error": "File not found"}
    try:
        import nbformat
    except ImportError:
        return {"ok": False, "error": "nbformat not installed; pip install nbformat"}
    try:
        nb = nbformat.read(str(target), as_version=4)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    cells_out: list[dict] = []
    for i, cell in enumerate(nb.cells):
        if i >= max(1, min(int(max_cells), 200)):
            break
        ct = getattr(cell, "cell_type", "") or ""
        src = getattr(cell, "source", "") or ""
        if not isinstance(src, str):
            src = str(src)
        cells_out.append({"index": i, "cell_type": ct, "source": src[:8000]})
    return {"ok": True, "path": str(target), "n_cells": len(nb.cells), "cells": cells_out}

def notebook_edit_cell(path: str, cell_index: int = 0, source: str = "") -> dict:
    """Replace source of one code/markdown cell in a .ipynb. Requires approval when writes are gated."""
    target = Path(path).expanduser().resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if target.suffix.lower() != ".ipynb":
        return {"ok": False, "error": "Expected a .ipynb notebook path"}
    if not target.is_file():
        return {"ok": False, "error": "File not found"}
    try:
        import nbformat
    except ImportError:
        return {"ok": False, "error": "nbformat not installed; pip install nbformat"}
    idx = int(cell_index)
    if idx < 0:
        return {"ok": False, "error": "cell_index must be >= 0"}
    try:
        nb = nbformat.read(str(target), as_version=4)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if idx >= len(nb.cells):
        return {"ok": False, "error": f"cell_index {idx} out of range (len={len(nb.cells)})"}
    nb.cells[idx].source = source or ""
    try:
        nbformat.write(nb, str(target))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": str(target), "cell_index": idx, "written": True}

def list_tools(filter_by: str = "", include_dangerous: bool = True) -> dict:
    """
    List all tools available to Layla with their descriptions, risk levels, and approval status.
    filter_by: keyword to filter by tool name or description (empty = return all)
    include_dangerous: if False, only shows safe tools
    """
    results = []
    for name, meta in TOOLS.items():
        if not include_dangerous and meta.get("dangerous"):
            continue
        fn = meta.get("fn")
        doc = (fn.__doc__ or "").strip().split("\n")[0][:120] if fn else ""
        if filter_by and filter_by.lower() not in name.lower() and filter_by.lower() not in doc.lower():
            continue
        results.append({
            "name": name,
            "description": doc,
            "dangerous": meta.get("dangerous", False),
            "require_approval": meta.get("require_approval", False),
            "risk_level": meta.get("risk_level", "low"),
        })
    return {
        "ok": True,
        "total": len(TOOLS),
        "shown": len(results),
        "filter": filter_by,
        "tools": sorted(results, key=lambda x: x["name"]),
    }

def tool_recommend(task: str) -> dict:
    """
    Given a task description, recommend the most relevant tools to use.
    Uses keyword matching + category heuristics.
    Example: tool_recommend("read a PDF and summarize it") → [read_pdf, fetch_article, save_note]
    """
    task_lower = task.lower()
    CATEGORY_KEYWORDS = {
        "file": ["read_file", "write_file", "list_dir", "file_info", "understand_file"],
        "pdf": ["read_pdf"],
        "docx word": ["read_docx"],
        "excel spreadsheet": ["read_excel", "read_csv"],
        "csv data table": ["read_csv", "read_excel", "sql_query"],
        "code python test pytest": ["python_ast", "grep_code", "run_python", "run_tests", "security_scan", "code_lint"],
        "code search": ["search_codebase", "grep_code", "glob_files", "python_ast"],
        "git commit diff push pull": ["git_status", "git_diff", "git_log", "git_add", "git_commit", "git_push", "git_pull", "git_stash", "git_revert", "git_clone"],
        "web search": ["ddg_search", "browser_search", "fetch_article", "wiki_search"],
        "research paper arxiv": ["arxiv_search", "wiki_search", "ddg_search"],
        "website crawl": ["crawl_site", "fetch_article", "browser_navigate"],
        "math equation": ["math_eval", "sympy_solve"],
        "image ocr": ["ocr_image", "describe_image"],
        "chart graph plot": ["plot_chart"],
        "sql database": ["sql_query", "schema_introspect"],
        "memory remember": ["save_note", "search_memories", "vector_search", "vector_store"],
        "checkpoint restore revert": ["list_file_checkpoints", "restore_file_checkpoint"],
        "chat export import jsonl": ["ingest_chat_export_to_knowledge"],
        "elasticsearch keyword learnings": ["memory_elasticsearch_search", "search_memories"],
        "security scan": ["security_scan"],
        "stock finance crypto": ["stock_data"],
        "nlp entities keywords": ["nlp_analyze"],
        "compress token context": ["context_compress", "count_tokens"],
        "translate sql query": ["generate_sql", "sql_query", "schema_introspect"],
        "workspace project": ["workspace_map", "project_discovery", "get_project_context"],
        "gcode dxf stl fabrication cad geometry": [
            "parse_gcode",
            "stl_mesh_info",
            "understand_file",
            "generate_gcode",
            "geometry_validate_program",
            "geometry_execute_program",
            "geometry_list_frameworks",
            "geometry_extract_machining_ir",
            "validate_fabrication_bundle",
            "cam_feed_speed_hint",
        ],
        "clipboard copy paste": ["clipboard_read", "clipboard_write"],
        "search replace refactor": ["search_replace", "rename_symbol", "grep_code"],
        "pip install package": ["pip_list", "pip_install"],
        "docker container": ["docker_ps", "docker_run"],
        "ci github pr issue": ["check_ci", "github_issues", "github_pr"],
        "webhook slack discord email": ["send_webhook", "send_email"],
        "log tail": ["tail_file", "read_file"],
        "format code black ruff": ["code_format"],
        "archive zip extract": ["extract_archive", "create_archive"],
        "uuid random password": ["uuid_generate", "random_string", "password_generate"],
        "disk process system": ["disk_usage", "process_list", "env_info"],
        "qr code": ["generate_qr"],
        "csv write export": ["write_csv", "read_csv"],
        "json schema": ["json_schema", "json_query"],
        "jwt token": ["jwt_decode"],
        "toml config": ["read_toml", "yaml_read"],
        "merge pdf": ["merge_pdf", "read_pdf"],
        "discord": ["discord_send", "send_webhook"],
        "calendar ics event": ["calendar_read", "calendar_add_event"],
        "database backup": ["db_backup", "sql_query", "schema_introspect"],
        "svg draw diagram": ["create_svg", "create_mermaid", "write_file"],
    }
    scores: dict = {}
    for category, tools in CATEGORY_KEYWORDS.items():
        for keyword in category.split():
            if keyword in task_lower:
                for tool in tools:
                    scores[tool] = scores.get(tool, 0) + 1

    # Also match tool names/descriptions directly
    for name, meta in TOOLS.items():
        fn = meta.get("fn")
        doc = (fn.__doc__ or "").lower() if fn else ""
        for word in task_lower.split():
            if len(word) > 3 and (word in name.lower() or word in doc):
                scores[name] = scores.get(name, 0) + 1

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:10]
    recommendations = []
    for name, score in ranked:
        if name in TOOLS:
            fn = TOOLS[name].get("fn")
            doc = (fn.__doc__ or "").strip().split("\n")[0][:100] if fn else ""
            recommendations.append({"tool": name, "relevance": score, "description": doc})

    return {"ok": True, "task": task, "recommendations": recommendations}

def image_resize(path: str, width: int = 0, height: int = 0, output_path: str = "", maintain_aspect: bool = True) -> dict:
    """
    Resize an image. If maintain_aspect=True, only one dimension needed — the other scales proportionally.
    output_path: where to save. Default: <original>_resized.<ext> in same directory.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    if not width and not height:
        return {"ok": False, "error": "Provide at least width or height"}
    try:
        from PIL import Image as PILImage
        with PILImage.open(str(target)) as img:
            orig_w, orig_h = img.size
            if maintain_aspect:
                if width and not height:
                    height = int(orig_h * width / orig_w)
                elif height and not width:
                    width = int(orig_w * height / orig_h)
            resized = img.resize((width, height), PILImage.LANCZOS)
        out = Path(output_path) if output_path else target.parent / (target.stem + "_resized" + target.suffix)
        if not inside_sandbox(out):
            out = target.parent / (target.stem + "_resized" + target.suffix)
        resized.save(str(out))
        return {"ok": True, "original": str(target), "output": str(out), "original_size": f"{orig_w}x{orig_h}", "new_size": f"{resized.width}x{resized.height}"}
    except ImportError:
        return {"ok": False, "error": "Pillow not installed: pip install Pillow"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def log_event(message: str, level: str = "info", context: dict | None = None) -> dict:
    """
    Write a structured log entry to agent/.governance/layla-events.log (JSON-lines).
    level: debug | info | warning | error | critical.
    context: optional dict of extra fields.
    """
    import json as _json

    from layla.time_utils import utcnow
    entry = {"ts": str(utcnow())[:19], "level": level.upper(), "message": message[:500], "context": context or {}}
    try:
        log_path = Path(__file__).resolve().parent.parent.parent / ".governance" / "layla-events.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry) + "\n")
    except Exception:
        pass
    return {"ok": True, "logged": entry}

def trace_last_run(n: int = 20) -> dict:
    """Return the last N entries from the audit log for debugging what the agent did."""
    import json as _json
    audit_path = Path(__file__).resolve().parent.parent.parent / ".governance" / "audit.log"
    if not audit_path.exists():
        return {"ok": False, "error": "No audit log found at agent/.governance/audit.log"}
    try:
        lines = audit_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except Exception:
                entries.append({"raw": line[:200]})
        return {"ok": True, "total_lines": len(lines), "showing_last": min(n, len(entries)), "entries": entries[-n:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_metrics(top_n: int = 15) -> dict:
    """Analyze audit log for tool usage statistics: call counts, approval rates, never-called tools."""
    import json as _json
    audit_path = Path(__file__).resolve().parent.parent.parent / ".governance" / "audit.log"
    call_counts: dict = {}
    approved, rejected, total = 0, 0, 0
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                entry = _json.loads(line)
                tool = entry.get("tool") or entry.get("action") or "unknown"
                call_counts[tool] = call_counts.get(tool, 0) + 1
                status = str(entry.get("action", "") or entry.get("status", "")).lower()
                if "approv" in status or status == "ok":
                    approved += 1
                elif "reject" in status or "deny" in status or "block" in status:
                    rejected += 1
            except Exception:
                pass
    top = sorted(call_counts.items(), key=lambda x: -x[1])[:top_n]
    never_called = [t for t in TOOLS if t not in call_counts]
    return {"ok": True, "total_log_entries": total, "approved_actions": approved, "rejected_actions": rejected, "top_tools": [{"tool": t, "calls": c} for t, c in top], "never_called": never_called[:25], "total_registered_tools": len(TOOLS)}

def stt_file(path: str, language: str = "en", model_size: str = "base") -> dict:
    """
    Transcribe an audio file (.wav, .mp3, .ogg, .flac, .m4a) using faster-whisper.
    language: ISO 639-1 code or empty for auto-detect. model_size: tiny|base|small|medium|large-v3.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from services.stt import transcribe_file
        result = transcribe_file(str(target), language=language or None)
        if isinstance(result, dict):
            return {"ok": True, "path": str(target), **result}
        return {"ok": True, "path": str(target), "text": str(result)}
    except Exception:
        pass
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(target), language=language or None)
        text = " ".join(s.text for s in segments)
        return {"ok": True, "path": str(target), "text": text.strip(), "language": info.language, "prob": round(info.language_probability, 3)}
    except ImportError:
        return {"ok": False, "error": "faster-whisper not installed: pip install faster-whisper"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tts_speak(text: str, voice: str = "af_heart", output_path: str = "") -> dict:
    """
    Synthesize speech and save as WAV. voice: kokoro-onnx voice ID (af_heart, af_sky, am_adam...).
    output_path: where to save (default: temp file). Returns path to WAV.
    """
    if not text.strip():
        return {"ok": False, "error": "Empty text"}
    import tempfile as _tmp
    import time as _time
    out = output_path or str(Path(_tmp.gettempdir()) / f"layla_tts_{int(_time.time())}.wav")
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from services.tts import speak_to_bytes
        wav_bytes = speak_to_bytes(text)
        if wav_bytes:
            p = Path(out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(wav_bytes)
            return {"ok": True, "output_path": out, "method": "kokoro-onnx", "chars": len(text)}
    except Exception:
        pass
    try:
        import pyttsx3 as _pyttsx3
        engine = _pyttsx3.init()
        engine.save_to_file(text, out)
        engine.runAndWait()
        return {"ok": True, "output_path": out, "method": "pyttsx3", "chars": len(text)}
    except ImportError:
        return {"ok": False, "error": "No TTS backend. Install kokoro-onnx or pyttsx3."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def crypto_prices(symbols: list | str, period: str = "1d") -> dict:
    """
    Real-time and historical crypto price data via yfinance.
    symbols: 'BTC' or ['BTC','ETH','SOL'] â€” auto-appends -USD if missing.
    period: 1d | 5d | 1mo | 3mo | 1y | max.
    """
    try:
        import yfinance as yf
        if isinstance(symbols, str):
            symbols = [symbols]
        results = {}
        for sym in symbols[:10]:
            s = sym.upper()
            if "-" not in s:
                s += "-USD"
            try:
                t = yf.Ticker(s)
                hist = t.history(period=period)
                if hist.empty:
                    results[s] = {"error": "No data"}
                    continue
                current = float(hist["Close"].iloc[-1])
                first = float(hist["Close"].iloc[0])
                results[s] = {"price_usd": round(current, 6), "change_pct": round((current - first) / first * 100, 2), "high": round(float(hist["High"].max()), 6), "low": round(float(hist["Low"].min()), 6), "volume_24h": int(hist["Volume"].iloc[-1]), "period": period}
            except Exception as e:
                results[s] = {"error": str(e)}
        return {"ok": True, "data": results}
    except ImportError:
        return {"ok": False, "error": "yfinance not installed: pip install yfinance"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def economic_indicators(series: str = "SP500", start_year: int = 2000) -> dict:
    """
    Fetch macroeconomic data. Common series: GDP, UNRATE, CPIAUCSL, FEDFUNDS, SP500, T10Y2Y, DEXUSEU.
    Uses pandas-datareader FRED if installed; falls back to yfinance proxies.
    """
    try:
        import datetime as _dt

        import pandas_datareader.data as _pdr
        df = _pdr.DataReader(series, "fred", _dt.datetime(start_year, 1, 1))
        data = df[series].dropna()
        recent = data.tail(20)
        return {"ok": True, "series": series, "source": "FRED", "observations": len(data), "latest_value": round(float(recent.iloc[-1]), 6) if len(recent) else None, "latest_date": str(recent.index[-1])[:10] if len(recent) else None, "history": [{"date": str(d)[:10], "value": round(float(v), 6)} for d, v in recent.items()]}
    except ImportError:
        pass
    except Exception:
        pass
    YF_MAP = {"SP500": "^GSPC", "DEXUSEU": "EURUSD=X", "DEXJPUS": "JPY=X", "GC=F": "GC=F", "CL=F": "CL=F"}
    yf_sym = YF_MAP.get(series.upper(), series)
    try:
        import yfinance as yf
        t = yf.Ticker(yf_sym)
        hist = t.history(period="1y")
        if not hist.empty:
            return {"ok": True, "series": series, "source": "yfinance", "current": round(float(hist["Close"].iloc[-1]), 4), "1y_change_pct": round(float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100), 2)}
    except Exception:
        pass
    return {"ok": False, "error": f"Series '{series}' needs pandas-datareader: pip install pandas-datareader. FRED series: GDP, UNRATE, CPIAUCSL, FEDFUNDS, T10Y2Y"}

def timestamp_convert(value: str | int | float, input_format: str = "auto", output_format: str = "iso") -> dict:
    """
    Convert between timestamp formats.
    input_format: auto | unix | unix_ms | strftime string
    output_format: iso | unix | human | strftime string
    """
    import datetime as _dt
    dt = None
    try:
        if input_format in ("auto", "unix"):
            try:
                f = float(str(value))
                dt = _dt.datetime.utcfromtimestamp(f if f < 1e12 else f/1000)
                input_format = "unix"
            except ValueError:
                pass
        if dt is None:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    dt = _dt.datetime.strptime(str(value), fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return {"ok": False, "error": f"Cannot parse '{value}'"}
        if output_format == "iso":
            result = dt.isoformat()
        elif output_format == "unix":
            result = int(dt.timestamp())
        elif output_format == "human":
            result = dt.strftime("%B %d, %Y at %H:%M UTC")
        else:
            result = dt.strftime(output_format)
        return {"ok": True, "input": str(value), "result": result, "utc_iso": dt.isoformat()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def string_transform(text: str, operations: list | str | None = None) -> dict:
    """
    Apply text transformations. operations: list or single string.
    Ops: upper, lower, title, capitalize, strip, slug, snake_case, camel_case, reverse,
    truncate_N, dedupe_lines, sort_lines, remove_empty_lines, extract_numbers,
    extract_emails, extract_urls, remove_punctuation, first_sentence
    """
    import re as _re
    if operations is None:
        operations = []
    if isinstance(operations, str):
        operations = [operations]
    result, applied = text, []
    for op in operations:
        op = op.strip().lower()
        try:
            if op == "upper":
                result = result.upper()
            elif op == "lower":
                result = result.lower()
            elif op == "title":
                result = result.title()
            elif op == "capitalize":
                result = result.capitalize()
            elif op == "strip":
                result = result.strip()
            elif op == "slug":
                result = _re.sub(r'[^a-z0-9]+', '-', result.lower().strip()).strip('-')
            elif op == "snake_case":
                result = _re.sub(r'[^\w]', '_', _re.sub(r'[\s\-]+', '_', result.lower())).strip('_')
            elif op == "camel_case":
                parts = _re.split(r'[\s_\-]+', result)
                result = parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
            elif op == "reverse":
                result = result[::-1]
            elif op.startswith("truncate_"):
                n = int(op.split("_")[1])
                result = result[:n] + ("..." if len(result) > n else "")
            elif op == "dedupe_lines":
                seen, lines = set(), []
                for line in result.splitlines():
                    if line not in seen:
                        seen.add(line)
                        lines.append(line)
                result = "\n".join(lines)
            elif op == "sort_lines":
                result = "\n".join(sorted(result.splitlines()))
            elif op == "remove_empty_lines":
                result = "\n".join(ln for ln in result.splitlines() if ln.strip())
            elif op == "first_sentence":
                m = _re.search(r'^.+?[.!?]', result)
                result = m.group(0) if m else result
            elif op == "extract_numbers":
                result = ", ".join(_re.findall(r'-?\d+\.?\d*', result))
            elif op == "extract_emails":
                result = ", ".join(_re.findall(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', result))
            elif op == "extract_urls":
                result = "\n".join(_re.findall(r'https?://[^\s<>"\']+', result))
            elif op == "remove_punctuation":
                result = _re.sub(r'[^\w\s]', '', result)
            else:
                applied.append(f"UNKNOWN:{op}")
                continue
            applied.append(op)
        except Exception:
            applied.append(f"ERROR:{op}")
    return {"ok": True, "result": result, "original_length": len(text), "result_length": len(result), "operations_applied": applied}

def geo_query(location: str, details: bool = True) -> dict:
    """
    Geocode a location to coordinates + geographic details.
    Uses geopy/Nominatim (pip install geopy) or public Nominatim REST API fallback.
    """
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="layla-agent/2.0")
        loc = geolocator.geocode(location, exactly_one=True, timeout=10, addressdetails=details, language="en")
        if not loc:
            return {"ok": False, "error": f"Not found: {location}"}
        result: dict = {"ok": True, "query": location, "display_name": loc.raw.get("display_name", ""), "lat": float(loc.latitude), "lon": float(loc.longitude)}
        if details and loc.raw.get("address"):
            addr = loc.raw["address"]
            result.update({"country": addr.get("country", ""), "country_code": addr.get("country_code", "").upper(), "state": addr.get("state", ""), "city": addr.get("city", addr.get("town", addr.get("village", "")))})
        if loc.raw.get("boundingbox"):
            bb = loc.raw["boundingbox"]
            result["bounding_box"] = {"south": float(bb[0]), "north": float(bb[1]), "west": float(bb[2]), "east": float(bb[3])}
        return result
    except ImportError:
        pass
    # Fallback: public REST API
    try:
        import json as _json
        import urllib.parse
        import urllib.request
        q = urllib.parse.quote(location)
        req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&addressdetails=1", headers={"User-Agent": "layla-agent/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
        if not data:
            return {"ok": False, "error": f"Not found: {location}"}
        d = data[0]
        addr = d.get("address", {})
        return {"ok": True, "query": location, "method": "nominatim-api", "display_name": d.get("display_name", ""), "lat": float(d["lat"]), "lon": float(d["lon"]), "country": addr.get("country", ""), "state": addr.get("state", ""), "city": addr.get("city", addr.get("town", ""))}
    except Exception as e:
        return {"ok": False, "error": f"geo_query failed (install geopy: pip install geopy): {e}"}

def map_url(center: str = "", lat: float = 0.0, lon: float = 0.0, zoom: int = 12, markers: list | None = None) -> dict:
    """
    Generate static map URLs centered on a location (auto-geocoded from name or lat/lon).
    Returns OpenStreetMap URL, embed HTML, and Geoapify static map URL.
    """
    if center and not (lat and lon):
        geo = geo_query(center, details=False)
        if geo.get("ok"):
            lat, lon = geo["lat"], geo["lon"]
        else:
            return {"ok": False, "error": f"Could not geocode: {center}"}
    if not (lat and lon):
        return {"ok": False, "error": "Provide center name or lat+lon"}
    osm = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"
    static = f"https://maps.geoapify.com/v1/staticmap?style=osm-bright&width=800&height=600&center=lonlat:{lon},{lat}&zoom={zoom}"
    embed = f'<iframe src="https://www.openstreetmap.org/export/embed.html?bbox={lon-0.05},{lat-0.05},{lon+0.05},{lat+0.05}&layer=mapnik&marker={lat},{lon}" width="800" height="500"></iframe>'
    return {"ok": True, "center": {"lat": lat, "lon": lon}, "zoom": zoom, "osm_url": osm, "static_map_url": static, "embed_html": embed}

def extract_frames(path: str, fps: float = 1.0, max_frames: int = 30, output_dir: str = "") -> dict:
    """
    Extract frames from a video at given fps. Requires ffmpeg binary in PATH.
    ffmpeg-python package (pip install ffmpeg-python) enables probe metadata.
    Falls back to ffmpeg CLI directly if package not installed.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    import tempfile as _tmp
    out_dir = Path(output_dir) if output_dir else Path(_tmp.gettempdir()) / f"frames_{target.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pattern = str(out_dir / "frame_%04d.png")
    try:
        import ffmpeg
        probe = ffmpeg.probe(str(target))
        duration = float(probe["format"].get("duration", 0))
        vi = next((s for s in probe["streams"] if s["codec_type"] == "video"), {})
        (ffmpeg.input(str(target)).filter("fps", fps=fps).output(out_pattern, vframes=max_frames).overwrite_output().run(quiet=True))
        frames = sorted(out_dir.glob("frame_*.png"))
        return {"ok": True, "path": str(target), "fps": fps, "duration_sec": round(duration, 2), "resolution": f"{vi.get('width',0)}x{vi.get('height',0)}", "frames_extracted": len(frames), "output_dir": str(out_dir), "frame_paths": [str(f) for f in frames]}
    except ImportError:
        pass
    try:
        subprocess.run(["ffmpeg", "-i", str(target), "-vf", f"fps={fps}", "-frames:v", str(max_frames), out_pattern, "-y"], capture_output=True, timeout=120, text=True, encoding="utf-8", errors="replace")
        frames = sorted(out_dir.glob("frame_*.png"))
        if frames:
            return {"ok": True, "path": str(target), "fps": fps, "frames_extracted": len(frames), "output_dir": str(out_dir), "frame_paths": [str(f) for f in frames]}
        return {"ok": False, "error": "ffmpeg produced no output. Ensure ffmpeg is installed and in PATH."}
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg not found. Install: https://ffmpeg.org/download.html and pip install ffmpeg-python"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def detect_scenes(path: str, threshold: float = 27.0) -> dict:
    """
    Detect scene cuts in a video. threshold: lower = more sensitive.
    Requires: pip install scenedetect[opencv]
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(target), ContentDetector(threshold=threshold))
        scene_list = [{"scene": i+1, "start_sec": round(s[0].get_seconds(), 3), "end_sec": round(s[1].get_seconds(), 3), "duration_sec": round(s[1].get_seconds()-s[0].get_seconds(), 3)} for i, s in enumerate(scenes)]
        return {"ok": True, "path": str(target), "scene_count": len(scene_list), "threshold": threshold, "scenes": scene_list}
    except ImportError:
        return {"ok": False, "error": "pyscenedetect not installed: pip install scenedetect[opencv]"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def detect_objects(path: str, confidence: float = 0.25, model: str = "yolov8n.pt") -> dict:
    """
    Detect objects in an image using YOLO (ultralytics).
    First run auto-downloads model (~6 MB for nano). confidence: 0.0-1.0.
    model: yolov8n.pt (nano/fast) | yolov8s.pt (small) | yolov8m.pt (medium).
    Requires: pip install ultralytics
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        from ultralytics import YOLO
        m = YOLO(model)
        results = m(str(target), conf=confidence, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                detections.append({"class": r.names[cls_id], "confidence": round(float(box.conf[0]), 4), "bbox": {"x1": round(float(box.xyxy[0][0]), 1), "y1": round(float(box.xyxy[0][1]), 1), "x2": round(float(box.xyxy[0][2]), 1), "y2": round(float(box.xyxy[0][3]), 1)}})
        by_class: dict = {}
        for d in detections:
            by_class[d["class"]] = by_class.get(d["class"], 0) + 1
        return {"ok": True, "model": model, "total": len(detections), "by_class": by_class, "detections": detections}
    except ImportError:
        return {"ok": False, "error": "ultralytics not installed: pip install ultralytics"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def create_svg(path: str, content: str) -> dict:
    """Write SVG file. content: valid SVG markup. Procedural drawing — no Gen AI."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not content.strip().startswith("<"):
        content = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">{content}</svg>'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target)}

def create_mermaid(path: str, content: str) -> dict:
    """Write Mermaid diagram file (.mmd). content: mermaid code (flowchart, sequenceDiagram, etc)."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not content.strip().startswith(("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "erDiagram", "gantt", "pie", "journey")):
        content = f"flowchart TD\n{content}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target)}

def uuid_generate(count: int = 1) -> dict:
    """Generate UUID(s). count: number of UUIDs."""
    import uuid
    uuids = [str(uuid.uuid4()) for _ in range(min(max(1, count), 100))]
    return {"ok": True, "uuids": uuids}

def random_string(length: int = 16, charset: str = "alphanumeric") -> dict:
    """Generate random string. charset: alphanumeric|hex|ascii."""
    import secrets
    import string
    if charset == "hex":
        s = secrets.token_hex(length // 2 + 1)[:length]
    elif charset == "ascii":
        s = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    else:
        s = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    return {"ok": True, "value": s}

def password_generate(length: int = 20, symbols: bool = True) -> dict:
    """Generate secure random password."""
    import secrets
    import string
    chars = string.ascii_letters + string.digits
    if symbols:
        chars += "!@#$%^&*"
    pwd = "".join(secrets.choice(chars) for _ in range(min(max(12, length), 128)))
    return {"ok": True, "password": pwd, "length": len(pwd)}

def generate_qr(data: str, output_path: str = "", size: int = 10) -> dict:
    """Generate QR code. data: text/URL. output_path: save PNG. Requires qrcode."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=size, border=2)
        qr.add_data(data[:4000])
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        if output_path:
            out = Path(output_path)
            if not inside_sandbox(out):
                return {"ok": False, "error": "Output outside sandbox"}
            img.save(str(out))
            return {"ok": True, "output": str(out)}
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return {"ok": True, "base64": __import__("base64").b64encode(buf.getvalue()).decode()[:5000]}
    except ImportError:
        return {"ok": False, "error": "qrcode not installed: pip install qrcode[pil]"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def json_schema(data: str | dict) -> dict:
    """Infer JSON schema from sample data. data: JSON string or dict."""
    try:
        import json as _json
        obj = _json.loads(data) if isinstance(data, str) else data
        def _infer(v):
            if v is None:
                return {"type": "null"}
            if isinstance(v, bool):
                return {"type": "boolean"}
            if isinstance(v, int):
                return {"type": "integer"}
            if isinstance(v, float):
                return {"type": "number"}
            if isinstance(v, str):
                return {"type": "string"}
            if isinstance(v, list):
                item = _infer(v[0]) if v else {}
                return {"type": "array", "items": item}
            if isinstance(v, dict):
                return {"type": "object", "properties": {k: _infer(v) for k, v in v.items()}}
            return {}
        schema = _infer(obj)
        return {"ok": True, "schema": schema}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def jwt_decode(token: str, verify: bool = False, secret: str = "") -> dict:
    """Decode JWT (header + payload). verify=True validates signature with secret."""
    try:
        import base64
        import json as _json
        parts = token.split(".")
        if len(parts) != 3:
            return {"ok": False, "error": "Invalid JWT format"}
        def b64d(s):
            pad = 4 - len(s) % 4
            return base64.urlsafe_b64decode(s + "=" * pad)
        header = _json.loads(b64d(parts[0]).decode())
        payload = _json.loads(b64d(parts[1]).decode())
        if verify and secret:
            try:
                import hashlib
                import hmac
                sig = parts[2]
                msg = f"{parts[0]}.{parts[1]}".encode()
                exp = base64.urlsafe_b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode().rstrip("=")
                if exp != sig:
                    return {"ok": False, "error": "Signature verification failed"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "header": header, "payload": payload}
    except Exception as e:
        return {"ok": False, "error": str(e)}


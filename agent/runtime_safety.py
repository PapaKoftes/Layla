import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from layla.time_utils import utcnow

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
GOV_PATH = AGENT_DIR / ".governance"
APPROVAL_FILE = GOV_PATH / "approvals.json"
EXEC_LOG_FILE = GOV_PATH / "execution_log.json"
IDENTITY_FILE = AGENT_DIR / "system_identity.txt"
PERSONALITY_EXPRESSION_FILE = AGENT_DIR / "personality_expression.txt"
COGNITIVE_LENS_FILE = AGENT_DIR / "cognitive_lens.txt"
BEHAVIORAL_RHYTHM_FILE = AGENT_DIR / "behavioral_rhythm.txt"
UI_REFLECTION_FILE = AGENT_DIR / "ui_reflection.txt"
LENS_KNOWLEDGE_DIR = AGENT_DIR / "lens_knowledge"
OPERATIONAL_GUIDANCE_FILE = AGENT_DIR / "operational_guidance.txt"
CONFIG_FILE = AGENT_DIR / "runtime_config.json"
BACKUP_DIR = AGENT_DIR / ".backup"

SAFE_TOOLS = ["git_status", "read_file", "list_dir"]
DANGEROUS_TOOLS = [
    "write_file", "shell", "shell_session_start", "run_python", "apply_patch", "git_commit", "mcp_tools_call",
    "git_push", "git_revert", "git_clone", "git_worktree_add", "git_worktree_remove", "run_tests", "pip_install",
    "search_replace", "rename_symbol", "generate_gcode", "geometry_execute_program", "docker_run",
    "github_pr", "send_email", "clipboard_write", "browser_click", "browser_fill",
    "code_format", "write_csv", "calendar_add_event", "create_svg", "create_mermaid",
    "notebook_edit_cell",
]

PROTECTED_FILES = [
    AGENT_DIR / "main.py",
    AGENT_DIR / "agent_loop.py",
    AGENT_DIR / "runtime_safety.py",
]

_config_cache: dict | None = None
_config_mtime: float = 0.0
_config_last_check: float = 0.0
_CONFIG_CHECK_TTL: float = 2.0  # skip stat() for 2 s during hot loops
_config_lock = threading.Lock()
_file_cache_lock = threading.Lock()
_hw_lock = threading.Lock()
_hardware_probe_cache: dict | None = None


def invalidate_config_cache() -> None:
    """Clear the TTL config cache under lock. Use after writing runtime_config.json."""
    global _config_cache, _config_mtime, _config_last_check
    with _config_lock:
        _config_cache = None
        _config_mtime = 0.0
        _config_last_check = 0.0


def _probe_hardware() -> dict:
    """Probe CPU, RAM, GPU/VRAM once per process. Returns ram_gb, vram_gb, cpu_logical."""
    global _hardware_probe_cache
    if _hardware_probe_cache is not None:
        return _hardware_probe_cache
    with _hw_lock:
        if _hardware_probe_cache is not None:
            return _hardware_probe_cache
        result: dict
        try:
            from services.hardware_detect import detect_hardware
            h = detect_hardware()
            result = {
                "ram_gb": h["ram_gb"],
                "vram_gb": h["vram_gb"],
                "cpu_logical": h["cpu_cores"],
            }
        except Exception as e:
            logger.debug("runtime_safety hardware_detect failed: %s", e)
            cpu_count = os.cpu_count() or 4
            ram_gb = 16.0
            vram_gb = 0.0
            try:
                import psutil
                mem = psutil.virtual_memory()
                ram_gb = round(mem.total / (1024**3), 1)
            except Exception as pe:
                logger.debug("runtime_safety psutil fallback failed: %s", pe)
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = r.stdout.strip().split("\n")[0].strip().replace("MiB", "").replace("MB", "").strip()
                    try:
                        vram_mb = int(raw)
                        vram_gb = round(vram_mb / 1024.0, 1)
                    except ValueError:
                        pass
            except Exception as ne:
                logger.debug("runtime_safety nvidia-smi failed: %s", ne)
            result = {"ram_gb": ram_gb, "vram_gb": vram_gb, "cpu_logical": cpu_count}
        _hardware_probe_cache = result
        return _hardware_probe_cache


def _hardware_derived_defaults() -> dict:
    """Return LLM-related defaults derived from probed hardware. Override in runtime_config.json."""
    h = _probe_hardware()
    ram_gb = h["ram_gb"]
    vram_gb = h["vram_gb"]

    if vram_gb >= 16 and ram_gb >= 24:
        return {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024, "use_mlock": True, "completion_max_tokens": 512}
    if vram_gb >= 12 and ram_gb >= 16:
        return {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 512, "use_mlock": ram_gb >= 24, "completion_max_tokens": 512}
    if vram_gb >= 8 and ram_gb >= 12:
        return {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 512, "use_mlock": False, "completion_max_tokens": 384}
    if vram_gb >= 6:
        return {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 256, "use_mlock": False, "completion_max_tokens": 256}
    if vram_gb >= 4:
        return {"n_ctx": 4096, "n_gpu_layers": 20, "n_batch": 256, "use_mlock": False, "completion_max_tokens": 256}
    if vram_gb >= 2:
        return {"n_ctx": 2048, "n_gpu_layers": 10, "n_batch": 128, "use_mlock": False, "completion_max_tokens": 256}
    # CPU-only or no GPU
    return {"n_ctx": 2048, "n_gpu_layers": 0, "n_batch": 128, "use_mlock": ram_gb >= 16, "completion_max_tokens": 256}


def load_config() -> dict:
    """Load runtime config. Cached: skips disk stat for _CONFIG_CHECK_TTL seconds during hot loops."""
    global _config_cache, _config_mtime, _config_last_check
    now = time.monotonic()
    # Fast path: TTL not expired and cache warm — zero I/O, no lock needed (read-only reference)
    if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_TTL:
        return _config_cache
    with _config_lock:
        # Re-check inside lock to avoid redundant reloads from concurrent threads
        now = time.monotonic()
        if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_TTL:
            return _config_cache
        _config_last_check = now
        try:
            current_mtime = CONFIG_FILE.stat().st_mtime
        except Exception as e:
            logger.debug("runtime_safety config stat failed: %s", e)
            current_mtime = 0.0
        if _config_cache is not None and current_mtime == _config_mtime:
            return _config_cache
        # Static defaults (safe fallbacks)
        defaults = {
            "max_cpu_percent": 95,
            "max_ram_percent": 95,
            "warn_cpu_percent": 70,
            "hard_cpu_percent": 85,
            "max_active_runs": 1,
            "response_pacing_ms": 0,
            "repo_cognition_inject_enabled": True,
            "repo_cognition_max_chars": 6000,
            "project_memory_enabled": True,
            "project_memory_max_bytes": 1_500_000,
            "project_memory_inject_max_chars": 4000,
            "project_memory_max_file_entries": 500,
            "project_memory_max_list_entries": 200,
            "project_memory_persist_plan": True,
            "planning_strict_mode": False,
            "in_loop_plan_governance_enabled": True,
            "in_loop_plan_default_max_retries": 1,
            "plan_governance_require_nonempty_step_tools": False,
            "plan_governance_reject_auto_filled_tools": False,
            "plan_governance_strict_tool_evidence": False,
            "plan_governance_hard_mode": False,
            "llm_serialize_per_workspace": False,
            "plan_step_default_read_tools": ["read_file", "list_dir", "grep_code"],
            "file_plan_refinement_enabled": False,
            "ui_agent_stream_timeout_seconds": 900,
            "ui_agent_json_timeout_seconds": 720,
            "ui_stream_keepalive_seconds": 20,
            "ui_stalled_silence_ms": 0,
            "honesty_and_boundaries_enabled": True,
            "dual_model_threshold_gb": 24,
            "force_dual_models": False,
            "route_default_to_chat_model": False,
            "auto_pip_install_optional": False,
            "performance_mode": "auto",
            "anti_drift_prompt_enabled": True,
            "chat_model_path": "",
            "agent_model_path": "",
            "max_runtime_seconds": 900,
            "chat_light_max_runtime_seconds": 90,
            "max_tool_calls": 20,
            "tool_call_timeout_seconds": 60,
            "approval_ttl_seconds": 3600,
            "hyde_enabled": False,
            "ollama_base_url": "",
            "inference_backend": "llama_cpp",
            "context_auto_compact_ratio": 0.75,
            "tool_routing_enabled": True,
            "tools_profile": "full",
            "tools_allow": [],
            "tools_deny": [],
            "tool_groups": {},
            "tools_by_provider": {},
            "tool_loop_detection_enabled": True,
            "tool_loop_history_size": 30,
            "tool_loop_warning_threshold": 10,
            "tool_loop_stop_threshold": 20,
            "tool_loop_detect_repeat": True,
            "tool_loop_detect_pingpong": True,
            "http_cache_ttl_seconds": 0,
            "http_cache_max_entries": 200,
            "inference_fallback_urls": [],
            "image_model": None,
            "image_generation_model": None,
            "markdown_skills_dir": None,
            "markdown_skills_watch": False,
            "browser_default_profile": "default",
            "browser_profiles": {},
            "browser_persistent_profiles": False,
            "use_instructor_for_decisions": True,
            "retrieval_cache_ttl_seconds": 60,
            "completion_cache_enabled": True,
            "completion_cache_ttl_seconds": 45,
            "completion_cache_max_entries": 500,
            "response_cache_enabled": True,
            "response_cache_ttl_seconds": 300,
            "response_cache_max_entries": 300,
            "telemetry_enabled": True,
            "sandbox_runner_timeout_seconds": 120.0,
            "sandbox_python_timeout_seconds": 45.0,
            "shell_restrict_to_allowlist": False,
            "shell_allowlist_extra": [],
            "tool_args_validation_enabled": True,
            "coding_model_large_context": None,
            "coding_large_context_threshold": 12000,
            "retrieval_hybrid_vector_weight": 1.0,
            "retrieval_hybrid_bm25_weight": 1.0,
            "retrieval_hybrid_coding_bm25_boost": 1.25,
            "use_bge_reranker": False,
            "bge_reranker_model": "",
            "knowledge_ingestion_enabled": True,
            "multi_agent_orchestration_enabled": False,
            "learning_quality_gate_enabled": True,
            "learning_quality_min_score": 0.35,
            "learning_min_score": 0.3,
            "auto_lint_test_fix": False,
            "auto_lint_test_fix_run_tests": False,
            "git_auto_commit": False,
            "github_repo": "",
            "auto_update_check_enabled": False,
            "research_max_tool_calls": 20,
            "research_max_runtime_seconds": 1800,
            "safe_mode": True,
            "mcp_client_enabled": False,
            "mcp_stdio_servers": [],
            "mcp_inject_tool_summary_in_decisions": False,
            "mcp_tool_summary_ttl_seconds": 300,
            "agent_hooks_enabled": True,
            "hooks_require_allow_run": True,
            "agent_hooks": [],
            "background_use_subprocess_workers": False,
            "background_subprocess_local_gguf_policy": "warn",
            "background_worker_grace_seconds": 4.0,
            "background_job_max_stdout_bytes": 8000000,
            "background_worker_force_sandbox_only": False,
            "background_worker_rlimits_enabled": False,
            "background_worker_rlimit_as_bytes": 0,
            "background_worker_windows_job_limits_enabled": False,
            "background_worker_windows_job_memory_mb": 0,
            "background_worker_windows_job_cpu_percent": 0,
            "background_worker_rlimit_cpu_seconds": 0,
            "background_worker_wrapper_command": [],
            "background_progress_stream_enabled": True,
            "background_progress_min_interval_seconds": 0.35,
            "background_progress_max_events": 200,
            "background_progress_tail_max": 50,
            "background_job_max_stderr_bytes": 2_000_000,
            "background_worker_cgroup_auto_enabled": False,
            "background_worker_cgroup_memory_max_bytes": 0,
            "background_worker_cgroup_cpu_max": "",
            "temperature": 0.2,
            "n_ctx": 4096,
            "n_gpu_layers": -1,  # full GPU offload by default; overridden by hardware probe
            "n_batch": 512,
            "n_threads": None,
            "n_threads_batch": None,
            "use_mlock": False,
            "use_mmap": True,
            "top_p": 0.95,
            "repeat_penalty": 1.1,
            "top_k": 40,
            "model_filename": "your-model.gguf",
            "models_dir": str(REPO_ROOT / "models"),  # repo models/ for backward compat; installer may set ~/.layla/models
            "sandbox_root": str(Path.home()),
            "web_allowlist": [],
            "knowledge_sources": [],
            "knowledge_max_bytes": 4000,
            "knowledge_chunks_k": 5,
            "learnings_n": 30,
            "semantic_k": 5,
            "aspect_memories_n": 10,
            "convo_turns": 0,
            "stop_sequences": ["\nUser:", " User:"],
            "completion_max_tokens": 256,
            "remote_model_name": "llama3.1",
            "llama_server_url": None,
            "inference_backend": "auto",
            "coding_model": None,
            "reasoning_model": None,
            "chat_model": None,
            "model_override_enabled": True,
            "reasoning_budget": -1,
            "scheduler_study_enabled": True,
            "scheduler_interval_minutes": 30,
            "scheduler_recent_activity_minutes": 90,
            "wakeup_include_initiative": False,
            "wakeup_include_discovery_line": False,
            "remote_enabled": False,
            "remote_api_key": None,
            "remote_allow_endpoints": [],
            "remote_mode": "observe",
            "trace_id_enabled": False,
            "use_chroma": True,
            "uncensored": True,
            "nsfw_allowed": True,
            "knowledge_unrestricted": True,
            "anonymous_access": True,
            "enable_personality_expression": False,
            "enable_cognitive_lens": False,
            "enable_behavioral_rhythm": False,
            "enable_ui_reflection": False,
            "enable_lens_knowledge": False,
            "enable_lens_refresh": False,
            "lens_refresh_interval_days": 7,
            "enable_operational_guidance": False,
            "enable_cognitive_workspace": True,
            "spotify_client_id": None,
            "spotify_client_secret": None,
            "slack_bot_token": None,
            "slack_app_token": None,
            "telegram_bot_token": None,
            "transport_allowlist": "",
            "transport_require_allowlist": False,
            "openclaw_gateway_url": None,
            "sandbox_python_memory_limit_mb": 0,
            "max_chars_per_source": 500,
            "retrieval_line_overlap_threshold": 0.7,
            "write_file_max_bytes": 500_000,
            "write_file_explosion_factor": 5,
            "max_patch_lines": 0,
            "doc_injection_guard_enabled": True,
            "telemetry_log_trivial": False,
            "embedder_prewarm_enabled": False,
            "voice_stt_prewarm_enabled": False,
            "voice_tts_prewarm_enabled": False,
            "geometry_frameworks_enabled": {"ezdxf": True, "cadquery": True, "openscad": True, "trimesh": True},
            "openscad_executable": "openscad",
            "geometry_subprocess_timeout_seconds": 120.0,
            "geometry_external_bridge_url": "",
            "geometry_external_bridge_allow_insecure_localhost": False,
            "direct_feedback_enabled": False,
            "pin_psychology_framework_excerpt": True,
            "file_checkpoint_enabled": True,
            "file_checkpoint_max_count": 200,
            "file_checkpoint_max_bytes": 209_715_200,
            "elasticsearch_enabled": False,
            "elasticsearch_url": "",
            "elasticsearch_index_prefix": "layla",
            "elasticsearch_api_key": None,
        }
        defaults.update(_hardware_derived_defaults())
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception as e:
            logger.debug("runtime_safety config load failed: %s", e)
        _config_cache = defaults
        _config_mtime = current_mtime
        return _config_cache


def resolve_model_path(cfg: dict | None = None) -> Path:
    """
    Resolve full path to model file. Uses models_dir from config if set, else REPO_ROOT/models.
    """
    if cfg is None:
        cfg = load_config()
    model_filename = (cfg.get("model_filename") or "").strip()
    if not model_filename or model_filename == "your-model.gguf":
        return REPO_ROOT / "models" / "your-model.gguf"  # placeholder
    models_dir_raw = cfg.get("models_dir")
    if models_dir_raw:
        models_dir = Path(models_dir_raw).expanduser().resolve()
    else:
        models_dir = REPO_ROOT / "models"
    return models_dir / model_filename


_file_cache: dict[str, tuple[float, str]] = {}  # path -> (mtime, content)


def _read_cached(path: Path) -> str:
    """Read a file with mtime caching — safe to call on every inference turn."""
    key = str(path)
    with _file_cache_lock:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            return _file_cache.get(key, (0.0, ""))[1]
        cached = _file_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            content = ""
        _file_cache[key] = (mtime, content)
        return content


def load_identity() -> str:
    return _read_cached(IDENTITY_FILE)


def load_personality() -> str:
    try:
        p = json.loads(_read_cached(REPO_ROOT / "personality.json"))
        return p.get("systemPromptAddition", "")
    except Exception:
        return ""


def load_personality_expression() -> str:
    return _read_cached(PERSONALITY_EXPRESSION_FILE).strip() if PERSONALITY_EXPRESSION_FILE.exists() else ""


def load_cognitive_lens() -> str:
    return _read_cached(COGNITIVE_LENS_FILE).strip() if COGNITIVE_LENS_FILE.exists() else ""


def load_behavioral_rhythm() -> str:
    return _read_cached(BEHAVIORAL_RHYTHM_FILE).strip() if BEHAVIORAL_RHYTHM_FILE.exists() else ""


def load_ui_reflection() -> str:
    return _read_cached(UI_REFLECTION_FILE).strip() if UI_REFLECTION_FILE.exists() else ""


def load_operational_guidance() -> str:
    return _read_cached(OPERATIONAL_GUIDANCE_FILE).strip() if OPERATIONAL_GUIDANCE_FILE.exists() else ""


def load_lens_knowledge() -> str:
    """Load summarized lens knowledge from lens_knowledge/*.md (prompt-only). Cached per mtime."""
    summaries = []
    try:
        if LENS_KNOWLEDGE_DIR.exists():
            for f in sorted(LENS_KNOWLEDGE_DIR.glob("*.md")):
                summaries.append(_read_cached(f)[:600])
    except Exception:
        pass
    return "\n\n".join(summaries) if summaries else ""


def _knowledge_priority_from_text(text: str) -> str:
    """Parse optional YAML front matter priority. Default support."""
    if not (text or "").strip().startswith("---"):
        return "support"
    for line in (text or "").split("\n")[1:]:
        line = line.strip()
        if line == "---":
            break
        if line.lower().startswith("priority:") and ":" in line:
            val = line.split(":", 1)[1].strip().lower()
            if val in ("core", "support", "flavor"):
                return val
    return "support"


def load_knowledge_docs(max_bytes: int = 6000) -> str:
    """Walk knowledge/ and concatenate .md / .txt files up to max_bytes. Excludes .identity. Priority: core > support > flavor."""
    knowledge_dir = REPO_ROOT / "knowledge"
    if not knowledge_dir.exists():
        return ""
    collected = []
    for ext in ("*.md", "*.txt"):
        for f in sorted(knowledge_dir.rglob(ext)):
            if ".identity" in str(f):
                continue
            try:
                text = _read_cached(f)
                priority = _knowledge_priority_from_text(text)
                if text.strip().startswith("---"):
                    end = text.find("\n---", 3)
                    body = text[end + 4:].strip() if end >= 0 else text
                else:
                    body = text
                collected.append((priority, f"--- {f.name} ---\n{body[:8000]}"))
            except Exception:
                continue
    order = {"core": 0, "support": 1, "flavor": 2}
    collected.sort(key=lambda x: order.get(x[0], 1))
    parts = []
    total = 0
    for _, chunk in collected:
        if total >= max_bytes:
            break
        remaining = max_bytes - total
        parts.append(chunk[:remaining])
        total += len(parts[-1])
    return "\n\n".join(parts)


def require_approval(tool_name: str) -> bool:
    if tool_name in SAFE_TOOLS:
        return True
    if tool_name in DANGEROUS_TOOLS:
        try:
            data = json.loads(APPROVAL_FILE.read_text(encoding="utf-8"))
            return data.get(tool_name, False) if isinstance(data, dict) else False
        except Exception:
            return False
    return False


def is_protected(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return any(resolved == p for p in PROTECTED_FILES)
    except Exception:
        return False


def backup_file(path: Path) -> bool:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"{path.stem}_{ts}{path.suffix}"
        shutil.copy2(str(path), str(dest))
        return True
    except Exception:
        return False


def log_execution(tool_name: str, payload: dict) -> None:
    entry = {
        "timestamp": utcnow().isoformat(),
        "tool": tool_name,
        "payload": payload,
    }
    try:
        GOV_PATH.mkdir(parents=True, exist_ok=True)
        data = []
        if EXEC_LOG_FILE.exists():
            try:
                data = json.loads(EXEC_LOG_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = []
        data.append(entry)
        EXEC_LOG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

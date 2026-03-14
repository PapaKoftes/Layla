import json
import os
import shutil
import subprocess
import time

from layla.time_utils import utcnow
from pathlib import Path

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
DANGEROUS_TOOLS = ["write_file", "shell", "run_python", "apply_patch"]

PROTECTED_FILES = [
    AGENT_DIR / "main.py",
    AGENT_DIR / "agent_loop.py",
    AGENT_DIR / "runtime_safety.py",
]

_config_cache: dict | None = None
_config_mtime: float = 0.0
_config_last_check: float = 0.0
_CONFIG_CHECK_TTL: float = 2.0  # skip stat() for 2 s during hot loops
_hardware_probe_cache: dict | None = None


def _probe_hardware() -> dict:
    """Probe CPU, RAM, GPU/VRAM once per process. Returns ram_gb, vram_gb, cpu_logical."""
    global _hardware_probe_cache
    if _hardware_probe_cache is not None:
        return _hardware_probe_cache
    try:
        from services.hardware_detect import detect_hardware
        h = detect_hardware()
        _hardware_probe_cache = {
            "ram_gb": h["ram_gb"],
            "vram_gb": h["vram_gb"],
            "cpu_logical": h["cpu_cores"],
        }
    except Exception:
        cpu_count = os.cpu_count() or 4
        ram_gb = 16.0
        vram_gb = 0.0
        try:
            import psutil
            mem = psutil.virtual_memory()
            ram_gb = round(mem.total / (1024**3), 1)
        except Exception:
            pass
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
        except Exception:
            pass
        _hardware_probe_cache = {"ram_gb": ram_gb, "vram_gb": vram_gb, "cpu_logical": cpu_count}
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
    # Fast path: TTL not expired and cache warm — zero I/O
    if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_TTL:
        return _config_cache
    _config_last_check = now
    try:
        current_mtime = CONFIG_FILE.stat().st_mtime
    except Exception:
        current_mtime = 0.0
    if _config_cache is not None and current_mtime == _config_mtime:
        return _config_cache
    # Static defaults (safe fallbacks)
    defaults = {
        "max_cpu_percent": 90,
        "max_ram_percent": 90,
        "max_runtime_seconds": 20,
        "max_tool_calls": 5,
        "research_max_tool_calls": 20,
        "research_max_runtime_seconds": 120,
        "safe_mode": True,
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
    }
    defaults.update(_hardware_derived_defaults())
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    _config_cache = defaults
    _config_mtime = current_mtime
    return _config_cache


_file_cache: dict[str, tuple[float, str]] = {}  # path -> (mtime, content)


def _read_cached(path: Path) -> str:
    """Read a file with mtime caching — safe to call on every inference turn."""
    key = str(path)
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

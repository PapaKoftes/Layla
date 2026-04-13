"""Tool implementations — domain: system."""
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
def shell(argv: list, cwd: str) -> dict:
    if not argv:
        return {"ok": False, "error": "Empty command"}
    base = _shell_executable_base(argv)
    if base in _SHELL_NETWORK_DENYLIST:
        return {"ok": False, "error": f"command blocked by network denylist: {base}"}
    line = shell_command_line(argv)
    import re
    inj_warn = None
    if not shell_command_is_safe_whitelisted(argv):
        for pat in _SHELL_INJECTION_WARN:
            if re.search(pat, line):
                inj_warn = "potential command injection detected — operator review recommended"
                break
    try:
        from services.sandbox.shell_runner import run_shell_argv

        cwd_path = Path(cwd)
        out = run_shell_argv(list(argv or []), cwd_path, inside_sandbox_check=inside_sandbox)
        if inj_warn and isinstance(out, dict) and out.get("ok"):
            out = {**out, "warning": inj_warn, "risk_level": "high"}
        return out
    except Exception as e:
        logger.debug("shell runner failed, fallback: %s", e)
    cmd = argv[0].lower().lstrip("./\\")
    for blocked in _SHELL_BLOCKLIST:
        if cmd == blocked or cmd.endswith(blocked):
            return {"ok": False, "error": f"Command blocked: {argv[0]}"}
    cwd_path = Path(cwd)
    if not inside_sandbox(cwd_path):
        return {"ok": False, "error": "cwd outside sandbox"}
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        out = {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:2000],
            "returncode": proc.returncode,
        }
        if inj_warn and out.get("ok"):
            out["warning"] = inj_warn
            out["risk_level"] = "high"
        return out
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out (60s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def shell_session_start(argv: list | None = None, cwd: str = "") -> dict:
    """Start a background shell process; returns session_id. Requires approval."""
    from services.shell_sessions import shell_session_tool

    return shell_session_tool(action="start", argv=list(argv or []), cwd=cwd or "")

def shell_session_manage(
    action: str = "poll",
    session_id: str = "",
    cwd: str = "",
    limit: int = 80,
) -> dict:
    """Poll, log, or kill a background shell session (no extra approval)."""
    from services.shell_sessions import shell_session_tool

    return shell_session_tool(
        action=action,
        session_id=session_id,
        cwd=cwd or "",
        limit=limit,
    )

def pip_list(cwd: str = "") -> dict:
    """List installed pip packages. cwd: optional venv path."""
    try:
        argv = [sys.executable, "-m", "pip", "list", "--format=json"]
        proc = subprocess.run(
            argv,
            cwd=cwd or str(Path.cwd()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": (proc.stderr or proc.stdout or "")[:500]}
        import json as _json
        data = _json.loads(proc.stdout or "[]")
        return {"ok": True, "packages": [{"name": p["name"], "version": p["version"]} for p in data[:200]]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def pip_install(packages: str, cwd: str = "", upgrade: bool = False) -> dict:
    """Install pip package(s). packages: space-separated names or path to requirements.txt."""
    cwd_path = Path(cwd) if cwd else Path.cwd()
    if cwd and not inside_sandbox(cwd_path):
        return {"ok": False, "error": "cwd outside sandbox"}
    argv = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        argv.append("--upgrade")
    pkg = packages.strip()
    if pkg.endswith(".txt") and Path(pkg).exists():
        argv.append("-r")
        argv.append(pkg)
    else:
        argv.extend(pkg.split())
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "")[:4000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pip install timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def env_info() -> dict:
    """Return system info: OS, Python version, CPU, RAM, GPU, installed key packages."""
    import platform
    import sys as _sys
    info: dict = {
        "os": platform.system(),
        "os_version": platform.version(),
        "python": _sys.version.split()[0],
        "architecture": platform.machine(),
    }
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        info["ram_available_gb"] = round(mem.available / (1024**3), 1)
        info["cpu_logical"] = psutil.cpu_count(logical=True)
    except Exception:
        pass
    try:
        r = subprocess.run(  # noqa: F841
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            info["gpu"] = r.stdout.strip()
    except Exception:
        info["gpu"] = "none / not detected"
    key_packages = ["fastapi", "uvicorn", "llama_cpp", "chromadb", "sentence_transformers",
                    "playwright", "faster_whisper", "psutil", "rank_bm25"]
    installed = {}
    import importlib.metadata as _meta
    for pkg in key_packages:
        try:
            installed[pkg] = _meta.version(pkg.replace("_", "-"))
        except Exception:
            installed[pkg] = "not installed"
    info["packages"] = installed
    return {"ok": True, **info}

def check_port(host: str, port: int, timeout: float = 3.0) -> dict:
    """Check if a TCP port is open. Returns: open/closed, response time ms."""
    import socket as _sock
    import time as _time
    start = _time.time()
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return {"ok": True, "host": host, "port": port, "open": result == 0, "response_ms": round((_time.time()-start)*1000, 1)}
    except Exception as e:
        return {"ok": False, "host": host, "port": port, "open": False, "error": str(e)}

def docker_ps(all_containers: bool = False) -> dict:
    """List Docker containers. all_containers=True includes stopped."""
    try:
        argv = ["docker", "ps", "-a"] if all_containers else ["docker", "ps"]
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "")[:4000]}
    except FileNotFoundError:
        return {"ok": False, "error": "Docker not found or not in PATH"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def docker_run(image: str, args: str = "", name: str = "", rm: bool = True) -> dict:
    """Run a Docker container. args: extra docker run args. name: container name. rm: remove when stopped."""
    argv = ["docker", "run"]
    if rm:
        argv.append("--rm")
    if name:
        argv.extend(["--name", name])
    argv.append(image)
    if args:
        argv.extend(args.split())
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "")[:4000]}
    except FileNotFoundError:
        return {"ok": False, "error": "Docker not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def check_ci(repo: str, provider: str = "github") -> dict:
    """Check CI status. repo: path or owner/repo. provider: github|gitlab."""
    repo_path = Path(repo)
    if repo_path.exists() and repo_path.is_dir():
        try:
            r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(repo_path), capture_output=True, text=True)
            url = (r.stdout or "").strip()
            if "github.com" in url:
                m = re.search(r"github\.com[/:]([\w-]+)/([\w.-]+)", url)
                if m:
                    owner, repo_name = m.group(1), m.group(2).replace(".git", "")
                    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/actions/runs?per_page=5"
                    try:
                        import urllib.request
                        req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github.v3+json"})
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = __import__("json").loads(resp.read().decode())
                        runs = data.get("workflow_runs", [])[:5]
                        return {"ok": True, "provider": "github", "runs": [{"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"), "created_at": r.get("created_at")} for r in runs]}
                    except Exception as e:
                        return {"ok": False, "error": str(e)}
        except Exception:
            pass
    return {"ok": False, "error": "Could not determine repo or fetch CI status"}

def disk_usage(path: str = ".") -> dict:
    """Disk usage for path. Returns used/total/free in GB."""
    try:
        import shutil
        p = Path(path)
        if not p.exists():
            p = Path.cwd()
        total, used, free = shutil.disk_usage(str(p))
        return {"ok": True, "path": str(p), "total_gb": round(total / (1024**3), 2), "used_gb": round(used / (1024**3), 2), "free_gb": round(free / (1024**3), 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def process_list(limit: int = 20) -> dict:
    """List running processes (top by CPU/memory). Requires psutil."""
    try:
        import psutil
        procs = []
        for p in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]), key=lambda x: (x.info.get("cpu_percent") or 0) + (x.info.get("memory_percent") or 0), reverse=True)[:limit]:
            try:
                procs.append({"pid": p.info["pid"], "name": (p.info.get("name") or "")[:40], "cpu": p.info.get("cpu_percent"), "memory": p.info.get("memory_percent")})
            except (psutil.NoSuchProcess, KeyError):
                pass
        return {"ok": True, "processes": procs}
    except ImportError:
        return {"ok": False, "error": "psutil not installed: pip install psutil"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


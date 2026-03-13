import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

# Thread-local effective sandbox for research missions (lab path). When set, tools use this instead of config sandbox_root.
_effective_sandbox = threading.local()

def set_effective_sandbox(path: str | None) -> None:
    """Set the effective sandbox root for this thread (e.g. .research_lab/workspace). Used by research missions so read_file/list_dir accept lab paths. Clear with None when run ends."""
    _effective_sandbox.path = path

def _get_sandbox() -> Path:
    try:
        p = getattr(_effective_sandbox, "path", None)
        if p is not None and str(p).strip():
            return Path(p).expanduser().resolve()
    except Exception:
        pass
    try:
        # runtime_safety is a sibling of this package's grandparent (agent/)
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        import runtime_safety
        root = runtime_safety.load_config().get("sandbox_root", str(Path.home()))
        return Path(root).expanduser().resolve()
    except Exception:
        return Path.home().resolve()

# Commands that are never allowed even with allow_run=True
_SHELL_BLOCKLIST = [
    "rm", "del", "rmdir", "format", "mkfs", "dd",
    "shutdown", "reboot", "powershell", "cmd", "reg",
    "netsh", "sc", "taskkill", "cipher",
]


def inside_sandbox(path: Path) -> bool:
    """Check whether path is inside the configured sandbox using Path.relative_to (no string prefix tricks)."""
    try:
        sandbox = _get_sandbox()
        resolved = path.resolve()
        resolved.relative_to(sandbox)
        return True
    except (ValueError, Exception):
        return False


def write_file(path: str, content: str) -> dict:
    target = Path(path)
    if not target.is_absolute() and getattr(_effective_sandbox, "path", None):
        target = (Path(_effective_sandbox.path) / path).resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target)}


def read_file(path: str) -> dict:
    target = Path(path)
    if not target.is_absolute() and getattr(_effective_sandbox, "path", None):
        target = (Path(_effective_sandbox.path) / path).resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    if not target.is_file():
        return {"ok": False, "error": "Not a file"}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": str(target), "content": content[:8000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_dir(path: str) -> dict:
    target = Path(path)
    if not target.is_absolute() and getattr(_effective_sandbox, "path", None):
        target = (Path(_effective_sandbox.path) / path).resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    try:
        entries = []
        for item in sorted(target.iterdir()):
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            })
        return {"ok": True, "path": str(target), "entries": entries}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_status(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "status"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": result.stdout or ""}


def shell(argv: list, cwd: str) -> dict:
    if not argv:
        return {"ok": False, "error": "Empty command"}
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
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out (60s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def grep_code(pattern: str, path: str, file_glob: str = "*") -> dict:
    """Search for a pattern in files. Tries rg first, falls back to Python re walk."""
    root = Path(path)
    if not root.is_absolute() and getattr(_effective_sandbox, "path", None):
        root = (Path(_effective_sandbox.path) / path).resolve()
    if not inside_sandbox(root):
        return {"ok": False, "error": "Outside sandbox"}
    if not root.exists():
        return {"ok": False, "error": "Path not found"}
    # Try ripgrep (UTF-8 so Windows doesn't decode with cp1252 and raise on rg output)
    try:
        proc = subprocess.run(
            ["rg", pattern, str(root), "--glob", file_glob, "-n", "--max-count", "5"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode in (0, 1):  # 1 = no matches
            out = (proc.stdout if proc.stdout is not None else "")[:6000]
            return {"ok": True, "matches": out}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Python fallback
    try:
        rx = re.compile(pattern)
        results = []
        for f in root.rglob(file_glob):
            if not f.is_file():
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        results.append(f"{f}:{i}: {line.rstrip()}")
                        if len(results) >= 50:
                            break
            except Exception:
                continue
            if len(results) >= 50:
                break
        return {"ok": True, "matches": "\n".join(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def glob_files(pattern: str, root: str) -> dict:
    root_path = Path(root)
    if not root_path.is_absolute() and getattr(_effective_sandbox, "path", None):
        root_path = (Path(_effective_sandbox.path) / root).resolve()
    if not inside_sandbox(root_path):
        return {"ok": False, "error": "Outside sandbox"}
    if not root_path.exists():
        return {"ok": False, "error": "Path not found"}
    try:
        matches = [str(p) for p in root_path.rglob(pattern)][:200]
        return {"ok": True, "matches": matches}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_python(code: str, cwd: str) -> dict:
    cwd_path = Path(cwd)
    if not inside_sandbox(cwd_path):
        return {"ok": False, "error": "cwd outside sandbox"}
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        proc = subprocess.run(
            ["python", tmp_path],
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        Path(tmp_path).unlink(missing_ok=True)
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:2000],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "run_python timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def apply_patch(original_path: str, patch_text: str) -> dict:
    """Apply a unified diff patch using unidiff (pure Python, Windows-safe). Creates a backup first."""
    target = Path(original_path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    import shutil, datetime
    backup = target.with_suffix(
        f".bak_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{target.suffix}"
    )
    shutil.copy2(str(target), str(backup))
    try:
        import unidiff
        patch_set = unidiff.PatchSet(patch_text.splitlines(keepends=True))
        original_lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        result_lines = list(original_lines)
        for patched_file in patch_set:
            offset = 0
            for hunk in patched_file:
                src_start = hunk.source_start - 1 + offset
                removed = [line.value for line in hunk if line.is_removed]
                added = [line.value for line in hunk if line.is_added]
                # Remove old lines, insert new ones
                result_lines[src_start: src_start + len(removed)] = added
                offset += len(added) - len(removed)
        target.write_text("".join(result_lines), encoding="utf-8")
        return {"ok": True, "path": str(target), "backup": str(backup)}
    except Exception as e:
        return {"ok": False, "error": str(e), "backup": str(backup)}


def git_diff(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "diff"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "")[:8000]}


def git_log(repo: str, n: int = 10) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "log", f"--oneline", f"-{n}"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "")[:4000]}


def git_branch(repo: str) -> dict:
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or "").strip()}


def fetch_url_tool(url: str, store: bool = False) -> dict:
    from layla.tools.web import fetch_url
    return fetch_url(url, store=store)


def file_info(path: str) -> dict:
    """Return size, line count (approx), and whether file looks text. Read-only; no approval."""
    target = Path(path)
    if not target.is_absolute() and getattr(_effective_sandbox, "path", None):
        target = (Path(_effective_sandbox.path) / path).resolve()
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    if not target.is_file():
        return {"ok": False, "error": "Not a file"}
    try:
        size = target.stat().st_size
        # Sample first 8k to guess text vs binary and count newlines
        raw = target.read_bytes()
        sample = raw[:8192]
        try:
            sample.decode("utf-8", errors="strict")
            is_text = True
        except Exception:
            is_text = False
        line_count = sample.count(b"\n") if is_text else None
        note = "from first 8k only" if is_text and len(raw) > len(sample) else None
        return {"ok": True, "path": str(target), "size_bytes": size, "is_text": is_text, "line_count_sample": line_count, "note": note}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
) -> dict:
    """Update project context. lifecycle_stage: idea|planning|prototype|iteration|execution|reflection."""
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
        )
        return {"ok": True, "message": "Project context updated."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def understand_file_tool(path: str, content: str | None = None) -> dict:
    """Interpret file intent (read-only). path: file path; optional content for in-memory analysis."""
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.file_understanding import analyze_file
        if content is not None:
            return {"ok": True, **analyze_file(file_path=path, content=content)}
        return {"ok": True, **analyze_file(file_path=path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def browser_navigate(url: str, timeout_ms: int = 15000) -> dict:
    """Navigate to a URL and return its main text content and title."""
    try:
        from services.browser import navigate
        return navigate(url, timeout_ms=timeout_ms)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}


def browser_search(query: str) -> dict:
    """Search the web via DuckDuckGo. Returns top 8 results with titles, URLs, snippets."""
    try:
        from services.browser import search_web
        return search_web(query)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}


def browser_screenshot(url: str) -> dict:
    """Take a full-page screenshot of a URL. Returns path to the screenshot file."""
    try:
        from services.browser import screenshot
        return screenshot(url)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}


def browser_click(url: str, selector: str) -> dict:
    """Navigate to a URL, click a CSS selector, return updated page text."""
    try:
        from services.browser import click_and_extract
        return click_and_extract(url, selector)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}


def browser_fill(url: str, fields: dict, submit_selector: str = "") -> dict:
    """Navigate to a URL, fill form fields {selector: value}, optionally submit."""
    try:
        from services.browser import fill_form
        return fill_form(url, fields, submit_selector)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}


TOOLS: dict[str, Any] = {
    "write_file": {"fn": write_file, "dangerous": True, "require_approval": True, "risk_level": "medium"},
    "read_file": {"fn": read_file, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "list_dir": {"fn": list_dir, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_status": {"fn": git_status, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "shell": {"fn": shell, "dangerous": True, "require_approval": True, "risk_level": "high"},
    "grep_code": {"fn": grep_code, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "glob_files": {"fn": glob_files, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "run_python": {"fn": run_python, "dangerous": True, "require_approval": True, "risk_level": "high"},
    "apply_patch": {"fn": apply_patch, "dangerous": True, "require_approval": True, "risk_level": "medium"},
    "git_diff": {"fn": git_diff, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_log": {"fn": git_log, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_branch": {"fn": git_branch, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "fetch_url": {"fn": fetch_url_tool, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "file_info": {"fn": file_info, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "get_project_context": {"fn": get_project_context_tool, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "update_project_context": {"fn": update_project_context_tool, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "understand_file": {"fn": understand_file_tool, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Browser tools — require playwright: playwright install chromium
    "browser_navigate": {"fn": browser_navigate, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_search": {"fn": browser_search, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_screenshot": {"fn": browser_screenshot, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_click": {"fn": browser_click, "dangerous": False, "require_approval": True, "risk_level": "medium"},
    "browser_fill": {"fn": browser_fill, "dangerous": False, "require_approval": True, "risk_level": "medium"},
}

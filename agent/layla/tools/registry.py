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


# ─── Extended tools ────────────────────────────────────────────────────────────

def json_query(path: str, query: str = "") -> dict:
    """
    Parse a JSON file and optionally extract a value by dot-notation path.
    query examples: 'key', 'nested.key', 'array.0.field'.
    If no query, returns the full parsed object (truncated).
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import json as _json
        data = _json.loads(target.read_text(encoding="utf-8"))
        if not query:
            return {"ok": True, "data": str(data)[:4000]}
        parts = query.split(".")
        val = data
        for p in parts:
            if isinstance(val, dict):
                val = val[p]
            elif isinstance(val, list):
                val = val[int(p)]
            else:
                return {"ok": False, "error": f"Cannot traverse into {type(val).__name__} at '{p}'"}
        return {"ok": True, "result": val, "result_str": str(val)[:2000]}
    except (KeyError, IndexError) as e:
        return {"ok": False, "error": f"Path not found: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def diff_files(path_a: str, path_b: str) -> dict:
    """Diff two text files. Returns unified diff."""
    for p in (path_a, path_b):
        t = Path(p)
        if not inside_sandbox(t):
            return {"ok": False, "error": f"Outside sandbox: {p}"}
        if not t.exists():
            return {"ok": False, "error": f"File not found: {p}"}
    try:
        import difflib
        a_lines = Path(path_a).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        b_lines = Path(path_b).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        diff = list(difflib.unified_diff(a_lines, b_lines, fromfile=path_a, tofile=path_b, n=3))
        return {"ok": True, "diff": "".join(diff)[:8000], "changed": len(diff) > 0}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def env_info() -> dict:
    """Return system info: OS, Python version, CPU, RAM, GPU, installed key packages."""
    import platform, sys as _sys
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
        r = subprocess.run(
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


def regex_test(pattern: str, text: str, flags: str = "") -> dict:
    """Test a regex pattern against text. Returns matches, groups, count."""
    try:
        import re as _re
        flag_map = {"i": _re.IGNORECASE, "m": _re.MULTILINE, "s": _re.DOTALL}
        compiled_flags = 0
        for f in flags.lower():
            compiled_flags |= flag_map.get(f, 0)
        rx = _re.compile(pattern, compiled_flags)
        matches = list(rx.finditer(text))
        result = []
        for m in matches[:20]:
            result.append({"match": m.group(0), "start": m.start(), "end": m.end(), "groups": list(m.groups())})
        return {"ok": True, "count": len(matches), "matches": result, "pattern": pattern}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def git_add(repo: str, path: str = ".") -> dict:
    """Stage files for commit. path: file or '.' for all."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    result = subprocess.run(
        ["git", "add", path],
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": result.stdout or result.stderr or ""}


def git_commit(repo: str, message: str, add_all: bool = False) -> dict:
    """Commit staged changes. If add_all=True, stages everything first."""
    repo_path = Path(repo)
    if not inside_sandbox(repo_path):
        return {"ok": False, "error": "Outside sandbox"}
    if add_all:
        subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {"ok": result.returncode == 0, "output": (result.stdout or result.stderr or "")[:2000]}


def save_note(content: str, tag: str = "note") -> dict:
    """
    Save a note directly to Layla's memory as a learning.
    Use this to remember facts, preferences, or observations mid-conversation.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.db import save_learning
        save_learning(content=content[:800], kind=tag)
        return {"ok": True, "saved": content[:100]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_memories(query: str, n: int = 8) -> dict:
    """
    Search Layla's own memory (learnings + semantic recall) for relevant past knowledge.
    Returns the most relevant stored memories for the given query.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from layla.memory.vector_store import search_memories_full
        results = search_memories_full(query, k=n, use_rerank=False)
        items = [r.get("content", "") for r in results if r.get("content")]
        return {"ok": True, "memories": items, "count": len(items)}
    except Exception as e:
        try:
            from layla.memory.db import get_recent_learnings
            rows = get_recent_learnings(n=n)
            items = [r.get("content", "") for r in rows if r.get("content")]
            return {"ok": True, "memories": items, "count": len(items), "fallback": True}
        except Exception:
            return {"ok": False, "error": str(e)}


# ─── Research & Information tools ─────────────────────────────────────────────

def read_pdf(path: str, max_pages: int = 30) -> dict:
    """
    Extract text from a PDF file using PyMuPDF.
    Returns text per page up to max_pages. Falls back to pypdf if fitz not installed.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    # Try PyMuPDF (fitz) first
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(target))
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(f"--- Page {i+1} ---\n{page.get_text()}")
        doc.close()
        full = "\n".join(pages)
        return {"ok": True, "path": str(target), "pages": min(len(doc), max_pages), "text": full[:12000]}
    except ImportError:
        pass
    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(target))
        pages = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            pages.append(f"--- Page {i+1} ---\n{page.extract_text() or ''}")
        full = "\n".join(pages)
        return {"ok": True, "path": str(target), "pages": min(len(reader.pages), max_pages), "text": full[:12000]}
    except ImportError:
        return {"ok": False, "error": "PDF reading requires PyMuPDF or pypdf: pip install PyMuPDF"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_article(url: str) -> dict:
    """
    Extract clean text from a web article using trafilatura.
    Much cleaner than raw fetch — removes nav, ads, footers. Ideal for research.
    """
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"ok": False, "error": "Could not fetch URL"}
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if not text:
            # Fallback to raw text
            text = trafilatura.extract(downloaded, favor_recall=True)
        if not text:
            return {"ok": False, "error": "Could not extract content from page"}
        title = ""
        try:
            meta = trafilatura.extract_metadata(downloaded)
            if meta:
                title = meta.title or ""
        except Exception:
            pass
        return {"ok": True, "url": url, "title": title, "text": text[:10000], "chars": len(text)}
    except ImportError:
        return {"ok": False, "error": "trafilatura not installed: pip install trafilatura"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def wiki_search(query: str, sentences: int = 8, lang: str = "en") -> dict:
    """
    Search Wikipedia and return a summary. sentences controls summary length.
    Returns the intro, URL, and a list of related page titles.
    """
    try:
        import wikipedia
        wikipedia.set_lang(lang)
        try:
            summary = wikipedia.summary(query, sentences=sentences, auto_suggest=True)
            page = wikipedia.page(query, auto_suggest=True)
            return {
                "ok": True,
                "query": query,
                "title": page.title,
                "url": page.url,
                "summary": summary,
                "related": page.links[:10],
            }
        except wikipedia.DisambiguationError as e:
            # Return top options on disambiguation
            return {"ok": True, "query": query, "disambiguation": True, "options": e.options[:8]}
        except wikipedia.PageError:
            results = wikipedia.search(query, results=5)
            return {"ok": False, "query": query, "error": "Page not found", "suggestions": results}
    except ImportError:
        return {"ok": False, "error": "wikipedia package not installed: pip install wikipedia-api"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def ddg_search(query: str, max_results: int = 10, region: str = "wt-wt") -> dict:
    """
    DuckDuckGo web search — pure Python, no browser required.
    Returns results with title, href, body snippet.
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=region, max_results=max_results))
        return {"ok": True, "query": query, "results": results, "count": len(results)}
    except ImportError:
        return {"ok": False, "error": "duckduckgo-search not installed: pip install duckduckgo-search"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def arxiv_search(query: str, max_results: int = 5, sort_by: str = "relevance") -> dict:
    """
    Search arXiv for papers. Returns title, authors, abstract, PDF URL, published date.
    sort_by: 'relevance' | 'lastUpdatedDate' | 'submittedDate'
    """
    try:
        import arxiv
        sort_map = {
            "relevance": arxiv.SortCriterion.Relevance,
            "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
            "submittedDate": arxiv.SortCriterion.SubmittedDate,
        }
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_map.get(sort_by, arxiv.SortCriterion.Relevance),
        )
        papers = []
        for r in client.results(search):
            papers.append({
                "title": r.title,
                "authors": [str(a) for a in r.authors[:5]],
                "abstract": (r.summary or "")[:500],
                "pdf_url": r.pdf_url,
                "published": str(r.published)[:10] if r.published else "",
                "arxiv_id": r.entry_id.split("/")[-1],
                "categories": r.categories[:3],
            })
        return {"ok": True, "query": query, "results": papers, "count": len(papers)}
    except ImportError:
        return {"ok": False, "error": "arxiv not installed: pip install arxiv"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def math_eval(expression: str) -> dict:
    """
    Safely evaluate a mathematical expression. Supports: +, -, *, /, **, %, //, abs, round,
    min, max, sum, int, float, sqrt, log, sin, cos, tan, pi, e, and more.
    No arbitrary code execution — uses a strict AST whitelist.
    """
    import ast as _ast, math as _math, operator as _op

    _SAFE_NODES = (
        _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Call, _ast.Constant,
        _ast.Add, _ast.Sub, _ast.Mul, _ast.Div, _ast.Pow, _ast.Mod, _ast.FloorDiv,
        _ast.UAdd, _ast.USub, _ast.Compare, _ast.Lt, _ast.Gt, _ast.LtE, _ast.GtE,
        _ast.Eq, _ast.NotEq, _ast.BoolOp, _ast.And, _ast.Or, _ast.Name, _ast.List,
        _ast.Tuple,
    )
    _SAFE_FUNCS = {
        "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
        "int": int, "float": float, "bool": bool,
        "sqrt": _math.sqrt, "log": _math.log, "log2": _math.log2, "log10": _math.log10,
        "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
        "asin": _math.asin, "acos": _math.acos, "atan": _math.atan, "atan2": _math.atan2,
        "ceil": _math.ceil, "floor": _math.floor, "trunc": _math.trunc,
        "factorial": _math.factorial, "gcd": _math.gcd,
        "degrees": _math.degrees, "radians": _math.radians,
        "pi": _math.pi, "e": _math.e, "tau": _math.tau, "inf": _math.inf,
        "pow": pow, "divmod": divmod,
    }

    def _safe_eval(node):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"Disallowed operation: {type(node).__name__}")
        if isinstance(node, _ast.Constant):
            return node.value
        if isinstance(node, _ast.Name):
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, _ast.BinOp):
            ops = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mul: _op.mul,
                   _ast.Div: _op.truediv, _ast.Pow: _op.pow, _ast.Mod: _op.mod,
                   _ast.FloorDiv: _op.floordiv}
            return ops[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
        if isinstance(node, _ast.UnaryOp):
            ops = {_ast.UAdd: _op.pos, _ast.USub: _op.neg}
            return ops[type(node.op)](_safe_eval(node.operand))
        if isinstance(node, _ast.Call):
            func = _safe_eval(node.func)
            args = [_safe_eval(a) for a in node.args]
            return func(*args)
        if isinstance(node, (_ast.List, _ast.Tuple)):
            return [_safe_eval(el) for el in node.elts]
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    try:
        tree = _ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree.body)
        return {"ok": True, "expression": expression, "result": result, "result_str": str(result)}
    except ZeroDivisionError:
        return {"ok": False, "error": "Division by zero"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def read_csv(path: str, max_rows: int = 50, describe: bool = True) -> dict:
    """
    Read a CSV file and return a summary. max_rows controls rows returned.
    If describe=True, returns statistical summary (count, mean, std, etc.).
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import pandas as _pd
        df = _pd.read_csv(str(target))
        result: dict = {
            "ok": True,
            "path": str(target),
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "sample": df.head(max_rows).to_dict(orient="records"),
            "null_counts": df.isnull().sum().to_dict(),
        }
        if describe:
            try:
                result["stats"] = df.describe().to_dict()
            except Exception:
                pass
        return result
    except ImportError:
        # Fallback to stdlib csv
        import csv as _csv
        with open(str(target), newline="", encoding="utf-8", errors="replace") as f:
            reader = _csv.DictReader(f)
            rows = [row for _, row in zip(range(max_rows + 1), reader)]
        return {"ok": True, "path": str(target), "columns": reader.fieldnames or [], "sample": rows[:max_rows]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def count_tokens(text: str, model: str = "gpt-4") -> dict:
    """
    Estimate token count for text. Uses tiktoken if available, else rough approximation.
    Rough rule: ~4 chars per token for English, ~2.5 for code.
    """
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(model)
        tokens = enc.encode(text)
        return {"ok": True, "tokens": len(tokens), "model": model, "method": "tiktoken"}
    except ImportError:
        # Rough estimate: split on whitespace and punctuation
        import re as _re
        words = len(_re.split(r"\s+", text.strip()))
        chars = len(text)
        rough = max(int(chars / 4), words)
        return {"ok": True, "tokens": rough, "model": "estimate", "method": "rough (~4 chars/token)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def http_request(url: str, method: str = "GET", body: str = "", headers: dict | None = None, timeout: int = 15) -> dict:
    """
    Make an HTTP request. method: GET | POST | PUT | DELETE | PATCH.
    Returns status, response text (truncated to 8000 chars).
    Use for webhooks, REST APIs, testing endpoints.
    """
    import urllib.request, urllib.error
    method = method.upper()
    hdrs = {"User-Agent": "Layla/2.0 research agent", "Accept": "application/json,text/html,*/*"}
    if headers:
        hdrs.update(headers)
    try:
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read(80000).decode("utf-8", errors="replace")
            return {
                "ok": resp.status < 400,
                "status": resp.status,
                "url": url,
                "text": content[:8000],
                "headers": dict(resp.headers),
            }
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read(2000).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": str(e), "text": body_text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def python_ast(path: str) -> dict:
    """
    Analyze a Python file's AST structure. Returns:
    - Top-level functions and classes (with line numbers, decorators, docstrings)
    - Imports
    - Global variables
    - Complexity indicators (nested function depth, line count)
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    import ast as _ast
    try:
        source = target.read_text(encoding="utf-8", errors="replace")
        tree = _ast.parse(source, filename=str(target))
    except SyntaxError as e:
        return {"ok": False, "error": f"SyntaxError: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    functions, classes, imports, globals_list = [], [], [], []

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            else:
                mod = node.module or ""
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)

    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            decorators = [_ast.unparse(d) for d in (node.decorator_list or [])]
            doc = _ast.get_docstring(node) or ""
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "async": isinstance(node, _ast.AsyncFunctionDef),
                "args": [a.arg for a in node.args.args],
                "decorators": decorators,
                "docstring": doc[:120],
            })
        elif isinstance(node, _ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    methods.append({"name": item.name, "line": item.lineno})
            doc = _ast.get_docstring(node) or ""
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": [_ast.unparse(b) for b in node.bases],
                "methods": methods,
                "docstring": doc[:120],
            })
        elif isinstance(node, _ast.Assign):
            for target in node.targets:
                if isinstance(target, _ast.Name) and target.id.isupper():
                    globals_list.append(target.id)

    lines = source.splitlines()
    return {
        "ok": True,
        "path": str(target),
        "line_count": len(lines),
        "functions": functions,
        "classes": classes,
        "imports": list(dict.fromkeys(imports))[:30],
        "constants": globals_list[:20],
    }


def project_discovery_tool(workspace_root: str = "") -> dict:
    """
    Run project discovery on a workspace: detects tech stack, file types, entry points,
    README summary, and key structural patterns. Useful for orienting to an unfamiliar codebase.
    """
    try:
        agent_dir = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(agent_dir))
        from services.project_discovery import discover_project
        root = workspace_root or str(Path.home())
        return discover_project(root)
    except Exception as e:
        # Fallback: lightweight manual discovery
        try:
            root_path = Path(workspace_root or ".").expanduser().resolve()
            if not root_path.exists():
                return {"ok": False, "error": "Path not found"}
            files = []
            for f in root_path.rglob("*"):
                if f.is_file() and not any(p in str(f) for p in (".git", ".venv", "__pycache__", "node_modules")):
                    files.append(str(f.relative_to(root_path)))
                    if len(files) >= 200:
                        break
            ext_counts: dict = {}
            for f in files:
                ext = Path(f).suffix.lower()
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
            readme = ""
            for name in ("README.md", "readme.md", "README.txt"):
                rp = root_path / name
                if rp.exists():
                    readme = rp.read_text(encoding="utf-8", errors="replace")[:1000]
                    break
            return {
                "ok": True, "root": str(root_path), "file_count": len(files),
                "extensions": dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:15]),
                "readme_preview": readme, "files_sample": files[:40],
            }
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


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
    # Extended tools
    "json_query": {"fn": json_query, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "diff_files": {"fn": diff_files, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "env_info": {"fn": env_info, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "regex_test": {"fn": regex_test, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_add": {"fn": git_add, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "git_commit": {"fn": git_commit, "dangerous": True, "require_approval": True, "risk_level": "medium"},
    "save_note": {"fn": save_note, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "search_memories": {"fn": search_memories, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Research & Information tools
    "read_pdf": {"fn": read_pdf, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "fetch_article": {"fn": fetch_article, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "wiki_search": {"fn": wiki_search, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "ddg_search": {"fn": ddg_search, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "arxiv_search": {"fn": arxiv_search, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "math_eval": {"fn": math_eval, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "read_csv": {"fn": read_csv, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "count_tokens": {"fn": count_tokens, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "http_request": {"fn": http_request, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "python_ast": {"fn": python_ast, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "project_discovery": {"fn": project_discovery_tool, "dangerous": False, "require_approval": False, "risk_level": "low"},
}

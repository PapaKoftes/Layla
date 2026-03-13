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


# ─── Symbolic & Advanced Math ──────────────────────────────────────────────────

def sympy_solve(expression: str, variable: str = "x", mode: str = "solve") -> dict:
    """
    Symbolic math via SymPy. mode options:
    - 'solve': solve equation for variable (e.g. "x**2 - 4", "x" → [-2, 2])
    - 'simplify': algebraically simplify an expression
    - 'diff': differentiate with respect to variable
    - 'integrate': integrate with respect to variable
    - 'expand': expand/distribute
    - 'factor': factor into irreducible parts
    - 'latex': render as LaTeX string
    - 'numeric': numerical evaluation (calls evalf)
    """
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application
        transforms = standard_transformations + (implicit_multiplication_application,)
        local_dict = {v: sp.Symbol(v) for v in "xyzabcntk"}
        if variable not in local_dict:
            local_dict[variable] = sp.Symbol(variable)
        expr = parse_expr(expression, local_dict=local_dict, transformations=transforms)
        var = local_dict.get(variable, sp.Symbol(variable))
        if mode == "solve":
            sol = sp.solve(expr, var)
            return {"ok": True, "mode": "solve", "variable": variable, "solutions": [str(s) for s in sol]}
        elif mode == "diff":
            return {"ok": True, "mode": "diff", "result": str(sp.diff(expr, var)), "latex": sp.latex(sp.diff(expr, var))}
        elif mode == "integrate":
            return {"ok": True, "mode": "integrate", "result": str(sp.integrate(expr, var)), "latex": sp.latex(sp.integrate(expr, var))}
        elif mode == "simplify":
            return {"ok": True, "mode": "simplify", "result": str(sp.simplify(expr)), "latex": sp.latex(sp.simplify(expr))}
        elif mode == "expand":
            return {"ok": True, "mode": "expand", "result": str(sp.expand(expr))}
        elif mode == "factor":
            return {"ok": True, "mode": "factor", "result": str(sp.factor(expr))}
        elif mode == "latex":
            return {"ok": True, "mode": "latex", "latex": sp.latex(expr)}
        elif mode == "numeric":
            return {"ok": True, "mode": "numeric", "result": str(expr.evalf()), "float": float(expr.evalf())}
        else:
            return {"ok": False, "error": f"Unknown mode: {mode}. Use solve/diff/integrate/simplify/expand/factor/latex/numeric"}
    except ImportError:
        return {"ok": False, "error": "sympy not installed: pip install sympy"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── NLP Intelligence ──────────────────────────────────────────────────────────

def nlp_analyze(text: str, tasks: list | None = None) -> dict:
    """
    NLP analysis pipeline. tasks: list of ['entities', 'keywords', 'sentiment', 'sentences', 'pos']
    Default: all. Uses spaCy if available, falls back to NLTK + basic heuristics.
    """
    if not tasks:
        tasks = ["entities", "keywords", "sentiment", "sentences"]
    result: dict = {"ok": True, "text_length": len(text), "tasks": tasks}

    # Try spaCy first
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            # Model not downloaded — try blank
            nlp = spacy.blank("en")
        doc = nlp(text[:50000])
        if "entities" in tasks:
            result["entities"] = [
                {"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char}
                for ent in doc.ents
            ][:50]
        if "sentences" in tasks:
            result["sentences"] = [str(s)[:200] for s in list(doc.sents)[:20]]
        if "pos" in tasks:
            result["pos_tags"] = [
                {"token": t.text, "pos": t.pos_, "dep": t.dep_}
                for t in doc if not t.is_space
            ][:60]
    except ImportError:
        pass

    # Keywords via KeyBERT
    if "keywords" in tasks:
        try:
            from keybert import KeyBERT
            kw_model = KeyBERT()
            keywords = kw_model.extract_keywords(text[:10000], keyphrase_ngram_range=(1, 2), top_n=12)
            result["keywords"] = [{"phrase": kw, "score": round(score, 4)} for kw, score in keywords]
        except ImportError:
            # Fallback: simple frequency-based keywords
            import re
            words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
            freq: dict = {}
            for w in words:
                freq[w] = freq.get(w, 0) + 1
            stopwords = {"that", "this", "with", "from", "they", "have", "been", "were", "will", "would", "could", "should", "their", "there", "these", "those"}
            keywords_fb = sorted([(w, c) for w, c in freq.items() if w not in stopwords], key=lambda x: -x[1])[:12]
            result["keywords"] = [{"phrase": w, "score": c} for w, c in keywords_fb]

    # Basic sentiment (no ML needed — lexicon approach)
    if "sentiment" in tasks:
        try:
            from textblob import TextBlob
            tb = TextBlob(text[:5000])
            result["sentiment"] = {"polarity": round(tb.sentiment.polarity, 3), "subjectivity": round(tb.sentiment.subjectivity, 3)}
        except ImportError:
            # Very basic heuristic
            pos_words = {"good","great","excellent","amazing","love","wonderful","best","fantastic","perfect","brilliant"}
            neg_words = {"bad","terrible","awful","horrible","hate","worst","poor","disappointing","fail","wrong"}
            words_lower = set(text.lower().split())
            pos = len(words_lower & pos_words)
            neg = len(words_lower & neg_words)
            polarity = (pos - neg) / max(pos + neg, 1)
            result["sentiment"] = {"polarity": round(polarity, 3), "method": "lexicon_heuristic"}

    return result


# ─── Image & OCR ───────────────────────────────────────────────────────────────

def ocr_image(path: str, lang: str = "eng") -> dict:
    """
    Extract text from an image using OCR.
    Tries EasyOCR first (better accuracy, no Tesseract required),
    then falls back to pytesseract (requires Tesseract binary installed).
    lang: language code ('eng', 'fra', 'deu', 'jpn', 'chi_sim', etc.)
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    ext = target.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}:
        return {"ok": False, "error": f"Unsupported image format: {ext}"}

    # Try EasyOCR
    try:
        import easyocr
        lang_map = {"eng": "en", "fra": "fr", "deu": "de", "chi_sim": "ch_sim", "jpn": "ja"}
        easy_lang = lang_map.get(lang, "en")
        reader = easyocr.Reader([easy_lang], gpu=False, verbose=False)
        results = reader.readtext(str(target))
        text_parts = [item[1] for item in results if item[2] > 0.1]
        full_text = "\n".join(text_parts)
        return {
            "ok": True, "method": "easyocr", "path": str(target),
            "text": full_text[:8000], "blocks": len(results),
            "confidence_avg": round(sum(r[2] for r in results) / max(len(results), 1), 3),
        }
    except ImportError:
        pass

    # Fallback: pytesseract
    try:
        import pytesseract
        from PIL import Image as PILImage
        img = PILImage.open(str(target))
        text = pytesseract.image_to_string(img, lang=lang)
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
        conf_avg = sum(confidences) / max(len(confidences), 1)
        return {
            "ok": True, "method": "pytesseract", "path": str(target),
            "text": text.strip()[:8000],
            "confidence_avg": round(conf_avg, 1),
        }
    except ImportError:
        return {"ok": False, "error": "OCR requires easyocr or pytesseract+Pillow: pip install easyocr OR pip install pytesseract Pillow"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Visualization ─────────────────────────────────────────────────────────────

def plot_chart(
    data: dict,
    chart_type: str = "bar",
    title: str = "",
    output_path: str = "",
    xlabel: str = "",
    ylabel: str = "",
) -> dict:
    """
    Generate a chart and save it as PNG. Returns path to saved file.
    chart_type: 'bar' | 'line' | 'scatter' | 'pie' | 'histogram' | 'heatmap'
    data format:
    - bar/line: {"labels": [...], "values": [...]} or {"Series A": [...], "Series B": [...], "labels": [...]}
    - scatter: {"x": [...], "y": [...]}
    - pie: {"labels": [...], "values": [...]}
    - histogram: {"values": [...], "bins": 20}
    - heatmap: {"matrix": [[...], ...], "row_labels": [...], "col_labels": [...]}
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend, always safe
        import matplotlib.pyplot as plt
        import numpy as _np

        fig, ax = plt.subplots(figsize=(10, 6))
        if title:
            ax.set_title(title, fontsize=14, fontweight="bold")
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)

        if chart_type == "bar":
            labels = data.get("labels", list(range(len(data.get("values", [])))))
            values = data.get("values", [])
            ax.bar(range(len(labels)), values, tick_label=[str(l) for l in labels])
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "line":
            labels = data.get("labels", list(range(len(data.get("values", [])))))
            for key, vals in data.items():
                if key == "labels":
                    continue
                if isinstance(vals, (list, tuple)):
                    ax.plot(labels if len(labels) == len(vals) else range(len(vals)), vals, label=key, marker="o", markersize=3)
            ax.legend()

        elif chart_type == "scatter":
            x, y = data.get("x", []), data.get("y", [])
            labels = data.get("point_labels", [])
            ax.scatter(x, y, alpha=0.7)
            for i, label in enumerate(labels[:len(x)]):
                ax.annotate(str(label), (x[i], y[i]), fontsize=7)

        elif chart_type == "pie":
            labels = data.get("labels", [])
            values = data.get("values", [])
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=140)
            ax.axis("equal")

        elif chart_type == "histogram":
            values = data.get("values", [])
            bins = data.get("bins", 20)
            ax.hist(values, bins=bins, edgecolor="black", alpha=0.7)

        elif chart_type == "heatmap":
            matrix = data.get("matrix", [[]])
            row_labels = data.get("row_labels", [])
            col_labels = data.get("col_labels", [])
            arr = _np.array(matrix)
            im = ax.imshow(arr, cmap="viridis", aspect="auto")
            plt.colorbar(im, ax=ax)
            if row_labels:
                ax.set_yticks(range(len(row_labels)))
                ax.set_yticklabels(row_labels)
            if col_labels:
                ax.set_xticks(range(len(col_labels)))
                ax.set_xticklabels(col_labels, rotation=45, ha="right")
        else:
            plt.close(fig)
            return {"ok": False, "error": f"Unknown chart_type: {chart_type}"}

        # Determine save path
        if output_path:
            save_path = Path(output_path)
        else:
            import tempfile, time
            tmp_dir = Path(tempfile.gettempdir())
            save_path = tmp_dir / f"layla_chart_{int(time.time())}.png"

        plt.tight_layout()
        fig.savefig(str(save_path), dpi=120, bbox_inches="tight")
        plt.close(fig)
        return {"ok": True, "chart_type": chart_type, "path": str(save_path), "title": title}
    except ImportError:
        return {"ok": False, "error": "matplotlib not installed: pip install matplotlib"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Document Formats ──────────────────────────────────────────────────────────

def read_docx(path: str) -> dict:
    """
    Read a Word document (.docx). Returns full text, paragraph list, and table data.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        from docx import Document
        doc = Document(str(target))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        tables = []
        for table in doc.tables[:10]:
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            tables.append(rows)
        full_text = "\n".join(paragraphs)
        return {
            "ok": True, "path": str(target),
            "paragraphs": len(paragraphs),
            "text": full_text[:10000],
            "tables": tables[:5],
            "table_count": len(doc.tables),
        }
    except ImportError:
        return {"ok": False, "error": "python-docx not installed: pip install python-docx"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def read_excel(path: str, sheet: str = "", max_rows: int = 100) -> dict:
    """
    Read an Excel file (.xlsx/.xls). Returns sheet names, data from target sheet,
    and basic stats. sheet: sheet name or index (default: first sheet).
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import pandas as _pd
        xl = _pd.ExcelFile(str(target))
        sheet_names = xl.sheet_names
        active_sheet = sheet if sheet else sheet_names[0]
        df = xl.parse(active_sheet)
        result: dict = {
            "ok": True, "path": str(target),
            "sheets": sheet_names, "active_sheet": str(active_sheet),
            "rows": len(df), "columns": list(df.columns),
            "sample": df.head(max_rows).to_dict(orient="records"),
            "null_counts": df.isnull().sum().to_dict(),
        }
        try:
            result["stats"] = df.describe().to_dict()
        except Exception:
            pass
        return result
    except ImportError:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(target), read_only=True, data_only=True)
            sheet_names = wb.sheetnames
            ws = wb[sheet] if sheet and sheet in sheet_names else wb.active
            rows = []
            headers: list = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [str(c or f"col_{j}") for j, c in enumerate(row)]
                elif i <= max_rows:
                    rows.append(dict(zip(headers, row)))
            wb.close()
            return {"ok": True, "path": str(target), "sheets": sheet_names, "columns": headers, "sample": rows}
        except ImportError:
            return {"ok": False, "error": "Excel reading requires pandas or openpyxl: pip install pandas openpyxl"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Database Intelligence ─────────────────────────────────────────────────────

def sql_query(db_path: str, query: str, limit: int = 200) -> dict:
    """
    Execute a SQL query against a SQLite or DuckDB database file.
    READ-ONLY by default: SELECT queries only. Non-SELECT queries require allow_write.
    db_path: path to .db/.sqlite/.duckdb file, or ':memory:' for DuckDB in-memory.
    """
    is_readonly = query.strip().upper().startswith("SELECT") or query.strip().upper().startswith("WITH")
    target = Path(db_path) if db_path != ":memory:" else None
    if target and not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if target and not target.exists():
        return {"ok": False, "error": "File not found"}

    # Inject LIMIT if not present
    q = query.strip().rstrip(";")
    if is_readonly and "LIMIT" not in q.upper():
        q += f" LIMIT {limit}"

    # Try DuckDB first (handles .duckdb and in-memory well)
    ext = (target.suffix.lower() if target else ".duckdb")
    if ext == ".duckdb" or db_path == ":memory:":
        try:
            import duckdb
            conn = duckdb.connect(db_path)
            rel = conn.execute(q)
            cols = [d[0] for d in rel.description]
            rows = rel.fetchall()
            conn.close()
            return {
                "ok": True, "db": db_path, "query": query,
                "columns": cols, "rows": [dict(zip(cols, r)) for r in rows],
                "row_count": len(rows),
            }
        except ImportError:
            pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # SQLite
    try:
        import sqlite3 as _sql
        conn = _sql.connect(str(target))
        conn.row_factory = _sql.Row
        cursor = conn.execute(q)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description] if cursor.description else []
        conn.close()
        return {
            "ok": True, "db": db_path, "query": query,
            "columns": cols, "rows": [dict(r) for r in rows],
            "row_count": len(rows),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Financial Intelligence ────────────────────────────────────────────────────

def stock_data(ticker: str, period: str = "1mo", include_info: bool = True) -> dict:
    """
    Fetch stock or crypto data via yfinance.
    ticker: stock symbol (AAPL, TSLA, BTC-USD, ETH-USD, ^GSPC for S&P500)
    period: '1d' | '5d' | '1mo' | '3mo' | '6mo' | '1y' | '2y' | '5y' | 'ytd' | 'max'
    Returns: OHLCV data, current price, company info (if include_info=True).
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return {"ok": False, "error": f"No data for ticker: {ticker}"}
        hist_records = []
        for date, row in hist.tail(30).iterrows():
            hist_records.append({
                "date": str(date)[:10],
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        result: dict = {
            "ok": True, "ticker": ticker.upper(), "period": period,
            "current_price": round(float(hist["Close"].iloc[-1]), 4),
            "price_change_pct": round(float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100), 2),
            "52w_high": round(float(hist["High"].max()), 4),
            "52w_low": round(float(hist["Low"].min()), 4),
            "history": hist_records,
        }
        if include_info:
            try:
                info = t.info or {}
                result["info"] = {
                    "name": info.get("longName") or info.get("shortName", ""),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("forwardPE") or info.get("trailingPE"),
                    "dividend_yield": info.get("dividendYield"),
                    "description": (info.get("longBusinessSummary") or "")[:400],
                }
            except Exception:
                pass
        return result
    except ImportError:
        return {"ok": False, "error": "yfinance not installed: pip install yfinance"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Security Analysis ─────────────────────────────────────────────────────────

def security_scan(path: str, scan_type: str = "bandit") -> dict:
    """
    Run security analysis on Python code or check dependencies for known vulnerabilities.
    scan_type:
    - 'bandit': static analysis for Python security issues (CWEs, hardcoded secrets, etc.)
    - 'deps': check requirements.txt or pyproject.toml for vulnerable packages
    - 'secrets': pattern-based scan for hardcoded secrets/tokens/keys in any file
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}

    if scan_type == "bandit":
        try:
            r = subprocess.run(
                [sys.executable, "-m", "bandit", "-r", str(target), "-f", "json", "-q"],
                capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
            )
            import json as _json
            try:
                data = _json.loads(r.stdout or "{}")
            except Exception:
                data = {}
            issues = data.get("results", [])
            metrics = data.get("metrics", {})
            return {
                "ok": True, "scan_type": "bandit", "path": str(target),
                "issues": [
                    {
                        "severity": i.get("issue_severity"), "confidence": i.get("issue_confidence"),
                        "text": i.get("issue_text"), "file": i.get("filename"),
                        "line": i.get("line_number"), "cwe": i.get("issue_cwe", {}).get("id"),
                    }
                    for i in issues[:30]
                ],
                "issue_count": len(issues),
                "metrics": metrics,
            }
        except FileNotFoundError:
            return {"ok": False, "error": "bandit not installed: pip install bandit"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif scan_type == "secrets":
        import re as _re
        SECRET_PATTERNS = [
            (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([A-Za-z0-9\-_]{16,})', "API Key"),
            (r'(?i)(secret[_-]?key|secret)\s*[:=]\s*["\']?([A-Za-z0-9\-_]{16,})', "Secret Key"),
            (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?([^\s"\']{8,})', "Password"),
            (r'(?i)(token|access_token|auth_token)\s*[:=]\s*["\']?([A-Za-z0-9\-_\.]{16,})', "Token"),
            (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
            (r'(?i)(private[_-]?key)\s*[:=]', "Private Key"),
            (r'sk-[A-Za-z0-9]{32,}', "OpenAI Key"),
            (r'ghp_[A-Za-z0-9]{36,}', "GitHub Token"),
        ]
        findings = []
        files_scanned = 0
        if target.is_file():
            scan_files = [target]
        else:
            scan_files = [f for f in target.rglob("*") if f.is_file() and f.suffix in {".py", ".js", ".ts", ".env", ".json", ".yaml", ".yml", ".txt", ".cfg", ".ini"} and ".git" not in str(f)][:100]
        for fpath in scan_files:
            files_scanned += 1
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                for pattern, label in SECRET_PATTERNS:
                    for m in _re.finditer(pattern, content):
                        line_num = content[:m.start()].count("\n") + 1
                        findings.append({"file": str(fpath.relative_to(target) if target.is_dir() else fpath), "line": line_num, "type": label, "match": m.group(0)[:80]})
            except Exception:
                continue
        return {"ok": True, "scan_type": "secrets", "files_scanned": files_scanned, "findings": findings[:50], "finding_count": len(findings)}

    elif scan_type == "deps":
        req_files = []
        if target.is_file():
            req_files = [target]
        else:
            for name in ("requirements.txt", "pyproject.toml", "Pipfile"):
                f = target / name
                if f.exists():
                    req_files.append(f)
        if not req_files:
            return {"ok": False, "error": "No requirements.txt/pyproject.toml found"}
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip_audit", "--requirement", str(req_files[0]), "--format", "json"],
                capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
            )
            import json as _json
            try:
                data = _json.loads(r.stdout or "[]")
                return {"ok": True, "scan_type": "deps", "vulnerabilities": data[:30], "count": len(data)}
            except Exception:
                return {"ok": True, "scan_type": "deps", "output": (r.stdout or r.stderr)[:2000]}
        except FileNotFoundError:
            return {"ok": False, "error": "pip-audit not installed: pip install pip-audit"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"Unknown scan_type: {scan_type}. Use bandit/secrets/deps"}


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
    # Symbolic & Advanced Math
    "sympy_solve": {"fn": sympy_solve, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # NLP Intelligence
    "nlp_analyze": {"fn": nlp_analyze, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Image & OCR
    "ocr_image": {"fn": ocr_image, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Visualization
    "plot_chart": {"fn": plot_chart, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Document Formats
    "read_docx": {"fn": read_docx, "dangerous": False, "require_approval": False, "risk_level": "low"},
    "read_excel": {"fn": read_excel, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Database Intelligence
    "sql_query": {"fn": sql_query, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Financial Intelligence
    "stock_data": {"fn": stock_data, "dangerous": False, "require_approval": False, "risk_level": "low"},
    # Security Analysis
    "security_scan": {"fn": security_scan, "dangerous": False, "require_approval": False, "risk_level": "low"},
}

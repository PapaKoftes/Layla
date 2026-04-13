"""Tool implementations — domain: code."""
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
            except Exception as e:
                logger.debug("grep_code read failed %s: %s", f, e)
                continue
            if len(results) >= 50:
                break
        return {"ok": True, "matches": "\n".join(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def search_codebase(symbol: str, root: str = "") -> dict:
    """Find functions/classes and semantic chunks matching symbol (read-only). root defaults to sandbox."""
    try:
        from services.code_intelligence import search_symbols
    except Exception as e:
        return {"ok": False, "error": str(e), "matches": []}
    root_path = Path(root).expanduser().resolve() if (root or "").strip() else _get_sandbox()
    if not inside_sandbox(root_path):
        return {"ok": False, "error": "Workspace outside sandbox", "matches": []}
    return search_symbols(root_path, symbol, k=25)

def run_python(code: str, cwd: str) -> dict:
    try:
        from services.sandbox.python_runner import run_python_file

        cwd_path = Path(cwd)
        return run_python_file(code or "", cwd_path, inside_sandbox_check=inside_sandbox)
    except Exception as e:
        logger.debug("python runner failed, fallback: %s", e)
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
            [sys.executable, tmp_path],
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

def run_tests(cwd: str, pattern: str = "", extra_args: str = "", timeout_s: int = 120) -> dict:
    """
    Discover and run pytest (or unittest) in cwd. pattern: test file/pattern e.g. tests/ or test_foo.py.
    extra_args: e.g. -v -x. Returns pass/fail counts and output.
    """
    cwd_path = Path(cwd)
    if not inside_sandbox(cwd_path):
        return {"ok": False, "error": "cwd outside sandbox"}
    if not cwd_path.exists():
        return {"ok": False, "error": "Path not found"}
    # Prefer pytest
    args = ["python", "-m", "pytest", pattern] if pattern else ["python", "-m", "pytest"]
    if extra_args:
        args.extend(extra_args.split())
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # Parse pytest output for pass/fail
        passed = failed = 0
        for line in out.splitlines():
            if " passed" in line or " passed," in line:
                for part in line.split():
                    if part.isdigit():
                        passed = int(part)
                        break
            if " failed" in line or " failed," in line:
                for part in line.replace(",", " ").split():
                    if part.isdigit():
                        failed = int(part)
                        break
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "passed": passed,
            "failed": failed,
            "output": out[:8000],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Tests timed out ({timeout_s}s)"}
    except FileNotFoundError:
        # Fallback: unittest
        try:
            proc = subprocess.run(
                ["python", "-m", "unittest", "discover", "-v"],
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": out[:8000], "runner": "unittest"}
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
        root = workspace_root or str(Path.cwd())
        return discover_project(root)
    except Exception as e:
        return {"ok": False, "error": str(e)}

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

def code_symbols(path: str, include_private: bool = False) -> dict:
    """
    Extract a complete symbol index from a Python file or directory.
    For each symbol: name, type, line, docstring, signature, parent class.
    include_private: include _ prefixed symbols (default False).
    Returns a structured symbol table useful for code navigation.
    """
    import ast as _ast

    def _extract(fpath: Path) -> dict:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source, filename=str(fpath))
        except Exception as e:
            return {"error": str(e), "symbols": [], "count": 0}
        symbols: list = []
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if not include_private and node.name.startswith("_"):
                    continue
                try:
                    sig = f"({', '.join(a.arg for a in node.args.args)})"
                except Exception:
                    sig = "()"
                symbols.append({"name": node.name, "type": "async_fn" if isinstance(node, _ast.AsyncFunctionDef) else "function", "line": node.lineno, "signature": sig, "docstring": (_ast.get_docstring(node) or "")[:100], "decorators": [_ast.unparse(d) for d in node.decorator_list]})
            elif isinstance(node, _ast.ClassDef):
                if not include_private and node.name.startswith("_"):
                    continue
                methods = []
                for item in node.body:
                    if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        if not include_private and item.name.startswith("_"):
                            continue
                        methods.append({"name": item.name, "line": item.lineno, "type": "method"})
                symbols.append({"name": node.name, "type": "class", "line": node.lineno, "bases": [_ast.unparse(b) for b in node.bases], "docstring": (_ast.get_docstring(node) or "")[:100], "methods": methods})
        return {"symbols": symbols, "count": len(symbols)}

    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}

    if target.is_file():
        return {"ok": True, "path": str(target), **_extract(target)}

    py_files = [f for f in target.rglob("*.py") if not any(p in str(f) for p in (".venv", "__pycache__"))][:50]
    all_symbols: dict = {}
    for f in py_files:
        all_symbols[str(f.relative_to(target))] = _extract(f)
    total = sum(v.get("count", 0) for v in all_symbols.values())
    return {"ok": True, "path": str(target), "files_analyzed": len(py_files), "total_symbols": total, "files": all_symbols}

def find_todos(path: str, tags: list | None = None) -> dict:
    """
    Scan a file or directory for TODO/FIXME/HACK/NOTE/BUG/REVIEW/OPTIMIZE comments.
    Returns each finding: file, line, tag type, message.
    """
    import re as _re
    if tags is None:
        tags = ["TODO", "FIXME", "HACK", "BUG", "REVIEW", "OPTIMIZE", "XXX", "NOTE", "WARN", "DEPRECATED"]
    tag_pattern = "|".join(_re.escape(t) for t in tags)
    rx = _re.compile(rf'(?:#|//|/\*|<!--)\s*({tag_pattern})\s*[:\-]?\s*(.*)', _re.IGNORECASE)
    CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".sh", ".yml", ".yaml", ".toml"}

    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}

    scan_files = [target] if target.is_file() else [
        f for f in target.rglob("*")
        if f.is_file() and f.suffix.lower() in CODE_EXTS and not any(p in str(f) for p in (".git", ".venv", "__pycache__", "node_modules"))
    ][:200]

    findings, files_scanned = [], 0
    for fpath in scan_files:
        files_scanned += 1
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
            for lineno, line in enumerate(lines, 1):
                for m in rx.finditer(line):
                    findings.append({"file": str(fpath.relative_to(target) if target.is_dir() else fpath), "line": lineno, "tag": m.group(1).upper(), "message": m.group(2).strip()[:120]})
        except Exception:
            continue

    by_tag: dict = {}
    for f in findings:
        by_tag[f["tag"]] = by_tag.get(f["tag"], 0) + 1
    return {"ok": True, "path": str(target), "files_scanned": files_scanned, "total_found": len(findings), "by_tag": by_tag, "findings": findings[:100]}

def dependency_graph(path: str) -> dict:
    """
    Build a Python import dependency graph for a file or package.
    Uses AST to extract import statements, resolves local vs external deps.
    Returns adjacency list + networkx metrics if available.
    """
    import ast as _ast

    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}

    root = target if target.is_dir() else target.parent
    local_modules = {f.stem for f in root.rglob("*.py") if not any(p in str(f) for p in (".venv", "__pycache__"))}

    def _get_imports(fpath: Path) -> list[str]:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source)
            imports = []
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    imports.extend(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, _ast.ImportFrom):
                    if node.module:
                        imports.append(node.module.split(".")[0])
            return list(dict.fromkeys(imports))
        except Exception:
            return []

    py_files = [target] if target.is_file() else [
        f for f in target.rglob("*.py") if not any(p in str(f) for p in (".venv", "__pycache__"))
    ][:30]

    edges: list[dict] = []
    nodes: set[str] = set()
    for fpath in py_files:
        module_name = fpath.stem
        nodes.add(module_name)
        for imp in _get_imports(fpath):
            nodes.add(imp)
            is_local = imp in local_modules
            edges.append({"from": module_name, "to": imp, "type": "local" if is_local else "external"})

    external_deps = list({e["to"] for e in edges if e["type"] == "external"})
    local_deps = [e for e in edges if e["type"] == "local"]
    result: dict = {"ok": True, "path": str(target), "nodes": list(nodes), "node_count": len(nodes), "edges": edges[:200], "edge_count": len(edges), "external_packages": external_deps, "local_edges": local_deps}

    try:
        import networkx as nx
        G = nx.DiGraph()
        G.add_nodes_from(nodes)
        G.add_edges_from([(e["from"], e["to"]) for e in edges])
        result["metrics"] = {"most_imported": sorted(dict(G.in_degree()).items(), key=lambda x: -x[1])[:5], "most_importing": sorted(dict(G.out_degree()).items(), key=lambda x: -x[1])[:5], "is_dag": nx.is_directed_acyclic_graph(G)}
    except Exception:
        pass
    return result

def code_metrics(path: str) -> dict:
    """
    Compute code quality metrics for Python files: LOC, blank/comment lines,
    function/class count, avg complexity, docstring coverage, high-complexity functions.
    """
    import ast as _ast

    def _file_metrics(fpath: Path) -> dict:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": str(e)}
        lines = source.splitlines()
        blank = sum(1 for ln in lines if not ln.strip())
        comment = sum(1 for ln in lines if ln.strip().startswith("#"))
        try:
            tree = _ast.parse(source)
        except SyntaxError as e:
            return {"loc": len(lines), "blank": blank, "syntax_error": str(e)}
        functions, classes = [], []
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno + 1)
                branches = sum(1 for n in _ast.walk(node) if isinstance(n, (_ast.If, _ast.While, _ast.For, _ast.ExceptHandler, _ast.BoolOp)))
                functions.append({"name": node.name, "len": (end or node.lineno+1) - node.lineno, "complexity": 1 + branches, "has_doc": bool(_ast.get_docstring(node))})
            elif isinstance(node, _ast.ClassDef):
                classes.append({"name": node.name, "methods": sum(1 for n in node.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))), "has_doc": bool(_ast.get_docstring(node))})
        avg_cc = round(sum(f["complexity"] for f in functions) / max(len(functions), 1), 2)
        doc_cov = round(sum(1 for f in functions if f["has_doc"]) / max(len(functions), 1) * 100, 1)
        return {"loc": len(lines), "blank": blank, "comment": comment, "code": len(lines)-blank-comment, "functions": len(functions), "classes": len(classes), "avg_complexity": avg_cc, "doc_coverage_pct": doc_cov, "high_complexity": [f["name"] for f in functions if f["complexity"] > 10], "longest": sorted(functions, key=lambda x: -x["len"])[:3]}

    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    if target.is_file():
        return {"ok": True, "path": str(target), **_file_metrics(target)}
    py_files = [f for f in target.rglob("*.py") if not any(p in str(f) for p in (".venv", "__pycache__"))][:50]
    totals = {"loc": 0, "functions": 0, "classes": 0}
    files = {}
    for f in py_files:
        m = _file_metrics(f)
        files[str(f.relative_to(target))] = m
        for k in totals:
            totals[k] += m.get(k, 0)
    return {"ok": True, "path": str(target), "files": len(py_files), "totals": totals, "file_metrics": files}

def code_lint(path: str, fix: bool = False) -> dict:
    """Run ruff linter on Python file/dir. fix=True auto-fixes. Falls back to syntax check."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    import json as _json
    cmd = [sys.executable, "-m", "ruff", "check", str(target), "--output-format", "json"]
    if fix:
        cmd.append("--fix")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace")
        violations = []
        for v in (_json.loads(r.stdout or "[]") or []):
            violations.append({"file": v.get("filename", ""), "line": v.get("location", {}).get("row"), "code": v.get("code", ""), "message": v.get("message", ""), "fixable": v.get("fix") is not None})
        by_code: dict = {}
        for v in violations:
            by_code[v["code"]] = by_code.get(v["code"], 0) + 1
        return {"ok": True, "tool": "ruff", "violations": len(violations), "by_code": dict(sorted(by_code.items(), key=lambda x: -x[1])[:20]), "details": violations[:50]}
    except FileNotFoundError:
        import ast as _ast
        errors = []
        files = [target] if target.is_file() else [f for f in target.rglob("*.py") if not any(p in str(f) for p in (".venv", "__pycache__"))][:30]
        for f in files:
            try:
                _ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as e:
                errors.append({"file": str(f), "line": e.lineno, "message": str(e)})
        return {"ok": True, "tool": "syntax_check_fallback", "syntax_errors": errors, "note": "Install ruff: pip install ruff"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def generate_gcode(dxf_path: str, output_path: str, layer: str = "", depth_mm: float = -5.0, feed_rate: int = 3000, safe_z: float = 5.0) -> dict:
    """
    Generate 2D G-code from DXF polylines (flat cutting). layer: filter by layer name, empty=all.
    Requires ezdxf. Output is inside sandbox.
    """
    target = Path(dxf_path)
    out = Path(output_path)
    if not inside_sandbox(target) or not inside_sandbox(out):
        return {"ok": False, "error": "Paths must be inside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "DXF file not found"}
    try:
        import ezdxf
        doc = ezdxf.readfile(str(target))
        msp = doc.modelspace()
        lines_out = ["G21", "G90", f"G0 Z{safe_z}", f"F{feed_rate}"]
        count = 0
        for e in msp:
            if layer and getattr(e.dxf, "layer", "") != layer:
                continue
            if e.dxftype() == "LINE":
                start, end = e.dxf.start, e.dxf.end
                lines_out.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f}")
                lines_out.append(f"G1 Z{depth_mm:.3f}")
                lines_out.append(f"G1 X{end[0]:.3f} Y{end[1]:.3f}")
                lines_out.append(f"G0 Z{safe_z}")
                count += 1
            elif e.dxftype() == "LWPOLYLINE":
                points = list(e.get_points())
                if len(points) < 2:
                    continue
                x0, y0 = float(points[0][0]), float(points[0][1])
                lines_out.append(f"G0 X{x0:.3f} Y{y0:.3f}")
                lines_out.append(f"G1 Z{depth_mm:.3f}")
                for pt in points[1:]:
                    x, y = float(pt[0]), float(pt[1])
                    lines_out.append(f"G1 X{x:.3f} Y{y:.3f}")
                lines_out.append(f"G0 Z{safe_z}")
                count += 1
        lines_out.append("M2")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines_out), encoding="utf-8")
        try:
            from layla.geometry.machining_ir import validate_gcode_text

            vg = validate_gcode_text("\n".join(lines_out))
        except Exception:
            vg = {"ok": True, "issues": [], "machine_readiness": "interpretive_preview"}
        return {
            "ok": True,
            "output_path": str(out),
            "moves": count,
            "lines": len(lines_out),
            "machine_readiness": vg.get("machine_readiness", "interpretive_preview"),
            "gcode_validation": vg,
            "disclaimer": "NOT_MACHINE_READY: interpretive 2D polyline G-code only; verify in CAM/simulation before running on hardware.",
        }
    except ImportError:
        return {"ok": False, "error": "ezdxf not installed: pip install ezdxf"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def rename_symbol(root: str, old_name: str, new_name: str, symbol_type: str = "auto", file_glob: str = "*.py", apply: bool = False) -> dict:
    """
    Rename symbol across Python files. symbol_type: function|class|variable|auto.
    apply=False: dry run, returns proposed changes. apply=True: writes changes.
    """
    root_path = Path(root)
    if not inside_sandbox(root_path):
        return {"ok": False, "error": "Outside sandbox"}
    if not root_path.exists():
        return {"ok": False, "error": "Path not found"}
    pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")
    changes = []
    for f in root_path.rglob(file_glob):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        new_content = pattern.sub(new_name, content)
        if new_content != content:
            n = len(pattern.findall(content))
            changes.append({"path": str(f), "replacements": n})
            if apply:
                f.write_text(new_content, encoding="utf-8")
    return {"ok": True, "old_name": old_name, "new_name": new_name, "changes": changes[:50], "total_files": len(changes), "applied": apply}

def code_format(path: str, formatter: str = "ruff") -> dict:
    """Format Python code with ruff or black. path: file or directory."""
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "Path not found"}
    try:
        if formatter == "ruff":
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "format", str(target)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        else:
            proc = subprocess.run(
                [sys.executable, "-m", "black", str(target)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
        return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "")[:2000]}
    except FileNotFoundError:
        return {"ok": False, "error": f"{formatter} not installed: pip install {formatter}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


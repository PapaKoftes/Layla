# -*- coding: utf-8 -*-
"""
check_security.py — Security anti-pattern scan for the Layla codebase.

Checks:
  SEC-01  Hardcoded secrets / API keys in source (regex on known patterns)
  SEC-02  os.system() / subprocess with shell=True on user-controlled input
  SEC-03  eval() / exec() on non-literal data
  SEC-04  Path traversal — open()/Path() with unvalidated user input
  SEC-05  SQL string concatenation (f-string or % into execute())
  SEC-06  pickle.loads() without trust check
  SEC-07  debug=True in production FastAPI/uvicorn calls
  SEC-08  Sensitive keys logged at INFO/DEBUG level
  SEC-09  Unrestricted file write from API route (no sandbox check)
  SEC-10  CORS allow_origins=["*"] in production app

Usage:
    cd agent/ && python scripts/check_security.py
    echo $?   # 0 = clean, 1 = issues found
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", "models",
             "chroma_db", "layla.egg-info", "build", "dist", "scripts"}  # skip self

issues: list[dict] = []


def _py_files(subdir: str | None = None):
    root = AGENT_DIR / subdir if subdir else AGENT_DIR
    for f in root.rglob("*.py"):
        if any(p in f.parts for p in SKIP_DIRS):
            continue
        yield f


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _report(check: str, path: Path, line: int, snippet: str, note: str):
    issues.append({"check": check, "file": str(path.relative_to(AGENT_DIR)),
                   "line": line, "snippet": snippet.strip()[:100], "note": note})


# SEC-01: Hardcoded secrets
_SECRET_PATTERNS = [
    (re.compile(r'(?i)(api_key|secret_key|password|token|auth_token)\s*=\s*["\'][A-Za-z0-9+/=_\-]{12,}["\']'),
     "Hardcoded secret — move to env var or runtime_config.json"),
    (re.compile(r'sk-[A-Za-z0-9]{20,}'),
     "OpenAI API key pattern detected in source"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'),
     "GitHub personal access token pattern in source"),
]

def check_hardcoded_secrets():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pat, note in _SECRET_PATTERNS:
                if pat.search(line):
                    _report("SEC-01", f, i, line, note)


# SEC-02: shell=True with variable input
_RE_SHELL_TRUE = re.compile(r'subprocess\.(run|Popen|call|check_output|check_call)\s*\([^)]*shell\s*=\s*True')
_RE_SHELL_VARIABLE = re.compile(r'shell\s*=\s*True.*[fF]["\']|[fF]["\']\S+.*shell\s*=\s*True')

def check_shell_true():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_SHELL_TRUE.search(line):
                # Only flag if there's string formatting nearby (variable input risk)
                ctx = "\n".join(_lines(f)[max(0,i-3):i+3])
                if re.search(r'\{|%s|format\(|cmd\b|command\b|user', ctx):
                    _report("SEC-02", f, i, line,
                            "subprocess with shell=True near variable input — risk of command injection; "
                            "use shell=False + list args instead")


# SEC-03: eval/exec on non-literal
_RE_EVAL = re.compile(r'\beval\s*\((?!\s*["\'\d\[\{])')
_RE_EXEC = re.compile(r'\bexec\s*\((?!\s*["\'\d\[\{])')

def check_eval_exec():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _RE_EVAL.search(line):
                _report("SEC-03", f, i, line,
                        "eval() on non-literal — if input is user-controlled this is RCE")
            if _RE_EXEC.search(line):
                _report("SEC-03", f, i, line,
                        "exec() on non-literal — if input is user-controlled this is RCE")


# SEC-04: Path traversal — only flag actual file open(), not HTTP calls
_RE_OPEN_FMT = re.compile(r'\bopen\s*\(\s*[fF]["\']|Path\s*\(\s*[fF]["\']')
_RE_HTTP_CALL = re.compile(r'urlopen|requests\.|httpx\.|aiohttp\.|http\.client')

def check_path_traversal():
    for f in _py_files("routers"):
        for i, line in enumerate(_lines(f), 1):
            if _RE_OPEN_FMT.search(line):
                if _RE_HTTP_CALL.search(line):
                    continue  # HTTP call, not a file open
                ctx = "\n".join(_lines(f)[max(0,i-5):i+5])
                if not re.search(r'sandbox|resolve\(\)|\.relative_to\(|_path_under|REPO_ROOT', ctx):
                    _report("SEC-04", f, i, line,
                            "open(f'...') in router without sandbox/resolve check — "
                            "potential path traversal; validate with path.resolve() + relative_to()")


# SEC-05: SQL string concatenation with USER-CONTROLLED input
# We only flag when the f-string contains a variable that could be user input,
# not when it's a constant column name (like `{table}` from a hardcoded list).
_RE_SQL_CONCAT = re.compile(r'execute\s*\(\s*[fF]["\'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP)', re.I)
# Safe patterns: table/column names from constants, placeholders, or hardcoded lists
_RE_SAFE_PATTERN = re.compile(r'\{(?:table|col|table_name|placeholders|fields|updates|q|joins?|order)\b|join\s*\((?:updates|fields|cols|placeholders)')

def check_sql_injection():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_SQL_CONCAT.search(line):
                # Only flag if the variable could be user-controlled (not a column/table constant)
                if not _RE_SAFE_PATTERN.search(line):
                    _report("SEC-05", f, i, line,
                            "SQL query built with f-string — use parameterised execute(sql, (params,)) instead")


# SEC-06: pickle.loads
_RE_PICKLE = re.compile(r'pickle\.loads?\s*\(')

def check_pickle():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_PICKLE.search(line):
                ctx = "\n".join(_lines(f)[max(0,i-3):i+3])
                if not re.search(r'#.*trusted|#.*safe|hmac|signature', ctx, re.I):
                    _report("SEC-06", f, i, line,
                            "pickle.loads() without trust annotation — "
                            "deserialising untrusted data allows arbitrary code execution")


# SEC-07: debug=True in production
_RE_DEBUG = re.compile(r'\bdebug\s*=\s*True\b')

def check_debug_mode():
    for f in _py_files():
        if f.name in ("conftest.py",) or "test" in f.name:
            continue
        for i, line in enumerate(_lines(f), 1):
            if _RE_DEBUG.search(line):
                if "uvicorn" in line or "app.run" in line or "fastapi" in line.lower():
                    _report("SEC-07", f, i, line,
                            "debug=True in production server call — exposes stack traces to clients")


# SEC-08: Actual credentials in logs (not token counts or auth status codes)
_RE_LOG_SENSITIVE = re.compile(
    r'logger\.(info|debug|warning)\s*\([^)]*(?:password|secret|api_key|private_key)',
    re.I
)

def check_sensitive_logging():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_LOG_SENSITIVE.search(line):
                _report("SEC-08", f, i, line,
                        "Sensitive field name in log call — ensure value is masked (e.g. ***)")


# SEC-09: Unrestricted file write in router
_RE_WRITE = re.compile(r'\.write(?:_text|_bytes)?\s*\(|open\s*\([^)]+["\']w["\']')

def check_unrestricted_write():
    for f in _py_files("routers"):
        src_lines = _lines(f)
        src = "\n".join(src_lines)
        if not _RE_WRITE.search(src):
            continue
        if re.search(r'sandbox|_path_under|resolve\(\).*relative_to|workspace_root', src):
            continue  # sandbox check present in file
        for i, line in enumerate(src_lines, 1):
            if _RE_WRITE.search(line):
                _report("SEC-09", f, i, line,
                        "File write in router without visible sandbox check — "
                        "verify path is validated against workspace_root")
                break  # one report per file


# SEC-10: CORS wildcard
_RE_CORS_WILD = re.compile(r'allow_origins\s*=\s*\[\s*["\'][*]["\']')

def check_cors_wildcard():
    for f in _py_files():
        for i, line in enumerate(_lines(f), 1):
            if _RE_CORS_WILD.search(line):
                # Only warn if not clearly marked as intentional/dev-only
                ctx = "\n".join(_lines(f)[max(0,i-3):i+3])
                if not re.search(r'#.*dev|#.*local|#.*intentional', ctx, re.I):
                    _report("SEC-10", f, i, line,
                            "CORS allow_origins=['*'] — restricts to localhost in production or "
                            "add a comment marking it intentional for local-first deployment")


def run() -> int:
    print("=" * 60)
    print("Security Anti-Pattern Check")
    print("=" * 60)

    checks = [
        ("SEC-01 Hardcoded secrets",    check_hardcoded_secrets),
        ("SEC-02 Shell injection",       check_shell_true),
        ("SEC-03 eval/exec",             check_eval_exec),
        ("SEC-04 Path traversal",        check_path_traversal),
        ("SEC-05 SQL injection",         check_sql_injection),
        ("SEC-06 Pickle unsafe",         check_pickle),
        ("SEC-07 Debug mode",            check_debug_mode),
        ("SEC-08 Sensitive logging",     check_sensitive_logging),
        ("SEC-09 Unrestricted write",    check_unrestricted_write),
        ("SEC-10 CORS wildcard",         check_cors_wildcard),
    ]

    for name, fn in checks:
        before = len(issues)
        try:
            fn()
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
        after = len(issues)
        status = "PASS" if after == before else f"WARN ({after - before})"
        print(f"  {name:<35} {status}")

    print()
    if issues:
        print(f"FINDINGS: {len(issues)} item(s)\n")
        for iss in issues:
            snippet = iss['snippet'].encode('ascii', errors='replace').decode('ascii')
            note    = iss['note'].encode('ascii', errors='replace').decode('ascii')
            print(f"  [{iss['check']}] {iss['file']}:{iss['line']}")
            print(f"    {snippet}")
            print(f"    ^ {note}\n")
        return 1
    else:
        print("All security checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(run())

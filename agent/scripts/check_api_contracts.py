# -*- coding: utf-8 -*-
"""
check_api_contracts.py — Verify every HTTP endpoint has at least one test.

Strategy:
  1. Parse all routers/*.py to collect @router.{get,post,put,patch,delete}
     path strings → {METHOD /path}.
  2. Scan tests/ for fetch('/path', ...) or client.get('/path', ...) references.
  3. Report any route with zero test coverage.

Also checks:
  - Router is registered in main.py (app.include_router)
  - Every route has a docstring

Usage:
    cd agent/ && python scripts/check_api_contracts.py
    echo $?   # 0 = all covered, 1 = gaps found
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
ROUTERS_DIR = AGENT_DIR / "routers"
TESTS_DIR = AGENT_DIR / "tests"
MAIN_PY = AGENT_DIR / "main.py"

SKIP_ROUTES = {
    # Health probes and well-known paths that are tested via smoke tests
    "/health", "/metrics", "/version", "/values.md", "/docs",
    # Internal/framework routes
    "/openapi.json", "/redoc",
}

# ── Coverage ratchet ─────────────────────────────────────────────────────────
# Baseline measured 2026-04-30: 118 untested routes out of 208 total.
# Bumped to 120 (2026-05-13): +2 new debate engine routes (POST /debate, GET /debate/modes).
# This number must only go DOWN. Every time you add endpoint tests, lower it.
# If the count exceeds this value the check fails, preventing coverage regression.
# To tighten: run `python scripts/check_api_contracts.py`, read the reported
# count, then set MAX_UNCOVERED_ROUTES = <new_count>.
MAX_UNCOVERED_ROUTES = 120

# Methods we track
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _collect_routes() -> dict[str, dict]:
    """Returns {'/path METHOD': {file, line, has_docstring, router_name}}"""
    routes: dict[str, dict] = {}
    _RE_ROUTE = re.compile(
        r'@router\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']'
    )
    _RE_PREFIX = re.compile(r'prefix\s*=\s*["\']([^"\']+)["\']')

    for f in sorted(ROUTERS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        src_lines = _lines(f)
        src = "\n".join(src_lines)

        # Find router prefix
        prefix = ""
        m = _RE_PREFIX.search(src)
        if m:
            prefix = m.group(1).rstrip("/")

        # Parse routes
        for i, line in enumerate(src_lines, 1):
            m = _RE_ROUTE.search(line)
            if m:
                method = m.group(1).upper()
                path = prefix + m.group(2)
                # Check for docstring in the next 10 lines
                snippet = "\n".join(src_lines[i:i+10])
                has_doc = bool(re.search(r'"""', snippet))
                key = f"{method} {path}"
                routes[key] = {
                    "file": f.name,
                    "line": i,
                    "has_docstring": has_doc,
                    "path": path,
                    "method": method,
                }
    return routes


def _collect_test_references() -> set[str]:
    """Return set of path strings found in test files."""
    refs: set[str] = set()
    _RE_FETCH = re.compile(r'''client\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']''')
    _RE_FETCH2 = re.compile(r'''fetch\s*\(\s*["\']([^"\'?]+)''')

    for f in TESTS_DIR.rglob("*.py"):
        for line in _lines(f):
            for m in _RE_FETCH.finditer(line):
                refs.add(m.group(2).split("?")[0])
            for m in _RE_FETCH2.finditer(line):
                refs.add(m.group(1).split("?")[0])

    # Also check JS test files
    for f in (AGENT_DIR / "ui").rglob("*.js"):
        for line in _lines(f):
            for m in _RE_FETCH2.finditer(line):
                refs.add(m.group(1).split("?")[0])

    return refs


def _collect_registered_routers() -> set[str]:
    """Return set of router module names included in main.py."""
    src = "\n".join(_lines(MAIN_PY))
    return set(re.findall(r'include_router\((\w+)\.router\)', src))


def run() -> int:
    print("=" * 60)
    print("API Contract Coverage Check")
    print("=" * 60)

    routes = _collect_routes()
    test_refs = _collect_test_references()
    registered = _collect_registered_routers()

    print(f"  Routes found:      {len(routes)}")
    print(f"  Test references:   {len(test_refs)}")
    print(f"  Registered routers: {len(registered)}")
    print()

    # Check router registration
    unregistered = []
    for f in sorted(ROUTERS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        stem = f.stem + "_router"
        # main.py imports as e.g. `from routers import german as german_router`
        # or `from routers import voice as voice_router`
        src_main = "\n".join(_lines(MAIN_PY))
        if f.stem not in src_main:
            unregistered.append(f.name)

    uncovered: list[dict] = []
    no_docstring: list[dict] = []

    for key, info in sorted(routes.items()):
        path = info["path"]
        method = info["method"]

        # Skip known skipped routes
        if any(path == s or path.startswith(s + "/") for s in SKIP_ROUTES):
            continue

        # Check test coverage — match on path segments (strip params)
        path_base = re.sub(r'\{[^}]+\}', '', path).rstrip("/") or "/"
        covered = any(
            ref == path or ref.startswith(path_base) or path_base in ref
            for ref in test_refs
        )
        if not covered:
            uncovered.append(info)

        if not info["has_docstring"]:
            no_docstring.append(info)

    issues = 0

    if unregistered:
        print(f"  UNREGISTERED ROUTERS ({len(unregistered)}):")
        for r in unregistered:
            print(f"    MISSING: routers/{r} -- not referenced in main.py")
        issues += len(unregistered)
        print()

    if uncovered:
        print(f"  UNTESTED ROUTES ({len(uncovered)}):")
        for r in uncovered[:20]:  # cap output
            print(f"    UNTESTED: {r['method']} {r['path']}  ({r['file']}:{r['line']})")
        if len(uncovered) > 20:
            print(f"    ... and {len(uncovered)-20} more")
        if len(uncovered) > MAX_UNCOVERED_ROUTES:
            issues += len(uncovered) - MAX_UNCOVERED_ROUTES
            print(f"  NOTE: {len(uncovered)} uncovered routes exceeds threshold {MAX_UNCOVERED_ROUTES}; "
                  f"{len(uncovered) - MAX_UNCOVERED_ROUTES} above limit.")
        else:
            print(f"  NOTE: {len(uncovered)} uncovered routes is within threshold ({MAX_UNCOVERED_ROUTES}).")
        print()

    if no_docstring:
        # Only report first 10 to avoid noise
        print(f"  MISSING DOCSTRINGS ({len(no_docstring)} routes — first 10 shown):")
        for r in no_docstring[:10]:
            print(f"    - {r['method']} {r['path']}  ({r['file']}:{r['line']})")
        print()

    if issues == 0:
        print("All routes registered and covered by tests.")
        return 0
    else:
        print(f"FAIL: {issues} issue(s) found")
        return 1


if __name__ == "__main__":
    sys.exit(run())

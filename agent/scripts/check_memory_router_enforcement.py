"""Lint: enforce memory_router as the canonical write path.

Fail (exit 1) if any file outside the allowlist imports the underlying SQLite
write primitives directly (save_learning, save_aspect_memory) instead of going
through services.memory_router.

Allowlist:
  - The storage layer itself (layla/memory/db.py, layla/memory/learnings.py,
    layla/memory/user_profile.py, layla/memory/distill.py — distill is gray
    but already uses the router).
  - The router itself (services/memory_router.py).
  - Tests under tests/ (they exercise the primitives directly on purpose).
  - Conftest, scripts/, install/, docs/, archives.

Wired into scripts/run_all_checks.py as WARN severity initially so partial
migration doesn't break CI. Ratchet to FAIL once the offender count hits 0.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent

# Files allowed to import the raw primitives directly.
ALLOWLIST_SUFFIXES = (
    "services/memory_router.py",
    "layla/memory/db.py",
    "layla/memory/learnings.py",
    "layla/memory/user_profile.py",
    "layla/memory/distill.py",  # uses router but defines its own helpers
)

# Patterns that indicate a direct write-primitive import.
FORBIDDEN_PATTERNS = [
    re.compile(r"from\s+layla\.memory\.db\s+import\s+[^\n]*\bsave_learning\b"),
    re.compile(r"from\s+layla\.memory\.db\s+import\s+[^\n]*\bsave_aspect_memory\b"),
    re.compile(r"from\s+layla\.memory\.learnings\s+import\s+[^\n]*\bsave_learning\b"),
]


def _is_allowed(path: Path) -> bool:
    p = path.as_posix()
    # Allow anything under tests/, scripts/, install/, docs/, archive/, .bak files
    if any(seg in p for seg in ("/tests/", "/scripts/", "/install/", "/docs/", "/archive/")):
        return True
    if p.endswith(".bak"):
        return True
    return any(p.endswith(suf) for suf in ALLOWLIST_SUFFIXES)


def scan() -> list[tuple[Path, int, str]]:
    offenders: list[tuple[Path, int, str]] = []
    for py in AGENT_DIR.rglob("*.py"):
        try:
            rel = py.relative_to(AGENT_DIR)
        except ValueError:
            continue
        if _is_allowed(rel):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat in FORBIDDEN_PATTERNS:
                if pat.search(line):
                    offenders.append((rel, i, line.strip()))
                    break
    return offenders


def main() -> int:
    offenders = scan()
    if not offenders:
        print("memory_router_enforcement: OK (0 offenders)")
        return 0
    print(f"memory_router_enforcement: {len(offenders)} offender(s)")
    for path, line_no, snippet in offenders:
        print(f"  {path.as_posix()}:{line_no}  {snippet}")
    # Default exit 1; run_all_checks wraps this as WARN initially.
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Fail if index.html onclick/onchange reference undefined global call targets."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_AGENT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_AGENT / "ui"

# onclick="foo(" or onchange="foo("
ATTR_SIMPLE = re.compile(r'\b(?:onclick|onchange)\s*=\s*"([^"]*)"')

# Identifiers followed by '(' — exclude obvious non-calls
SKIP_CALL = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "catch",
        "function",
        "return",
        "new",
        "typeof",
        "void",
        "await",
        "super",
        "import",
        "throw",
        "case",
        "try",
        "finally",
        "true",
        "false",
        "null",
        "undefined",
        "event",
        "window",
        "document",
        "location",
        "console",
        "Math",
        "Date",
        "JSON",
        "parseInt",
        "parseFloat",
        "String",
        "Number",
        "Array",
        "Object",
        "Error",
        "Promise",
        "fetch",
        "alert",
        "confirm",
        "prompt",
        "encodeURIComponent",
        "decodeURIComponent",
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
    }
)

# How a symbol can be defined in bundled UI scripts
DEF_PATTERNS = [
    re.compile(r"(?:^|\n)\s*function\s+([a-zA-Z_$][\w$]*)\s*\("),
    re.compile(r"(?:^|\n)\s*async\s+function\s+([a-zA-Z_$][\w$]*)\s*\("),
    re.compile(r"(?:^|\n)\s*window\.([a-zA-Z_$][\w$]*)\s*="),
    re.compile(r"(?:^|\n)\s*var\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"),
    re.compile(r"(?:^|\n)\s*const\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
    re.compile(r"(?:^|\n)\s*let\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
]


def _collect_defs(js_text: str) -> set[str]:
    names: set[str] = set()
    for pat in DEF_PATTERNS:
        names.update(pat.findall(js_text))
    # IIFE wrappers sometimes assign window.foo inside nested blocks — rough scan
    for m in re.finditer(r"\bwindow\.([a-zA-Z_$][\w$]*)\s*=", js_text):
        names.add(m.group(1))
    return names


def _calls_in_handler(attr_val: str) -> set[str]:
    """Extract likely global function names invoked from inline handler source."""
    # Strip one common guard pattern
    s = attr_val
    s = re.sub(r"typeof\s+([a-zA-Z_$][\w$]*)\s*===\s*['\"]function['\"]\s*&&\s*", "", s)
    calls: set[str] = set()
    for m in re.finditer(r"\b([a-zA-Z_$][\w$]*)\s*\(", s):
        if m.start() > 0 and s[m.start() - 1] == ".":
            continue  # obj.method( — not a global
        name = m.group(1)
        if name not in SKIP_CALL:
            calls.add(name)
    return calls


def main() -> int:
    if not UI_DIR.is_dir():
        print("check_ui_symbols: missing", UI_DIR, file=sys.stderr)
        return 2

    js_files = sorted((UI_DIR / "js").rglob("*.js")) if (UI_DIR / "js").is_dir() else []
    combined_js = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in js_files)
    defs = _collect_defs(combined_js)

    html_files = sorted(UI_DIR.rglob("*.html"))
    missing: list[tuple[str, str]] = []

    for html_path in html_files:
        text = html_path.read_text(encoding="utf-8", errors="replace")
        for m in ATTR_SIMPLE.finditer(text):
            val = m.group(1)
            if "function()" in val or "(function" in val:
                continue
            for sym in _calls_in_handler(val):
                if sym in defs:
                    continue
                # Allow inline DOM0 style that uses only event/this
                if sym in ("stopPropagation", "preventDefault"):
                    continue
                rel = html_path.relative_to(UI_DIR.parent)
                missing.append((str(rel), sym))

    if not missing:
        print("check_ui_symbols: OK", len(html_files), "html file(s),", len(defs), "def(s)")
        return 0

    print("check_ui_symbols: undefined handler symbol(s):", file=sys.stderr)
    for path, sym in sorted(missing):
        print(f"  {path}: {sym}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

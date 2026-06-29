#!/usr/bin/env python3
"""Fail if a strong-copyleft (AGPL/GPL/SSPL) dependency is installed (REQ-02).

The project ships under a proprietary "Free for non-commercial use" license,
incompatible with strong copyleft. This guard scans installed distribution
metadata (stdlib `importlib.metadata` — no third-party deps) and exits non-zero
if any package is strong-copyleft *without* a usable escape hatch, so CI blocks
a newly-introduced one (e.g. the PyMuPDF/AGPL issue that was removed).

To avoid the classic false positives it reasons over STRUCTURED metadata
(SPDX `License-Expression` + trove `License ::` classifiers) rather than the
free-text `License` field, which for many BSD/Apache packages embeds the full
text of bundled third-party notices (scipy, numpy, ...) and would match "general
public license" spuriously. A package is cleared when it is:

  * dual-licensed with a permissive option (Apache/BSD/MIT/... OR GPL), or
  * GPL **with a linking/"special exception"** (PyInstaller, GCC runtime), or
  * LGPL/MPL only (weak/file-level copyleft), or
  * listed in ALLOW with a justification.

Usage:  python scripts/check_copyleft.py [--list]
"""
from __future__ import annotations

import sys
from importlib import metadata

# Strong-copyleft markers (lowercased substring match).
COPYLEFT = (
    "agpl", "affero",
    "gplv2", "gplv3", "gpl-2", "gpl-3", "gpl v2", "gpl v3", "gpl version 2", "gpl version 3",
    "gnu general public", "general public license, version",
    "sspl", "server side public",
)
# Permissive markers — presence of one of these alongside a copyleft marker means
# the package is dual-licensed and the permissive option may be chosen.
PERMISSIVE = (
    "apache", "bsd", "mit license", "mit-", "://opensource.org/licenses/mit",
    "isc license", "python software foundation", "psf", "zlib", "unlicense",
    "public domain", "mpl", "mozilla public", "boost software",
)
# Packages explicitly cleared (name lowercased). Add with a justification comment.
ALLOW: set[str] = set()


def _fields(md):
    """Return (structured_text, freetext_short, fulltext) all lowercased.

    structured = License-Expression + every 'License ::' classifier (authoritative).
    freetext_short = the free-text License field only when it's a *name* (< 200 chars),
                     not an embedded full license body.
    fulltext = everything, used only for linking-exception detection.
    """
    structured: list[str] = []
    expr = md.get("License-Expression")
    if expr:
        structured.append(str(expr))
    for cls in md.get_all("Classifier") or []:
        if "License ::" in cls:
            structured.append(cls)
    free = (md.get("License") or "").strip()
    freetext_short = free if len(free) < 200 else ""
    s = " || ".join(structured).lower()
    return s, freetext_short.lower(), (s + " || " + free.lower())


def _has(text: str, markers) -> bool:
    return any(m in text for m in markers)


def _neutralize_lgpl(text: str) -> str:
    """Mask LGPL / weak-copyleft so it can't match the strong-GPL substrings.

    Necessary because "lgplv2" contains "gplv2" and "lgpl v2" contains "gpl v2";
    a naive substring scan would flag LGPL (weak, allowed) as strong copyleft.
    """
    return text.replace("lesser general public", "weakcopyleft").replace("lgpl", "weakcopyleft")


def classify(md) -> tuple[bool, str]:
    """Return (is_blocking_copyleft, reason)."""
    structured, free_short, full = _fields(md)
    sources = _neutralize_lgpl(structured + " || " + free_short)

    if not _has(sources, COPYLEFT):
        return False, ""

    # Linking / "special" exception (PyInstaller, GCC runtime, Classpath) — allow.
    full_n = _neutralize_lgpl(full)
    if "exception" in full_n and ("special exception" in full_n or "linking exception" in full_n
                                  or "with exception" in full_n or "runtime library exception" in full_n
                                  or "classpath" in full_n):
        return False, "GPL-with-linking-exception"

    # Dual-licensed with a permissive option — the permissive choice is compatible.
    # (Deliberately excludes "OR commercial", which is not free — so PyMuPDF stays flagged.)
    if _has(sources, PERMISSIVE):
        return False, "dual-licensed (permissive option available)"

    return True, (structured or free_short or "copyleft")


def scan():
    hits = []
    for dist in metadata.distributions():
        md = dist.metadata
        name = (md.get("Name") or "").strip()
        if not name or name.lower() in ALLOW:
            continue
        blocking, reason = classify(md)
        if blocking:
            hits.append((name, str(md.get("Version") or "?"), reason[:140]))
    # de-dup (multiple dist-info dirs) and sort
    return sorted(set(hits))


def main(argv) -> int:
    hits = scan()
    if "--list" in argv:
        for name, ver, reason in hits:
            print(f"{name} {ver}  [{reason}]")
        return 0
    if hits:
        print("ERROR: strong-copyleft (AGPL/GPL/SSPL) dependencies found — "
              "incompatible with the project license:", file=sys.stderr)
        for name, ver, reason in hits:
            print(f"  - {name} {ver}: {reason}", file=sys.stderr)
        print("\nRemove it, find a permissively-licensed alternative, or relicense the project.\n"
              "False positive? Add the package to ALLOW in this script with a justification.",
              file=sys.stderr)
        return 1
    print("OK: no blocking strong-copyleft (AGPL/GPL/SSPL) dependencies installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

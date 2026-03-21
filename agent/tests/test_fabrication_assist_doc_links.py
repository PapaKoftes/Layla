"""Verify relative markdown links from fabrication assist docs exist."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Markdown links: [text](path) — collect .md targets
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md[^)]*)\)")


def _targets_from_file(md_path: Path) -> list[Path]:
    text = md_path.read_text(encoding="utf-8")
    out: list[Path] = []
    for m in _LINK_RE.finditer(text):
        target = m.group(1).split("#", 1)[0].strip()
        if not target or target.startswith("http"):
            continue
        resolved = (md_path.parent / target).resolve()
        out.append(resolved)
    return out


def test_fabrication_assist_doc_links_resolve() -> None:
    roots = [
        _REPO_ROOT / "docs" / "FABRICATION_ASSIST.md",
        _REPO_ROOT / "knowledge" / "fabrication-assist-layer.md",
    ]
    seen: set[Path] = set()
    for doc in roots:
        assert doc.is_file(), f"missing doc {doc}"
        for t in _targets_from_file(doc):
            if t in seen:
                continue
            seen.add(t)
            assert t.is_file(), f"broken link in {doc.name} -> {t}"

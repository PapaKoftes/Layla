from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from layla.tools.sandbox_core import inside_sandbox


class WikiError(Exception):
    pass


_SAFE_SLUG = re.compile(r"[^a-z0-9._-]+")


def _slugify(title: str) -> str:
    t = (title or "").strip().lower()
    t = _SAFE_SLUG.sub("-", t).strip("-")
    return t[:80] or "untitled"


@dataclass(frozen=True)
class WikiCandidate:
    title: str
    slug: str
    content_md: str

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "slug": self.slug, "content_md": self.content_md}


def build_candidate(*, title: str, content_md: str) -> WikiCandidate:
    return WikiCandidate(title=title.strip() or "Untitled", slug=_slugify(title), content_md=(content_md or "").strip())


def wiki_root_for_workspace(workspace_root: str) -> Path:
    return (Path(workspace_root).expanduser().resolve() / ".layla" / "wiki").resolve()


def merge_wiki_markdown(existing: str, incoming: str) -> str:
    """
    Minimal merge policy:
    - If incoming already exists (substring) -> keep existing.
    - Else append with a divider.
    """
    a = (existing or "").rstrip()
    b = (incoming or "").strip()
    if not b:
        return a + ("\n" if a else "")
    if b in a:
        return a + ("\n" if a else "")
    if not a:
        return b + "\n"
    return a + "\n\n---\n\n" + b + "\n"


def write_wiki_entry(
    *,
    workspace_root: str,
    candidate: WikiCandidate,
    allow_write: bool,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    if not cfg.get("autonomous_wiki_enabled", True):
        return {"ok": True, "skipped": True, "reason": "wiki_disabled", "candidate": candidate.as_dict()}
    if not allow_write:
        return {"ok": True, "skipped": True, "reason": "allow_write_false", "candidate": candidate.as_dict()}

    root = wiki_root_for_workspace(workspace_root)
    if not inside_sandbox(root):
        raise WikiError("wiki_root_outside_sandbox")
    root.mkdir(parents=True, exist_ok=True)

    path = (root / f"{candidate.slug}.md").resolve()
    if not inside_sandbox(path):
        raise WikiError("wiki_path_outside_sandbox")

    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

    merged = merge_wiki_markdown(existing, candidate.content_md)
    path.write_text(merged, encoding="utf-8")
    return {"ok": True, "path": str(path), "candidate": candidate.as_dict()}


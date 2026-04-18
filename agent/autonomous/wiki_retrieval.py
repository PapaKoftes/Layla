"""Read-only scan of .layla/wiki/*.md before running the planner (no index file)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from autonomous.wiki import wiki_root_for_workspace
from layla.tools.sandbox_core import inside_sandbox

_TOKEN_SPLIT = re.compile(r"[^\w]+")
_PATH_LIKE = re.compile(r"[\w/.-]+\.(?:py|md|json|ts|tsx|js|yml|yaml|toml|rs|go)\b", re.I)
_FRONTMATTER = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n", re.MULTILINE)


def _tokens(text: str) -> frozenset[str]:
    raw = _TOKEN_SPLIT.split(str(text or "").lower())
    return frozenset(t for t in raw if len(t) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (tags dict from yaml-like lines, body)."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta_raw = m.group(1)
    body = text[m.end() :]
    tags: dict[str, str] = {}
    for ln in meta_raw.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            tags[k.strip().lower()] = v.strip()
    return tags, body


def _first_heading(body: str) -> str:
    for ln in body.splitlines():
        if ln.startswith("#"):
            return ln.lstrip("#").strip()[:500]
    return ""


def try_wiki_retrieval(*, goal: str, workspace_root: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    thresh = float(cfg.get("autonomous_wiki_match_threshold") or 0.18)
    max_files = int(cfg.get("autonomous_prefetch_wiki_max_files") or 80)
    max_chars = int(cfg.get("autonomous_prefetch_wiki_max_chars_per_file") or 48_000)

    root = wiki_root_for_workspace(workspace_root)
    try:
        if not root.is_dir():
            return None
        if not inside_sandbox(root):
            return None
    except OSError:
        return None

    goal_t = _tokens(goal)
    if not goal_t:
        return None

    paths = sorted(root.glob("*.md"))[:max_files]
    best: tuple[float, Path, dict[str, Any]] | None = None

    for p in paths:
        try:
            rp = p.resolve()
            if not inside_sandbox(rp):
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(raw) > max_chars:
            raw = raw[:max_chars]
        meta, body = _parse_frontmatter(raw)
        title = meta.get("title") or _first_heading(body) or p.stem.replace("-", " ")
        slug = p.stem
        tags_blob = " ".join(meta.get(k, "") for k in ("tags", "tag") if meta.get(k))
        path_hits = " ".join(_PATH_LIKE.findall(body))[:8000]
        corpus = f"{title}\n{slug}\n{tags_blob}\n{body[:12000]}\n{path_hits}"
        corpus_t = _tokens(corpus)
        score = _jaccard(goal_t, corpus_t)
        if meta.get("tags"):
            score = min(1.0, max(score, _jaccard(goal_t, _tokens(tags_blob)) * 1.05))
        if best is None or score > best[0]:
            best = (
                score,
                p,
                {"title": title, "slug": slug, "body": body.strip(), "meta": meta},
            )

    if best is None or best[0] < thresh:
        return None

    score, path, bundle = best
    body = bundle["body"]
    findings_lines: list[dict[str, Any]] = []
    for ln in body.splitlines():
        ln = ln.strip()
        if ln.startswith(("- ", "* ", "1.", "2.", "3.")):
            insight = ln.lstrip("-*0123456789. ")[:400]
            if insight:
                findings_lines.append({"insight": insight, "evidence": []})
        if len(findings_lines) >= 25:
            break
    if not findings_lines:
        excerpt = body.replace("\n", " ").strip()[:900]
        if excerpt:
            findings_lines.append({"insight": excerpt, "evidence": []})

    summary = body.replace("\n", " ").strip()[:4000]
    return {
        "summary": summary or bundle["title"],
        "findings": findings_lines[:40],
        "confidence": "medium",
        "reasoning": "",
        "wiki_path": str(path),
        "wiki_title": bundle["title"],
        "wiki_slug": bundle["slug"],
        "match_score": round(score, 4),
    }

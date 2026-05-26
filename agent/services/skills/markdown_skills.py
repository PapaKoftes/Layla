"""
Load AgentSkills-style SKILL.md files (YAML frontmatter + body) into prompt text.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL | re.MULTILINE)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    body = text[m.end() :]
    raw = m.group(1)
    meta: dict[str, Any] = {}
    try:
        import yaml

        meta = yaml.safe_load(raw) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        for line in raw.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _requires_ok(meta: dict[str, Any]) -> bool:
    req = meta.get("requires")
    if req is None:
        raw_metadata = meta.get("metadata")
        if isinstance(raw_metadata, dict):
            openclaw = raw_metadata.get("openclaw")
            if isinstance(openclaw, dict):
                req = openclaw.get("requires")
    # Normalize str/list requires to dict form for uniform handling below
    if isinstance(req, str):
        req = {"bins": [req]}
    elif isinstance(req, list):
        req = {"bins": req}
    if isinstance(req, dict):
        bins = req.get("bins") or []
        envs = req.get("env") or []
        if isinstance(bins, str):
            bins = [bins]
        if isinstance(envs, str):
            envs = [envs]
        for b in bins:
            if b and not shutil.which(str(b)):
                return False
        for e in envs:
            if e and not os.environ.get(str(e)):
                return False
    return True


def discover_skill_md_paths(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(base.rglob("SKILL.md"))


def load_markdown_skills_prompt(cfg: dict[str, Any]) -> str:
    """Return text block for planner / system context."""
    raw_dir = cfg.get("markdown_skills_dir")
    if raw_dir:
        base = Path(str(raw_dir)).expanduser().resolve()
    else:
        base = REPO_ROOT / "skills"
    paths = discover_skill_md_paths(base)
    if not paths:
        return ""

    blocks: list[str] = []
    for p in paths[:40]:
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            logger.debug("skip skill md %s: %s", p, e)
            continue
        meta, body = _parse_frontmatter(text)
        if not _requires_ok(meta):
            continue
        name = meta.get("name") or p.parent.name
        desc = (meta.get("description") or "")[:200]
        snippet = (body or "").strip()[:1200]
        blocks.append(f"### Skill: {name}\n{desc}\n{snippet}\n")
    if not blocks:
        return ""
    return "[Markdown skills]\n" + "\n".join(blocks)

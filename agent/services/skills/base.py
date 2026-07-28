"""
Load markdown skills from .layla/skills/, skills/, .claude/skills/ under workspace root.
Each file: optional YAML front matter (name, triggers, description) + body.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


@dataclass
class Skill:
    name: str
    triggers: list[str]
    description: str
    body: str
    path: str


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    text = text or ""
    if not text.lstrip().startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    raw_fm = m.group(1)
    body = text[m.end() :]
    meta: dict[str, Any] = {}
    for line in raw_fm.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        meta[k] = v
    return meta, body


_SKILLS_CACHE: dict[str, tuple[float, tuple, list["Skill"]]] = {}
_SKILLS_TTL = 30.0


def load_skills(workspace_root: str) -> list[Skill]:
    root = Path(workspace_root).expanduser().resolve()
    dirs = [
        root / ".layla" / "skills",
        root / "skills",          # repo-root skills/ (SKILL.md compatible)
        root / ".claude" / "skills",
        root / ".cursor" / "skills",  # Cursor AgentSkills location
    ]
    # This globs 4 dirs and reads+parses EVERY skill .md, yet it is called per substantive turn
    # (pick_skills_for_goal) just to keep the 2 best. Cache by (root, per-dir mtimes) with a short
    # TTL so an unchanged skills tree isn't re-read every turn (add/remove bumps the dir mtime;
    # in-place content edits are picked up within the TTL).
    import time as _time
    _sig = tuple((str(d), (d.stat().st_mtime if d.is_dir() else 0.0)) for d in dirs)
    _now = _time.monotonic()
    _hit = _SKILLS_CACHE.get(str(root))
    if _hit and (_now - _hit[0]) < _SKILLS_TTL and _hit[1] == _sig:
        return _hit[2]
    out: list[Skill] = []
    seen: set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            meta, body = _parse_frontmatter(text)
            name = str(meta.get("name") or f.stem)
            desc = str(meta.get("description") or "")
            triggers = []
            tr = meta.get("triggers")
            if isinstance(tr, str):
                triggers = [t.strip() for t in re.split(r"[,|]", tr) if t.strip()]
            elif isinstance(tr, list):
                triggers = [str(x).strip() for x in tr if str(x).strip()]
            out.append(Skill(name=name, triggers=triggers, description=desc, body=body.strip(), path=str(f)))
    _SKILLS_CACHE[str(root)] = (_now, _sig, out)
    return out


def pick_skills_for_goal(goal: str, workspace_root: str, max_skills: int = 2) -> list[Skill]:
    g = (goal or "").lower()
    if not g.strip():
        return []
    scored: list[tuple[int, Skill]] = []
    for sk in load_skills(workspace_root):
        score = 0
        for t in sk.triggers:
            if t.lower() in g:
                score += 3
        if sk.description and any(w in g for w in sk.description.lower().split() if len(w) > 4):
            score += 1
        if score > 0:
            scored.append((score, sk))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_skills]]


def skills_prompt_block(goal: str, workspace_root: str, max_tokens: int = 800) -> str:
    picks = pick_skills_for_goal(goal, workspace_root)
    if not picks:
        return ""
    parts = []
    for sk in picks:
        block = f"### Skill: {sk.name}\n{sk.body[: max_tokens // max(1, len(picks))]}"
        parts.append(block)
    return "\n\n".join(parts)

"""Read-only match against investigation_reuse.jsonl before running the planner."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from layla.tools.sandbox_core import inside_sandbox

_TOKEN_SPLIT = re.compile(r"[^\w]+")


def _tokens(text: str) -> frozenset[str]:
    raw = _TOKEN_SPLIT.split(str(text or "").lower())
    return frozenset(t for t in raw if len(t) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _combined_score(goal_t: frozenset[str], record: dict[str, Any]) -> float:
    g_goal = _jaccard(goal_t, _tokens(str(record.get("goal") or "")))
    g_sum = _jaccard(goal_t, _tokens(str(record.get("summary") or "")))
    # Weight summary slightly lower than goal overlap
    return max(g_goal, 0.65 * g_goal + 0.35 * g_sum)


def try_reuse_retrieval(*, goal: str, workspace_root: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """
    Return prefetch payload if a prior investigation line matches the goal strongly enough.
    """
    root = (workspace_root or "").strip()
    if not root:
        return None
    thresh = float(cfg.get("autonomous_reuse_match_threshold") or 0.22)
    max_bytes = int(cfg.get("autonomous_prefetch_jsonl_max_bytes") or 2_000_000)

    path = Path(root).expanduser().resolve() / ".layla" / "investigation_reuse.jsonl"
    try:
        if not path.is_file():
            return None
        rp = path.resolve()
        if not inside_sandbox(rp):
            return None
    except OSError:
        return None

    goal_t = _tokens(goal)
    if not goal_t:
        return None

    best: tuple[float, dict[str, Any]] | None = None
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        text = data.decode("utf-8", errors="replace")
    except OSError:
        return None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        score = _combined_score(goal_t, rec)
        if best is None or score > best[0]:
            best = (score, rec)

    if best is None or best[0] < thresh:
        return None

    score, rec = best
    findings = rec.get("findings")
    if not isinstance(findings, list):
        findings = []
    conf = str(rec.get("confidence") or "high").strip().lower()
    if conf not in ("low", "medium", "high"):
        conf = "high"
    return {
        "summary": str(rec.get("summary") or "")[:12000],
        "findings": findings[:50],
        "confidence": conf,
        "reasoning": "",
        "matched_run_id": str(rec.get("run_id") or ""),
        "matched_ts": rec.get("ts"),
        "match_score": round(score, 4),
    }

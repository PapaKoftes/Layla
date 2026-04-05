"""
Workspace-local durable plan mirror + compact history for cohesion (no full LLM re-gen).

- `.layla/plan_store/manifest.json` — rolling index (ids, status, goal preview, updated_at, source).
- `.layla/plan_store/plans/{id}.json` — snapshot of SQLite-backed plans (PATCH via rewrite of one file).
- `.layla/plan_store/history.jsonl` — append-only one JSON line per terminal plan (done/blocked); capped by trim.

Call `mirror_sqlite_plan` from routers after create/patch/approve/execute so all plan systems share on-disk truth.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from layla.tools.registry import inside_sandbox

logger = logging.getLogger("layla")

_MANIFEST = "manifest.json"
_HISTORY = "history.jsonl"
_PLANS_SUB = "plans"
_MAX_MANIFEST = 80
_MAX_HISTORY_LINES = 200


def _workspace_root_path(workspace_root: str) -> Path | None:
    raw = (workspace_root or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir() or not inside_sandbox(root):
        return None
    return root


def _store_dir(root: Path) -> Path:
    d = root / ".layla" / "plan_store"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plans_dir(root: Path) -> Path:
    d = _store_dir(root) / _PLANS_SUB
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_manifest(root: Path) -> list[dict[str, Any]]:
    p = _store_dir(root) / _MANIFEST
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_manifest(root: Path, entries: list[dict[str, Any]]) -> None:
    p = _store_dir(root) / _MANIFEST
    trimmed = entries[:_MAX_MANIFEST]
    p.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")


def _upsert_manifest(root: Path, entry: dict[str, Any]) -> None:
    entries = _load_manifest(root)
    pid = str(entry.get("plan_id") or "")
    out = [e for e in entries if str(e.get("plan_id") or "") != pid]
    out.insert(0, entry)
    _save_manifest(root, out)


def mirror_sqlite_plan(plan: dict[str, Any]) -> None:
    """
    Persist SQLite plan row to workspace disk (structured JSON, single-file replace).
    plan: get_layla_plan-shaped dict.
    """
    wr = str(plan.get("workspace_root") or "").strip()
    root = _workspace_root_path(wr)
    if root is None:
        return
    pid = str(plan.get("id") or "").strip()
    if not pid:
        return
    try:
        snap = {
            "id": pid,
            "source": "sqlite",
            "workspace_root": str(root),
            "goal": plan.get("goal") or "",
            "context": plan.get("context") or "",
            "status": plan.get("status") or "draft",
            "conversation_id": plan.get("conversation_id") or "",
            "steps": plan.get("steps") if isinstance(plan.get("steps"), list) else [],
            "created_at": plan.get("created_at") or "",
            "updated_at": plan.get("updated_at") or "",
        }
        outp = _plans_dir(root) / f"{pid.replace('/', '')[:128]}.json"
        outp.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
        _upsert_manifest(
            root,
            {
                "plan_id": pid,
                "source": "sqlite",
                "status": snap["status"],
                "goal_preview": (snap["goal"] or "")[:240],
                "updated_at": snap["updated_at"],
                "step_count": len(snap["steps"]),
            },
        )
    except OSError as e:
        logger.debug("mirror_sqlite_plan: %s", e)


def append_plan_history(workspace_root: str, record: dict[str, Any]) -> None:
    """Append one terminal event (done/blocked); trims file tail."""
    root = _workspace_root_path(workspace_root)
    if root is None:
        return
    line = json.dumps(record, default=str) + "\n"
    hp = _store_dir(root) / _HISTORY
    try:
        with hp.open("a", encoding="utf-8") as f:
            f.write(line)
        raw = hp.read_text(encoding="utf-8").splitlines()
        if len(raw) > _MAX_HISTORY_LINES:
            hp.write_text("\n".join(raw[-_MAX_HISTORY_LINES:]) + "\n", encoding="utf-8")
    except OSError as e:
        logger.debug("append_plan_history: %s", e)


def prior_plans_digest(workspace_root: str, *, limit: int = 8) -> str:
    """Compact text for planner prompt: recent plans from manifest + history tail."""
    root = _workspace_root_path(workspace_root)
    if root is None:
        return ""
    lim = max(1, min(int(limit), 24))
    parts: list[str] = []
    for e in _load_manifest(root)[:lim]:
        pid = e.get("plan_id") or "?"
        st = e.get("status") or ""
        g = (e.get("goal_preview") or "")[:160]
        if g:
            parts.append(f"- [{pid}] {st}: {g}")
    hp = _store_dir(root) / _HISTORY
    if hp.is_file():
        try:
            tail = hp.read_text(encoding="utf-8").splitlines()[-5:]
            for ln in tail:
                if not ln.strip():
                    continue
                try:
                    o = json.loads(ln)
                    if isinstance(o, dict):
                        parts.append(
                            f"- (past) {o.get('plan_id', '?')} {o.get('outcome', '')}: "
                            f"{str(o.get('goal_preview', ''))[:120]}"
                        )
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
    if not parts:
        return ""
    return "Recent / prior plans in this workspace (for cohesion; do not duplicate completed work):\n" + "\n".join(parts[: lim + 5])


def mirror_file_plan_json(workspace_root: str, plan_id: str, payload: dict[str, Any]) -> None:
    """Register file-backed `.layla_plans` plan in manifest (optional snapshot path)."""
    root = _workspace_root_path(workspace_root)
    if root is None or not plan_id:
        return
    try:
        _upsert_manifest(
            root,
            {
                "plan_id": str(plan_id),
                "source": "file",
                "status": str(payload.get("status") or ""),
                "goal_preview": str(payload.get("goal") or "")[:240],
                "updated_at": str(payload.get("updated_at") or ""),
                "step_count": len(payload.get("steps") or []) if isinstance(payload.get("steps"), list) else 0,
            },
        )
    except Exception as e:
        logger.debug("mirror_file_plan_json: %s", e)

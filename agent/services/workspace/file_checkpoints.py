"""Pre-write file snapshots for optional restore (Cursor-like checkpoints)."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_META = "meta.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def checkpoint_root_for_workspace(workspace_root: Path | None, agent_dir: Path) -> Path:
    """Directory where checkpoint bundles are stored."""
    if workspace_root and workspace_root.is_dir():
        return (workspace_root / ".layla" / "file_checkpoints").resolve()
    return (agent_dir / "file_checkpoints").resolve()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _bundle_size(bundle: Path) -> int:
    try:
        c = bundle / "content.bin"
        m = bundle / _META
        return (c.stat().st_size if c.is_file() else 0) + (m.stat().st_size if m.is_file() else 0)
    except OSError:
        return 0


def enforce_checkpoint_retention(root: Path, max_count: int, max_bytes: int) -> None:
    """
    Delete oldest checkpoint bundles when over max_count or max_bytes.
    0 = unlimited for that dimension; both 0 skips enforcement.
    """
    if not root.is_dir():
        return
    max_count = max(0, int(max_count or 0))
    max_bytes = max(0, int(max_bytes or 0))
    if max_count == 0 and max_bytes == 0:
        return
    entries: list[tuple[float, Path, int]] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        if not (d / _META).is_file() or not (d / "content.bin").is_file():
            continue
        try:
            mt = d.stat().st_mtime
            sz = _bundle_size(d)
            entries.append((mt, d, sz))
        except OSError:
            continue
    entries.sort(key=lambda x: x[0])
    total = sum(e[2] for e in entries)
    n = len(entries)
    while entries:
        over_n = max_count > 0 and n > max_count
        over_b = max_bytes > 0 and total > max_bytes
        if not over_n and not over_b:
            break
        _, oldest, sz = entries.pop(0)
        try:
            shutil.rmtree(oldest)
            total -= sz
            n -= 1
            logger.debug("file_checkpoint retention removed %s", oldest.name)
        except OSError as e:
            logger.warning("file_checkpoint retention failed to remove %s: %s", oldest, e)
            break


def create_checkpoint(
    *,
    path: Path,
    workspace_root: Path | None,
    agent_dir: Path,
    tool_name: str,
    approval_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    If path exists and is a file, copy to a new checkpoint bundle. If missing, no-op (new file).
    Returns { ok, checkpoint_id?, path?, skipped?, error? }.
    """
    path = path.expanduser().resolve()
    root = checkpoint_root_for_workspace(workspace_root, agent_dir)
    try:
        if not path.is_file():
            return {"ok": True, "skipped": True, "reason": "file_did_not_exist"}
        _ensure_dir(root)
        cid = str(uuid.uuid4())
        bundle = root / cid
        bundle.mkdir(parents=True, exist_ok=False)
        dest = bundle / "content.bin"
        shutil.copy2(path, dest)
        meta = {
            "checkpoint_id": cid,
            "original_path": str(path),
            "tool_name": tool_name,
            "approval_id": approval_id,
            "created_at": _utc_iso(),
        }
        (bundle / _META).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        try:
            c = cfg
            if c is None:
                import runtime_safety

                c = runtime_safety.load_config()
            if isinstance(c, dict):
                mc = c.get("file_checkpoint_max_count")
                if mc is None:
                    mc = 200
                mb = c.get("file_checkpoint_max_bytes")
                if mb is None:
                    mb = 209_715_200
                enforce_checkpoint_retention(root, int(mc), int(mb))
        except Exception as e:
            logger.debug("file_checkpoint retention skipped: %s", e)
        return {"ok": True, "checkpoint_id": cid, "path": str(path)}
    except Exception as e:
        logger.warning("file_checkpoint create failed: %s", e)
        return {"ok": False, "error": str(e)}


def list_checkpoints(
    *,
    workspace_root: Path | None,
    agent_dir: Path,
    path_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    root = checkpoint_root_for_workspace(workspace_root, agent_dir)
    if not root.is_dir():
        return {"ok": True, "checkpoints": []}
    items: list[dict[str, Any]] = []
    path_filter_norm: str | None = None
    if path_filter:
        try:
            path_filter_norm = Path(path_filter).expanduser().resolve().as_posix()
        except Exception:
            path_filter_norm = None
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        mp = d / _META
        if not mp.is_file():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        op = meta.get("original_path", "")
        if path_filter_norm and Path(op).resolve().as_posix() != path_filter_norm:
            continue
        items.append(meta)
        if len(items) >= max(1, min(limit, 200)):
            break
    return {"ok": True, "checkpoints": items}


def restore_checkpoint(
    *,
    checkpoint_id: str,
    workspace_root: Path | None,
    agent_dir: Path,
    sandbox_root: Path | None = None,
) -> dict[str, Any]:
    root = checkpoint_root_for_workspace(workspace_root, agent_dir)
    bundle = root / checkpoint_id
    meta_path = bundle / _META
    content = bundle / "content.bin"
    if not meta_path.is_file() or not content.is_file():
        return {"ok": False, "error": "checkpoint_not_found"}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        target = Path(str(meta.get("original_path", ""))).expanduser().resolve()
        if sandbox_root is not None:
            try:
                target.resolve().relative_to(sandbox_root.resolve())
            except ValueError:
                return {"ok": False, "error": "restore_target_outside_sandbox"}
        _ensure_dir(target.parent)
        shutil.copy2(content, target)
        return {"ok": True, "restored": str(target), "checkpoint_id": checkpoint_id}
    except Exception as e:
        logger.warning("file_checkpoint restore failed: %s", e)
        return {"ok": False, "error": str(e)}

"""
Linux cgroup v2 helper for background_job_worker child (best-effort).

Requires a delegated writable subtree (systemd, container, or root). If mkdir or
writes fail, logs once and returns None.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

CGROUP2_ROOT = Path("/sys/fs/cgroup")


def _linux_cgroup_v2_root_ok() -> bool:
    """True if unified cgroup v2 layout is present (cgroup.controllers at fs root)."""
    try:
        return CGROUP2_ROOT.is_dir() and (CGROUP2_ROOT / "cgroup.controllers").is_file()
    except OSError:
        return False


def _cgroup_parent_likely_delegated(parent: Path) -> bool:
    """Best-effort: parent exists and appears writable (delegation / permissions)."""
    try:
        return parent.is_dir() and os.access(parent, os.W_OK)
    except OSError:
        return False


def maybe_remove_worker_cgroup(rel_leaf: str | None) -> None:
    """
    Best-effort rmdir of a leaf cgroup after the worker process has exited.
    Skips if processes remain in the leaf or path is unsafe.
    """
    if sys.platform != "linux" or not rel_leaf or not isinstance(rel_leaf, str):
        return
    if ".." in rel_leaf or rel_leaf.startswith(("/", "\\")):
        logger.warning("cgroup cleanup: rejected unsafe rel_leaf")
        return
    try:
        leaf = (CGROUP2_ROOT / rel_leaf).resolve()
        root = CGROUP2_ROOT.resolve()
        leaf.relative_to(root)
    except (OSError, ValueError):
        logger.warning("cgroup cleanup: path outside cgroup root or resolve failed")
        return
    try:
        procs_f = leaf / "cgroup.procs"
        if procs_f.is_file():
            raw = procs_f.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                logger.debug("cgroup cleanup: leaf %s still has PIDs, skip rmdir", rel_leaf)
                return
    except OSError:
        pass
    try:
        leaf.rmdir()
        logger.debug("cgroup cleanup: removed leaf %s", rel_leaf)
    except OSError as e:
        logger.debug("cgroup cleanup: rmdir %s failed: %s", rel_leaf, e)


def _read_own_cgroup_v2_relative_path() -> str:
    if sys.platform != "linux":
        return ""
    try:
        raw = Path("/proc/self/cgroup").read_text(encoding="utf-8", errors="replace")
        for line in raw.splitlines():
            line = line.strip()
            parts = line.split(":", 2)
            if len(parts) >= 3 and parts[0] == "0":
                p = (parts[2] or "/").strip()
                return p.lstrip("/")
    except Exception:
        pass
    return ""


def maybe_attach_worker_to_cgroup(proc: subprocess.Popen[Any], cfg: dict[str, Any]) -> str | None:
    """
    Create a leaf cgroup under the parent's cgroup, move worker PID into it, set memory.max / cpu.max.
    Returns leaf path relative to /sys/fs/cgroup on success.
    """
    if sys.platform != "linux":
        return None
    if not bool(cfg.get("background_worker_cgroup_auto_enabled")):
        return None
    pid = proc.pid
    if not pid:
        return None
    mem_raw = cfg.get("background_worker_cgroup_memory_max_bytes")
    try:
        mem = int(mem_raw) if mem_raw is not None else 0
    except (TypeError, ValueError):
        mem = 0
    cpu_max = str(cfg.get("background_worker_cgroup_cpu_max") or "").strip()
    if mem <= 0 and not cpu_max:
        logger.debug("cgroup: skip (no memory_max or cpu_max configured)")
        return None
    if not _linux_cgroup_v2_root_ok():
        logger.debug("cgroup: skip (no unified v2 at %s)", CGROUP2_ROOT)
        return None
    rel = _read_own_cgroup_v2_relative_path()
    parent = CGROUP2_ROOT / rel if rel else CGROUP2_ROOT
    if not parent.is_dir():
        logger.warning("cgroup: parent path missing: %s", parent)
        return None
    if not _cgroup_parent_likely_delegated(parent):
        logger.warning(
            "cgroup: parent not writable (need delegation?). skip attach: %s",
            parent,
        )
        return None
    leaf = parent / f"layla-bg-{pid}"
    try:
        leaf.mkdir(exist_ok=False)
    except FileExistsError:
        leaf = parent / f"layla-bg-{pid}-{id(proc)}"
        try:
            leaf.mkdir(exist_ok=False)
        except OSError as e:
            logger.warning("cgroup: mkdir failed: %s", e)
            return None
    except OSError as e:
        logger.warning("cgroup: mkdir failed: %s", e)
        return None
    try:
        (leaf / "cgroup.procs").write_text(str(pid), encoding="utf-8")
    except OSError as e:
        logger.warning("cgroup: could not move pid %s: %s", pid, e)
        try:
            leaf.rmdir()
        except OSError:
            pass
        return None
    try:
        if mem > 0:
            (leaf / "memory.max").write_text(str(mem), encoding="utf-8")
        if cpu_max:
            (leaf / "cpu.max").write_text(cpu_max, encoding="utf-8")
    except OSError as e:
        logger.warning("cgroup: limit write failed (delegation?): %s", e)
    rel_leaf = str(leaf.relative_to(CGROUP2_ROOT))
    logger.info("cgroup: attached worker pid=%s to %s", pid, rel_leaf)
    return rel_leaf

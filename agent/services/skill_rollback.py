"""
Skill pack rollback — snapshot state before install, restore on failure.

Strategy:
  - Before install: record the pack name + venv existence
  - On failure: remove pack directory + venv + registry entry
  - Manual rollback: rollback_pack(name) removes everything
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def rollback_install(pack_name: str, pack_dir: Path | None = None) -> dict[str, Any]:
    """
    Rollback a failed installation. Removes:
    - Pack directory (if exists)
    - Venv (if exists)
    - Registry entry (if exists)

    Returns {"ok": bool, "actions": [str]}
    """
    actions = []

    # Remove pack directory
    if pack_dir and pack_dir.exists():
        try:
            shutil.rmtree(str(pack_dir))
            actions.append(f"Removed pack directory: {pack_dir}")
        except Exception as e:
            actions.append(f"Failed to remove pack directory: {e}")

    # Remove venv
    try:
        from services.skill_sandbox import remove_venv
        ok, msg = remove_venv(pack_name)
        if ok:
            actions.append(f"Removed venv: {msg}")
        else:
            actions.append(f"Venv cleanup: {msg}")
    except Exception as e:
        actions.append(f"Venv cleanup error: {e}")

    # Remove registry entry
    try:
        from services.skill_registry import unregister
        if unregister(pack_name):
            actions.append("Removed registry entry")
        else:
            actions.append("No registry entry to remove")
    except Exception as e:
        actions.append(f"Registry cleanup error: {e}")

    logger.info("skill_rollback: rolled back '%s' — %d actions", pack_name, len(actions))
    return {"ok": True, "pack_name": pack_name, "actions": actions}


def can_rollback(pack_name: str) -> bool:
    """Check if there's anything to rollback for a pack."""
    try:
        from services.skill_registry import get_pack
        if get_pack(pack_name):
            return True
    except Exception:
        pass
    try:
        from services.skill_sandbox import venv_exists
        if venv_exists(pack_name):
            return True
    except Exception:
        pass
    return False

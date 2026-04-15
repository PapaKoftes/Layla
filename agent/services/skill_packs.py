"""Installable skill packs: manifest + optional knowledge paths (see ``skill_packs/`` in repo root)."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALLED_DIR = REPO_ROOT / ".layla" / "skill_packs_installed"


def _manifest_path(pack_dir: Path) -> Path:
    return pack_dir / "manifest.json"


def list_installed() -> list[dict[str, Any]]:
    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(INSTALLED_DIR.iterdir()):
        if not d.is_dir():
            continue
        mp = _manifest_path(d)
        if mp.exists():
            try:
                out.append(json.loads(mp.read_text(encoding="utf-8")))
            except Exception:
                out.append({"id": d.name, "name": d.name, "error": "invalid manifest"})
        else:
            out.append({"id": d.name, "name": d.name})
    return out


def install_from_git(url: str, name: str | None = None) -> dict[str, Any]:
    """Clone a git URL into ``.layla/skill_packs_installed/<name>``."""
    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    slug = (name or url.rstrip("/").split("/")[-1].replace(".git", "")).strip() or "pack"
    dest = INSTALLED_DIR / slug
    if dest.exists():
        return {"ok": False, "error": f"already installed: {slug}"}
    try:
        subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True, timeout=600)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not _manifest_path(dest).exists():
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "error": "cloned repo missing manifest.json"}
    return {"ok": True, "path": str(dest), "id": slug}


def remove_pack(pack_id: str) -> dict[str, Any]:
    dest = INSTALLED_DIR / pack_id.strip()
    if not dest.exists():
        return {"ok": False, "error": "not found"}
    shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "removed": pack_id}

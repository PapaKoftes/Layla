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


import re as _re

_SAFE_SLUG_RE = _re.compile(r"^[a-zA-Z0-9_-]+$")
_ALLOWED_SCHEMES = ("https://", "git://")


def install_from_git(url: str, name: str | None = None) -> dict[str, Any]:
    """Clone a git URL into ``.layla/skill_packs_installed/<name>``.

    P1-7: URL sanitization — only ``https://`` and ``git://`` schemes are
    accepted.  Embedded credentials (``user:pass@``) are rejected.  The
    slug is validated against ``[a-zA-Z0-9_-]+``, and the resolved dest
    is verified to stay under INSTALLED_DIR.
    """
    # Scheme allowlist
    url_stripped = url.strip()
    if not any(url_stripped.startswith(s) for s in _ALLOWED_SCHEMES):
        return {"ok": False, "error": "URL scheme not allowed; use https:// or git://"}
    # Block embedded credentials (user:pass@host)
    if "@" in url_stripped.split("://", 1)[-1].split("/")[0]:
        return {"ok": False, "error": "embedded credentials in URL not allowed"}

    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    slug = (name or url.rstrip("/").split("/")[-1].replace(".git", "")).strip() or "pack"

    # Slug must be safe
    if not _SAFE_SLUG_RE.match(slug):
        return {"ok": False, "error": f"invalid pack slug: {slug!r} (only [a-zA-Z0-9_-] allowed)"}

    dest = INSTALLED_DIR / slug

    # Path confinement: resolved dest must stay under INSTALLED_DIR
    if not dest.resolve().is_relative_to(INSTALLED_DIR.resolve()):
        return {"ok": False, "error": "path traversal detected"}

    if dest.exists():
        return {"ok": False, "error": f"already installed: {slug}"}
    try:
        subprocess.run(["git", "clone", "--depth", "1", url_stripped, str(dest)], check=True, timeout=600)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not _manifest_path(dest).exists():
        shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "error": "cloned repo missing manifest.json"}

    # Phase 6: validate manifest via skill_manifest module
    manifest_data: dict | None = None
    try:
        from services.skill_manifest import load_manifest, validate_manifest
        manifest_data = load_manifest(dest)
        if manifest_data is None:
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "error": "manifest.json could not be parsed"}
        errors = validate_manifest(manifest_data)
        if errors:
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "error": f"manifest validation failed: {'; '.join(errors)}"}
    except ImportError:
        # skill_manifest not available — allow install with basic check only
        try:
            manifest_data = json.loads(_manifest_path(dest).read_text(encoding="utf-8"))
        except Exception:
            pass

    # Phase 6: register in skill_registry if available
    try:
        from services.skill_registry import register
        register(
            name=slug,
            version=(manifest_data or {}).get("version", "0.0.0"),
            pack_dir=str(dest),
            manifest=manifest_data,
        )
    except Exception as _reg_err:
        logger.debug("skill_registry registration skipped: %s", _reg_err)

    return {"ok": True, "path": str(dest), "id": slug}


def remove_pack(pack_id: str) -> dict[str, Any]:
    dest = INSTALLED_DIR / pack_id.strip()
    if not dest.exists():
        return {"ok": False, "error": "not found"}
    shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "removed": pack_id}

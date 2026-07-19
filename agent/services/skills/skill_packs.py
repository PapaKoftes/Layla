"""Installable skill packs: manifest + optional knowledge paths (see ``skill_packs/`` in repo root)."""
from __future__ import annotations

import json
import logging
import re as _re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
INSTALLED_DIR = REPO_ROOT / ".layla" / "skill_packs_installed"


def _manifest_path(pack_dir: Path) -> Path | None:
    """Resolve a pack's manifest, accepting BOTH documented names.

    This used to hardcode ``manifest.json``, but the docs name ``layla-skill.json``
    as PREFERRED and ``skill_manifest.find_manifest`` accepts either. A pack
    shipping only the preferred name failed install with "missing manifest.json"
    at the existence pre-check — before ``load_manifest`` (which would have
    accepted it) ever ran. Returns None when neither name is present.
    """
    try:
        from services.skills.skill_manifest import find_manifest
        return find_manifest(pack_dir)
    except ImportError:  # skill_manifest unavailable — fall back to the legacy name
        legacy = pack_dir / "manifest.json"
        return legacy if legacy.exists() else None


_VCS_SCHEMES = ("git+", "hg+", "bzr+", "svn+")
_COMMIT_SHA_RE = _re.compile(r"^[0-9a-fA-F]{40}$")


def _unpinned_dependencies(deps: list[str]) -> list[str]:
    """Return the dependency specifiers that are NOT version-pinned.

    Pinned = an exact version (``name==1.2.3``) or a direct reference to an
    IMMUTABLE artifact. Everything else — a bare name, or a floating range
    (``>=``, ``~=``, ``*``) — is unpinned and can silently pull a different
    (possibly hostile) version on reinstall.

    A direct reference (``name @ <url>``) used to be accepted wholesale, which
    made the docstring's "immutable artifact" false: ``pkg @ git+https://host/r.git``
    and ``...@main`` are BRANCHES. They re-resolve to whatever was pushed last,
    which is precisely the supply-chain substitution this check exists to stop.
    A VCS reference now counts as pinned only when it carries a full 40-character
    commit sha (``...r.git@<sha>``). Plain artifact URLs (an sdist/wheel over
    https/file) stay accepted — the URL names one artifact.
    """
    bad: list[str] = []
    for d in deps:
        spec = (d or "").strip()
        if not spec:
            continue
        if "==" in spec:
            continue
        url = ""
        if " @ " in spec:
            url = spec.split(" @ ", 1)[1].strip()
        elif "@" in spec and "://" in spec:
            url = spec.split("@", 1)[1].strip()
        if not url:
            bad.append(spec)
            continue
        if url.startswith(_VCS_SCHEMES):
            # Immutable only with an explicit commit sha after the final '@'.
            ref = url.rsplit("@", 1)[1].split("#", 1)[0].strip() if "@" in url.split("://", 1)[-1] else ""
            if not _COMMIT_SHA_RE.match(ref):
                bad.append(spec)
            continue
        if "://" not in url:
            bad.append(spec)
    return bad


def _rollback_cleanup(slug: str, dest: Path) -> None:
    """Atomically undo a partial install (pack dir + venv + registry entry).

    Prefers the dedicated ``skill_rollback`` module (which also tears down any
    provisioned venv and registry row); falls back to a plain rmtree so a
    failed install can never leave a half-written pack behind.

    That fallback used to be reachable only from an ``except``, but
    ``rollback_install`` catches its own rmtree failure and signals it by RETURN
    VALUE (``{"ok": False, ...}``) — so the documented guarantee never ran on the
    case that actually happens: on Windows a cloned repo's read-only ``.git``
    objects defeat rmtree, leaving the pack directory behind. Check the return
    value too, and confirm the directory is really gone.
    """
    try:
        from services.skills.skill_rollback import rollback_install
        result = rollback_install(slug, dest) or {}
        if not result.get("ok"):
            logger.debug("skill_rollback reported failure for %s: %s", slug, result.get("actions"))
    except Exception as _rb_err:
        logger.debug("skill_rollback unavailable, falling back to rmtree: %s", _rb_err)

    if dest.exists():
        # Read-only files (git objects) need the write bit cleared before removal.
        def _force(func, path, _exc):
            import os
            import stat
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass
        # `onerror` is deprecated from 3.12 in favour of `onexc`; the handler ignores
        # its third argument, so it is signature-compatible with both.
        import sys as _sys
        _hook = {"onexc": _force} if _sys.version_info >= (3, 12) else {"onerror": _force}
        shutil.rmtree(dest, **_hook)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        if dest.exists():
            logger.warning(
                "skill pack rollback could not remove %s — a partial install remains on disk", dest)


def list_installed() -> list[dict[str, Any]]:
    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(INSTALLED_DIR.iterdir()):
        if not d.is_dir():
            continue
        mp = _manifest_path(d)
        if mp is not None:
            try:
                out.append(json.loads(mp.read_text(encoding="utf-8")))
            except Exception:
                out.append({"id": d.name, "name": d.name, "error": "invalid manifest"})
        else:
            out.append({"id": d.name, "name": d.name})
    return out


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
    if _manifest_path(dest) is None:
        _rollback_cleanup(slug, dest)
        return {"ok": False, "error": "cloned repo missing a manifest (layla-skill.json or manifest.json)"}

    # Phase 6: validate manifest via skill_manifest module
    manifest_data: dict | None = None
    try:
        from services.skills.skill_manifest import load_manifest, validate_manifest
        manifest_data = load_manifest(dest)
        if manifest_data is None:
            _rollback_cleanup(slug, dest)
            return {"ok": False, "error": "manifest.json could not be parsed"}
        errors = validate_manifest(manifest_data)
        if errors:
            _rollback_cleanup(slug, dest)
            return {"ok": False, "error": f"manifest validation failed: {'; '.join(errors)}"}
    except ImportError:
        # skill_manifest not available — allow install with basic check only
        try:
            _mp = _manifest_path(dest)
            if _mp is not None:
                manifest_data = json.loads(_mp.read_text(encoding="utf-8"))
        except Exception:
            pass

    # A6b: supply-chain — reject installs whose declared deps aren't version-pinned.
    try:
        from runtime_safety import load_config
        _cfg = load_config() or {}
    except Exception:
        _cfg = {}
    _declared_deps = [d for d in (manifest_data or {}).get("dependencies", []) if isinstance(d, str)]
    if _cfg.get("skill_deps_require_pinned", True):
        _unpinned = _unpinned_dependencies(_declared_deps)
        if _unpinned:
            _rollback_cleanup(slug, dest)
            return {
                "ok": False,
                "error": "unpinned dependencies (set skill_deps_require_pinned=false to allow): " + ", ".join(_unpinned),
            }

    # Phase 6: register in skill_registry if available
    try:
        from services.skills.skill_registry import register
        _perms = (manifest_data or {}).get("permissions")
        register(
            name=slug,
            version=(manifest_data or {}).get("version", "0.0.0"),
            pack_dir=str(dest),
            manifest=manifest_data,
            # Was omitted, so every pack's declared permissions were silently
            # dropped and the registry stored "[]" — the column existed but was
            # never populated, making a permissions audit read as "none declared".
            permissions=_perms if isinstance(_perms, list) else None,
        )
    except Exception as _reg_err:
        logger.debug("skill_registry registration skipped: %s", _reg_err)

    # Optional sandbox provisioning: create a per-pack venv and install the
    # manifest's declared pip dependencies. Off by default (heavy on low-end
    # hardware, and declarative skills need no venv). When it fails we roll the
    # whole install back atomically so no half-provisioned pack survives.
    try:
        from runtime_safety import load_config
        _cfg = load_config() or {}
    except Exception:
        _cfg = {}
    deps = [d for d in (manifest_data or {}).get("dependencies", []) if isinstance(d, str)]
    if _cfg.get("skill_venv_enabled", False):
        try:
            from services.skills.skill_sandbox import create_venv, install_dependencies
            ok_v, msg_v = create_venv(slug)
            if not ok_v:
                _rollback_cleanup(slug, dest)
                return {"ok": False, "error": f"venv provisioning failed: {msg_v}"}
            if deps:
                ok_d, msg_d = install_dependencies(slug, deps)
                if not ok_d:
                    _rollback_cleanup(slug, dest)
                    return {"ok": False, "error": f"dependency install failed: {msg_d}"}
        except Exception as _venv_err:
            _rollback_cleanup(slug, dest)
            return {"ok": False, "error": f"venv provisioning error: {_venv_err}"}

    return {"ok": True, "path": str(dest), "id": slug}


def list_installed_readonly() -> list[dict[str, Any]]:
    """Installed packs read straight from disk. Creates nothing, writes nothing.

    ``list_installed`` mkdir's INSTALLED_DIR as a side effect, which is wrong for a
    pure query — a read should not materialise operator directories. Returns ``[]``
    when nothing is installed. Each entry carries the pack's directory id plus the
    manifest fields a caller needs to decide whether it is runnable.
    """
    base = INSTALLED_DIR
    out: list[dict[str, Any]] = []
    try:
        if not base.is_dir():
            return out
        entries = sorted(base.iterdir())
    except OSError as e:
        logger.debug("list_installed_readonly: cannot read %s: %s", base, e)
        return out
    for d in entries:
        try:
            if not d.is_dir():
                continue
            manifest: dict[str, Any] = {}
            try:
                from services.skills.skill_manifest import load_manifest
                manifest = load_manifest(d) or {}
            except Exception as e:
                logger.debug("list_installed_readonly: manifest load failed for %s: %s", d, e)
            if not manifest:
                # No readable manifest = not an installed pack. The old ``list_installed``
                # skipped these; this lister appended every directory, so the leftovers of a
                # failed install (or any stray dir) surfaced in list_skill_packs as a phantom
                # pack the operator never installed and cannot run.
                logger.debug("list_installed_readonly: skipping manifest-less dir %s", d)
                continue
            entry_point = manifest.get("entry_point")
            perms = manifest.get("permissions")
            out.append({
                "id": d.name,
                "name": manifest.get("name") or d.name,
                "version": manifest.get("version") or "",
                "description": manifest.get("description") or "",
                "entry_point": entry_point if isinstance(entry_point, str) else "",
                "permissions": perms if isinstance(perms, list) else [],
                "runnable": bool(isinstance(entry_point, str) and entry_point.strip()),
            })
        except OSError as e:
            logger.debug("list_installed_readonly: skipping %s: %s", d, e)
    return out


def installed_summary_for_prompt(cfg: dict | None = None) -> str:
    """One-line-per-pack summary for the decision prompt, or "" when there is nothing to say.

    Mirrors the MCP tool summary: without this the model has no idea an installed
    pack exists and will never choose ``run_skill_pack``. Gated on the same
    execution flag — if packs cannot run, advertising them would only produce a
    tool call that refuses.
    """
    cfg = cfg or {}
    if not cfg.get("skill_packs_execute_enabled", False):
        return ""
    packs = [p for p in list_installed_readonly() if p.get("runnable")]
    if not packs:
        return ""
    lines = ["Installed skill packs (run one with the run_skill_pack tool, pack=<id>):"]
    for p in packs[:20]:
        desc = str(p.get("description") or "").strip().replace("\n", " ")[:160]
        ver = str(p.get("version") or "").strip()
        lines.append(f"- {p['id']}" + (f" (v{ver})" if ver else "") + (f": {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def remove_pack(pack_id: str) -> dict[str, Any]:
    dest = INSTALLED_DIR / pack_id.strip()
    if not dest.exists():
        return {"ok": False, "error": "not found"}
    shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "removed": pack_id}

"""Update Layla when installed from a release ZIP (no git). Dev installs keep using `auto_updater.apply_update` (git pull)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger("layla")


def is_installed_mode() -> bool:
    """True when launcher/installer set per-user data dir (packaged Windows install)."""
    return bool((os.environ.get("LAYLA_DATA_DIR") or "").strip())


def install_root() -> Path:
    """Directory containing `agent/` (repo root in dev, e.g. ``C:\\Program Files\\Layla`` when packaged)."""
    raw = (os.environ.get("LAYLA_INSTALL_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # agent/services/this_file.py -> agent -> parent
    return Path(__file__).resolve().parent.parent.parent


def fetch_latest_release(repo: str) -> dict | None:
    repo = (repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = Request(url, headers={"User-Agent": "layla-local-updater"})
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("fetch_latest_release failed: %s", e)
        return None


def _pick_zip_asset(assets: list) -> dict | None:
    zips = [a for a in (assets or []) if str(a.get("name", "")).lower().endswith(".zip")]
    return zips[0] if zips else None


def assert_zip_extract_safe(zf: zipfile.ZipFile, dest: Path) -> None:
    """Raise ValueError if any archive member would extract outside ``dest`` (zip slip)."""
    dest_res = dest.resolve()
    for member in zf.infolist():
        name = member.filename or ""
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"unsafe_zip_entry:{name!r}")
        resolved = (dest / name).resolve()
        resolved.relative_to(dest_res)


def find_agent_package_in_extract(extract_root: Path) -> Path | None:
    """Locate the `agent` tree (main.py + agent_loop.py + services/)."""
    for main in sorted(extract_root.rglob("main.py")):
        d = main.parent
        try:
            if (d / "agent_loop.py").is_file() and (d / "services").is_dir():
                return d
        except OSError:
            continue
    return None


def apply_release_update() -> dict:
    """Download latest release ZIP, merge `agent/` into install tree, run DB migrate."""
    import runtime_safety as rs
    from services.auto_updater import check_update
    from version import __version__

    cfg = rs.load_config()
    repo = str(cfg.get("github_repo") or "").strip()
    if not repo:
        return {"ok": False, "error": "github_repo_not_configured"}

    chk = check_update(__version__, repo)
    if not chk or not chk.get("ok"):
        return chk or {"ok": False, "error": "update_check_failed"}
    if not chk.get("update_available"):
        return {"ok": True, "message": "Already up to date", "restart_required": False}

    payload = fetch_latest_release(repo)
    if not payload:
        return {"ok": False, "error": "release_fetch_failed"}
    asset = _pick_zip_asset(payload.get("assets") or [])
    if not asset or not asset.get("browser_download_url"):
        return {"ok": False, "error": "no_zip_asset_in_release"}

    dest_agent = install_root() / "agent"
    try:
        dest_agent = dest_agent.resolve()
    except OSError:
        pass
    if not dest_agent.is_dir():
        return {"ok": False, "error": "agent_dir_not_found"}

    url = str(asset["browser_download_url"])
    data_dir = rs.resolve_layla_data_dir()
    staging_parent = (data_dir or dest_agent.parent) / "updates"
    staging_parent.mkdir(parents=True, exist_ok=True)
    zpath = staging_parent / "layla_release_download.zip"

    try:
        req = Request(url, headers={"User-Agent": "layla-local-updater"})
        with urlopen(req, timeout=600) as resp, open(zpath, "wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as e:
        return {"ok": False, "error": f"download_failed: {e}"}

    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            with zipfile.ZipFile(zpath, "r") as zf:
                try:
                    assert_zip_extract_safe(zf, tdp)
                except ValueError as ve:
                    return {"ok": False, "error": str(ve)}
                zf.extractall(tdp)
            new_agent = find_agent_package_in_extract(tdp)
            if not new_agent:
                return {"ok": False, "error": "agent_tree_not_found_in_zip"}
            for root, _dirs, files in os.walk(new_agent):
                rel = Path(root).relative_to(new_agent)
                target_dir = dest_agent / rel
                target_dir.mkdir(parents=True, exist_ok=True)
                for fn in files:
                    shutil.copy2(Path(root) / fn, target_dir / fn)
    finally:
        try:
            zpath.unlink(missing_ok=True)
        except Exception:
            try:
                if zpath.exists():
                    zpath.unlink()
            except Exception:
                pass

    try:
        rs.invalidate_config_cache()
    except Exception:
        pass
    try:
        from layla.memory.migrations import migrate

        migrate()
    except Exception as e:
        logger.warning("post-update migrate: %s", e)

    return {
        "ok": True,
        "message": "Release files merged into agent/. Restart Layla to load the new build.",
        "restart_required": True,
    }

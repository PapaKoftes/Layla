"""Simple release check + git pull updater."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


def _normalize_tag(tag: str) -> str:
    t = (tag or "").strip()
    if t.lower().startswith("v"):
        t = t[1:]
    return t


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in _normalize_tag(version).split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out) if out else (0,)


def check_update(current_version: str, github_repo: str) -> dict:
    repo = (github_repo or "").strip().strip("/")
    if not repo or "/" not in repo:
        return {"ok": False, "error": "github_repo_not_configured"}
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = Request(url, headers={"User-Agent": "layla-local-updater"})
        with urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        latest_tag = (payload.get("tag_name") or "").strip()
        latest_version = _normalize_tag(latest_tag)
        current_clean = _normalize_tag(current_version)
        update_available = _parse_version_tuple(latest_version) > _parse_version_tuple(current_clean)
        return {
            "ok": True,
            "update_available": bool(update_available),
            "current_version": current_clean,
            "latest_version": latest_version or current_clean,
            "release_url": payload.get("html_url") or "",
            "changelog": (payload.get("body") or "")[:4000],
        }
    except Exception as e:
        return {"ok": False, "error": f"update_check_failed: {e}"}


def apply_update(repo_root: Path) -> dict:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        if status.returncode != 0:
            return {"ok": False, "error": (status.stderr or status.stdout or "git status failed").strip()}
        if (status.stdout or "").strip():
            return {"ok": False, "error": "Working tree is dirty - commit or stash changes first"}

        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "git pull failed").strip()}

        req_path = repo_root / "agent" / "requirements.txt"
        if req_path.exists():
            pip_cmd = [
                "python",
                "-m",
                "pip",
                "install",
                "-r",
                str(req_path),
                "-q",
            ]
            pip_res = subprocess.run(
                pip_cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=180,
                encoding="utf-8",
                errors="replace",
            )
            if pip_res.returncode != 0:
                return {
                    "ok": False,
                    "error": (pip_res.stderr or pip_res.stdout or "pip sync failed").strip(),
                }

        return {
            "ok": True,
            "message": (r.stdout or "Updated.").strip(),
            "restart_required": True,
        }
    except Exception as e:
        return {"ok": False, "error": f"update_apply_failed: {e}"}

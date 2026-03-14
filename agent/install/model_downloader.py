"""
Model downloader for Layla installer.
Uses huggingface_hub when available, falls back to urllib.
Shows progress bar and verifies file integrity.

Canonical models directory: ONE place for all models.
- When running from repo: repo/models/
- Otherwise: ~/.layla/models/
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

# Paths
_INSTALL_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _INSTALL_DIR.parent
REPO_MODELS_DIR = _REPO_ROOT / "models"
HOME_MODELS_DIR = Path.home() / ".layla" / "models"


def get_canonical_models_dir() -> Path:
    """
    The ONE canonical directory for models. All downloads and config point here.
    - Repo install: repo/models/
    - Standalone: ~/.layla/models/
    """
    if _REPO_ROOT.exists() and (_REPO_ROOT / "agent").exists():
        return REPO_MODELS_DIR
    return HOME_MODELS_DIR


def get_models_dir(prefer_repo: bool = True) -> Path:
    """Alias for get_canonical_models_dir. Kept for backward compatibility."""
    return get_canonical_models_dir()


def download_model(
    model: dict[str, Any],
    models_dir: Path | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    """
    Download a model from the catalog.

    Args:
        model: Catalog entry with download_url, filename, repo_id.
        models_dir: Where to save. Default ~/.layla/models.
        progress: Show progress bar.

    Returns:
        {"ok": bool, "path": str | None, "filename": str | None, "error": str | None}
    """
    models_dir = models_dir or get_canonical_models_dir()
    models_dir.mkdir(parents=True, exist_ok=True)

    url = model.get("download_url") or model.get("url")
    filename = model.get("filename") or (url.rstrip("/").split("/")[-1] if url else None)
    repo_id = model.get("repo_id")

    if not filename:
        return {"ok": False, "path": None, "filename": None, "error": "No filename in model entry"}

    dest = models_dir / filename

    # Try huggingface_hub first (supports hf_transfer for faster downloads)
    try:
        from huggingface_hub import hf_hub_download
        if repo_id and not url:
            # Use repo_id + filename
            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(models_dir),
                local_dir_use_symlinks=False,
                force_download=False,
            )
            return {"ok": True, "path": path, "filename": filename, "error": None}
        elif repo_id:
            # Prefer hf_hub_download for reliability
            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(models_dir),
                local_dir_use_symlinks=False,
                force_download=False,
            )
            return {"ok": True, "path": path, "filename": filename, "error": None}
    except ImportError:
        pass
    except Exception as e:
        if progress:
            print(f"  [note] HuggingFace Hub failed: {e}. Trying direct download...")

    # Fallback: direct URL download
    if not url:
        return {"ok": False, "path": None, "filename": None, "error": "No download URL"}

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if not progress or total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, int(downloaded * 100 / total_size))
        done = pct // 2
        bar = "█" * done + "░" * (50 - done)
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        print(f"\r  [{bar}] {pct}%  {downloaded_mb:.0f}/{total_mb:.0f} MB", end="", flush=True)

    try:
        if progress:
            urllib.request.urlretrieve(url, str(dest), _progress)
            print()
        else:
            urllib.request.urlretrieve(url, str(dest))

        # Basic integrity: file exists and has reasonable size (> 1 MB)
        if dest.exists() and dest.stat().st_size > 1024 * 1024:
            return {"ok": True, "path": str(dest), "filename": filename, "error": None}
        else:
            dest.unlink(missing_ok=True)
            return {"ok": False, "path": None, "filename": None, "error": "Downloaded file too small or missing"}
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        return {"ok": False, "path": None, "filename": None, "error": str(e)}


def verify_file(path: Path) -> bool:
    """
    Basic integrity check: file exists and has non-zero size.
    Full checksum verification would require catalog to store expected hashes.
    """
    if not path.exists():
        return False
    return path.stat().st_size > 1024 * 1024  # At least 1 MB

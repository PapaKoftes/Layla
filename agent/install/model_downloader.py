"""
Model downloader for Layla installer.
Uses huggingface_hub when available, falls back to urllib.
Shows progress bar and verifies file integrity.

Canonical models directory: ONE place for all models.
- When running from repo: repo/models/
- Otherwise: ~/.layla/models/

Direct HTTP downloads use a *.gguf.part temporary file plus *.part.meta JSON for resume
(Content-Length + byte offset); the final *.gguf is committed with os.replace (atomic).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("layla")


def _is_safe_url(url: str) -> bool:
    """Return True if URL is safe (no private/localhost). SSRF mitigation."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        if host.startswith("127.") or host.startswith("10.") or host.startswith("169.254."):
            return False
        if host.startswith("172."):
            parts = host.split(".")
            if len(parts) >= 2:
                try:
                    b = int(parts[1])
                except ValueError:
                    b = -1
                if 16 <= b <= 31:
                    return False
        return True
    except Exception:
        return False


def _safe_filename(name: str) -> str | None:
    """Return basename if safe (no path traversal), else None."""
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    return Path(name).name or None


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


def _part_paths(dest: Path) -> tuple[Path, Path]:
    """Return (partial download path, sidecar meta JSON path)."""
    part = dest.with_name(dest.name + ".part")
    meta = dest.with_name(dest.name + ".part.meta")
    return part, meta


def _fsync_file(fp: Any) -> None:
    try:
        fp.flush()
        os.fsync(fp.fileno())
    except Exception:
        pass


def _parse_total_from_content_range(header: str | None) -> int | None:
    if not header:
        return None
    # e.g. bytes 0-1048575/123456789
    try:
        if "/" in header:
            total = header.split("/")[-1].strip()
            if total.isdigit():
                return int(total)
    except Exception:
        pass
    return None


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> Any:
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def _norm_etag(val: str | None) -> str:
    if not val:
        return ""
    s = val.strip()
    if s.startswith("W/"):
        s = s[2:].strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s


def _head_metadata(url: str) -> dict[str, Any]:
    """Probe URL for Content-Length and ETag (resume / invalidation)."""
    out: dict[str, Any] = {"content_length": None, "etag": ""}
    try:
        resp = _http_request(url, method="HEAD", timeout=60)
        try:
            cl = resp.headers.get("Content-Length")
            if cl and str(cl).isdigit():
                out["content_length"] = int(cl)
            out["etag"] = _norm_etag(resp.headers.get("ETag"))
        finally:
            resp.close()
    except Exception as e:
        logger.warning("[download] HEAD probe failed (%s); continuing without ETag/size pre-check", e)
    return out


def _head_content_length(url: str) -> int | None:
    return _head_metadata(url).get("content_length")  # type: ignore[return-value]


def _integrity_min_bytes(model: dict[str, Any]) -> int:
    floor = 1024 * 1024
    mb = model.get("min_bytes")
    if isinstance(mb, int) and mb > 0:
        floor = max(floor, mb)
    exp = model.get("expected_size_bytes") or model.get("size_bytes")
    if isinstance(exp, int) and exp > 0:
        # Reject truncated downloads that still exceed generic min_bytes
        floor = max(floor, int(exp * 0.95))
    return floor


def _integrity_expected_exact(model: dict[str, Any]) -> int | None:
    exp = model.get("expected_size_bytes") or model.get("size_bytes")
    if isinstance(exp, int) and exp > 0:
        return exp
    return None


def _verify_before_commit(path: Path, model: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "File missing after download"
    sz = path.stat().st_size
    min_b = _integrity_min_bytes(model)
    if sz < min_b:
        return False, f"File too small ({sz} bytes; minimum {min_b})"
    exact = _integrity_expected_exact(model)
    if exact is not None and abs(sz - exact) > max(512, exact // 10000):
        return False, f"Size mismatch (got {sz}, expected ~{exact})"
    expected_sha = (model.get("sha256") or "").strip().lower()
    if expected_sha:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        if hasher.hexdigest().lower() != expected_sha:
            return False, "SHA256 mismatch"
    return True, ""


def try_load_part_meta(meta_path: Path) -> dict[str, Any] | None:
    """Parse `.part.meta` JSON; return ``None`` if missing or corrupt."""
    try:
        raw = meta_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def part_exceeds_server_total(part_path: Path, server_total: int | None) -> bool:
    """True if local partial is larger than the declared full-object size (corruption or stale meta)."""
    if server_total is None or server_total <= 0:
        return False
    try:
        return part_path.is_file() and part_path.stat().st_size > server_total
    except Exception:
        return False


def _remove_corrupt(dest: Path, part: Path, meta: Path) -> None:
    """Drop incomplete / failed download state (always remove both .part and .meta)."""
    for p in (dest, part, meta):
        try:
            if p.is_file():
                os.remove(p)
        except Exception:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def _download_direct_http(
    url: str,
    dest: Path,
    model: dict[str, Any],
    *,
    progress: bool,
) -> dict[str, Any]:
    """Stream download with .part + .part.meta resume and atomic replace."""
    if not _is_safe_url(url):
        return {"ok": False, "path": None, "filename": None, "error": "URL not allowed (private/localhost blocked)"}

    filename = dest.name
    part_path, meta_path = _part_paths(dest)

    expected_sha = (model.get("sha256") or "").strip().lower()
    url_norm = url.strip()
    live = _head_metadata(url_norm)
    live_cl: int | None = live.get("content_length")
    live_etag = str(live.get("etag") or "")

    def write_meta(
        written: int,
        total: int | None,
        *,
        etag_s: str,
        cl_s: int | None,
    ) -> None:
        payload = {
            "url": url_norm,
            "etag": etag_s or None,
            "content_length": cl_s,
            "filename": filename,
            "bytes_written": written,
            "sha256_expected": expected_sha or None,
        }
        meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def restart_download(cause: str) -> None:
        logger.info("[download] restart: %s", cause)
        try:
            part_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            meta_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Load + validate resume metadata (URL / ETag / size)
    offset = 0
    total_hint: int | None = live_cl
    meta_cl: int | None = None
    meta_etag = ""

    if part_path.exists() and meta_path.is_file():
        meta = try_load_part_meta(meta_path)
        if meta is None:
            logger.warning("Corrupt .part.meta — restarting download")
            restart_download("corrupt .part.meta")
            offset = 0
        else:
            meta_url = str(meta.get("url") or "")
            meta_fn = str(meta.get("filename") or "")
            meta_cl = meta.get("content_length") if isinstance(meta.get("content_length"), int) else None
            meta_etag = _norm_etag(str(meta.get("etag") or ""))
            try:
                if meta_url != url_norm or meta_fn != filename:
                    restart_download("url or filename mismatch")
                elif meta_etag and live_etag and meta_etag != live_etag:
                    restart_download("etag mismatch")
                elif (
                    meta_cl is not None
                    and live_cl is not None
                    and meta_cl > 0
                    and live_cl > 0
                    and meta_cl != live_cl
                ):
                    restart_download("content_length mismatch vs server")
                else:
                    ps = part_path.stat().st_size
                    if live_cl is not None and live_cl > 0 and ps > live_cl:
                        restart_download("partial larger than HEAD Content-Length")
                        offset = 0
                    else:
                        offset = int(meta.get("bytes_written") or ps)
                        offset = min(offset, ps)
                        if meta_cl is not None and ps > meta_cl:
                            restart_download("partial larger than recorded content_length")
                            offset = 0
                        elif isinstance(meta.get("content_length"), int):
                            total_hint = meta_cl
            except Exception as e:
                logger.warning("Invalid resume metadata — restarting download (%s)", e)
                restart_download("invalid meta fields")
                offset = 0
    else:
        if part_path.exists():
            part_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        offset = 0

    attempt = 0
    max_attempts = 5
    resp_etag = live_etag
    resp_cl_store = live_cl

    while attempt < max_attempts:
        attempt += 1
        headers: dict[str, str] = {}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"

        try:
            resp = _http_request(url_norm, headers=headers or None, timeout=120)
        except Exception as e:
            return {"ok": False, "path": None, "filename": None, "error": str(e)}

        try:
            code = resp.getcode()
            resp_etag = _norm_etag(resp.headers.get("ETag")) or resp_etag
            cr = resp.headers.get("Content-Range")
            parsed_total = _parse_total_from_content_range(cr)
            cl_header = resp.headers.get("Content-Length")

            total_size: int | None = total_hint
            if parsed_total is not None:
                total_size = parsed_total

            # Server sent full entity while we expected a ranged response
            if code == 200 and offset > 0:
                resp.close()
                restart_download("server ignored Range (200 while resuming)")
                offset = 0
                total_hint = live_cl
                continue

            # Orphan partial: full response but bytes already on disk without a ranged read
            if code == 200 and part_path.exists() and part_path.stat().st_size > 0 and offset == 0:
                resp.close()
                restart_download("200 with existing partial file (clean restart)")
                continue

            if code == 416:
                resp.close()
                restart_download("416 range not satisfiable")
                offset = 0
                continue

            if total_size is None and cl_header and str(cl_header).isdigit():
                total_size = int(cl_header)
                resp_cl_store = total_size
                if code == 206 and offset > 0:
                    total_size = offset + int(cl_header)

            if cl_header and str(cl_header).isdigit():
                resp_cl_store = int(cl_header) if code == 200 else resp_cl_store

            if part_exceeds_server_total(part_path, total_size):
                resp.close()
                restart_download("partial on disk larger than server entity size")
                offset = 0
                total_hint = live_cl
                continue

            mode = "ab" if offset > 0 else "wb"
            if mode == "wb":
                part_path.parent.mkdir(parents=True, exist_ok=True)

            block = 1024 * 1024  # 1 MiB reads for reasonable throughput on wide RTTs
            downloaded_blocks = offset // block if block else 0

            try:
                with part_path.open(mode) as out:
                    if offset == 0:
                        _fsync_file(out)
                    while True:
                        try:
                            chunk = resp.read(block)
                        except KeyboardInterrupt:
                            _fsync_file(out)
                            try:
                                bw = part_path.stat().st_size
                            except Exception:
                                bw = offset
                            write_meta(
                                bw,
                                total_size,
                                etag_s=resp_etag,
                                cl_s=resp_cl_store if total_size is None else total_size,
                            )
                            raise
                        if not chunk:
                            break
                        out.write(chunk)
                        offset += len(chunk)
                        downloaded_blocks += 1
                        if downloaded_blocks % 16 == 0:
                            _fsync_file(out)
                            write_meta(
                                offset,
                                total_size,
                                etag_s=resp_etag,
                                cl_s=resp_cl_store if total_size is None else total_size,
                            )
                        if progress and total_size and total_size > 0:
                            pct = min(100, int(offset * 100 / total_size))
                            done = pct // 2
                            bar = "█" * done + "░" * (50 - done)
                            print(
                                f"\r  [{bar}] {pct}%  {offset / (1024 * 1024):.0f}/"
                                f"{total_size / (1024 * 1024):.0f} MB",
                                end="",
                                flush=True,
                            )

                    _fsync_file(out)
            except KeyboardInterrupt:
                try:
                    resp.close()
                except Exception:
                    pass
                raise

            cl_for_meta = total_size if total_size is not None else resp_cl_store
            write_meta(offset, total_size or offset, etag_s=resp_etag, cl_s=cl_for_meta)
            if progress:
                print()

            # When catalog provides sha256, _verify_before_commit hashes the full .part once
            # (avoids re-hashing the entire existing partial on resume at start of request).
            ok_verify, err_msg = _verify_before_commit(part_path, model)
            if not ok_verify:
                _remove_corrupt(dest, part_path, meta_path)
                return {"ok": False, "path": None, "filename": None, "error": err_msg or "Integrity check failed"}

            try:
                os.replace(part_path, dest)
            except OSError as e:
                return {"ok": False, "path": None, "filename": None, "error": str(e)}
            try:
                meta_path.unlink(missing_ok=True)
            except Exception:
                pass

            return {"ok": True, "path": str(dest), "filename": filename, "error": None}
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return {"ok": False, "path": None, "filename": None, "error": "Download failed after retries"}


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
    raw_filename = model.get("filename") or (url.rstrip("/").split("/")[-1] if url else None)
    repo_id = model.get("repo_id")

    filename = _safe_filename(raw_filename) if raw_filename else None
    if not filename:
        return {"ok": False, "path": None, "filename": None, "error": "No filename in model entry or invalid path"}

    dest = models_dir / filename

    # Try huggingface_hub first (supports hf_transfer for faster downloads)
    try:
        from huggingface_hub import hf_hub_download

        if repo_id:
            try:
                path = hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(models_dir),
                    local_dir_use_symlinks=False,
                    force_download=False,
                )
                p = Path(path)
                ok_v, err_v = _verify_before_commit(p, model)
                if ok_v:
                    return {"ok": True, "path": str(p), "filename": filename, "error": None}
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
                if not url:
                    return {"ok": False, "path": None, "filename": None, "error": err_v or "Integrity check failed"}
                if progress:
                    print(f"  [note] Hub file failed verification ({err_v}). Trying direct URL…")
            except Exception as e:
                if progress:
                    print(f"  [note] HuggingFace Hub failed: {e}. Trying direct download...")
                if not url:
                    return {"ok": False, "path": None, "filename": None, "error": str(e)}
    except ImportError:
        pass

    # Fallback: direct URL download (SSRF: block private IPs)
    if not url:
        return {"ok": False, "path": None, "filename": None, "error": "No download URL"}
    return _download_direct_http(url, dest, model, progress=progress)


def verify_file(path: Path, expected_sha256: str = "") -> bool:
    """
    Basic integrity check: file exists and minimum size.
    If expected_sha256 is provided, verify exact file hash.
    """
    if not path.exists():
        return False
    if path.stat().st_size <= 1024 * 1024:
        return False
    expected = (expected_sha256 or "").strip().lower()
    if not expected:
        return True

    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower() == expected

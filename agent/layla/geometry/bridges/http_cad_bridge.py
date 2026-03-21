"""HTTP client for operator-hosted geometry bridge (returns JSON program)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse


def _allowed_url(base: str, full: str, allow_localhost: bool) -> bool:
    try:
        bu = urlparse(base)
        fu = urlparse(full)
    except Exception:
        return False
    if bu.scheme not in ("http", "https") or fu.scheme not in ("http", "https"):
        return False
    if bu.netloc != fu.netloc:
        return False
    if not allow_localhost and bu.hostname in ("127.0.0.1", "localhost", "::1"):
        return False
    return full.startswith(base.rstrip("/") + "/") or full.rstrip("/") == base.rstrip("/")


def fetch_program(
    cfg: dict[str, Any],
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    POST JSON to geometry_external_bridge_url + path.
    Returns {"ok": bool, "program": dict|None, "error": str}.
    """
    base = (cfg.get("geometry_external_bridge_url") or "").strip()
    if not base:
        return {"ok": False, "program": None, "error": "geometry_external_bridge_url not set"}
    allow_local = bool(cfg.get("geometry_external_bridge_allow_insecure_localhost", False))
    url = urljoin(base if base.endswith("/") else base + "/", path.lstrip("/"))
    if not _allowed_url(base, url, allow_local):
        return {"ok": False, "program": None, "error": "URL not under allowlisted base"}

    payload = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except urllib.error.HTTPError as e:
        return {"ok": False, "program": None, "error": f"HTTP {e.code}: {(e.read() or b'').decode()[:500]}"}
    except Exception as e:
        return {"ok": False, "program": None, "error": str(e)}

    if isinstance(data, dict) and "program" in data:
        prog = data["program"]
    elif isinstance(data, dict) and "version" in data and "ops" in data:
        prog = data
    else:
        return {"ok": False, "program": None, "error": "bridge response must be a GeometryProgram or {program: {...}}"}

    return {"ok": True, "program": prog, "error": ""}

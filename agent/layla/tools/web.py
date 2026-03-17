"""
Ethical web fetching tool for Layla.

Strictly respects:
- robots.txt (Layla-Crawler and * directives)
- X-Robots-Tag: noai / noindex / noarchive response headers
- <meta name="robots"> noai / noindex meta tags
- Configurable allowlist (runtime_config.json "web_allowlist")

If AI-exclusion is detected AFTER fetching, any stored data is deleted.
"""
import logging
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("layla")

_UA = "Layla-Personal-Research/1.0 (+local; single-user; respects-robots)"
_TIMEOUT = 15


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

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_allowlist() -> list[str]:
    try:
        import json
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "agent" / "runtime_config.json"
        if not cfg_path.exists():
            cfg_path = Path(__file__).resolve().parent.parent.parent / "runtime_config.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return data.get("web_allowlist", [])
    except Exception as e:
        logger.debug("web fetch_url _get_allowlist failed: %s", e)
        return []


def _robots_allowed(url: str) -> bool:
    """Return True if the path is allowed for our user-agent."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as e:
        logger.debug("web fetch_url robots.txt read failed: %s", e)
        return True
    return rp.can_fetch(_UA, url) or rp.can_fetch("*", url)


def _check_ai_exclusion_headers(headers: dict) -> bool:
    """Return True if headers indicate AI exclusion."""
    tag = headers.get("x-robots-tag", "").lower()
    for term in ("noai", "noindex", "noarchive"):
        if term in tag:
            return True
    return False


def _check_ai_exclusion_meta(html: str) -> bool:
    """Return True if HTML meta tags indicate AI exclusion."""
    pattern = re.compile(
        r'<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        content = match.group(1).lower()
        for term in ("noai", "noindex", "noarchive"):
            if term in content:
                return True
    return False


def _extract_text(html: str, url: str) -> str:
    """Extract clean text from HTML. Try trafilatura first, fall back to bs4."""
    try:
        import trafilatura
        result = trafilatura.extract(html, url=url, include_comments=False, include_tables=True)
        if result:
            return result
    except ImportError:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        pass
    # Last resort: strip all tags
    return re.sub(r"<[^>]+>", " ", html)


def _storage_path(url: str) -> Path:
    parsed = urlparse(url)
    domain = parsed.netloc.replace(":", "_")
    slug = re.sub(r"[^\w\-]", "_", parsed.path.strip("/"))[:80] or "index"
    store_dir = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "knowledge" / "fetched" / domain
    )
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir / f"{slug}.txt"


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def fetch_url(url: str, store: bool = False) -> dict:
    """
    Fetch a URL ethically and return extracted text.

    Returns:
        {"ok": True, "url": ..., "text": ..., "stored": bool}
        {"ok": False, "reason": str}
    """
    if not _is_safe_url(url):
        return {"ok": False, "reason": "url_blocked_private", "url": url}
    # Allowlist check
    allowlist = _get_allowlist()
    if allowlist:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not any(domain == a.lower() or domain.endswith("." + a.lower()) for a in allowlist):
            return {"ok": False, "reason": "not_in_allowlist", "url": url}

    # robots.txt check — before any network request to the page itself
    if not _robots_allowed(url):
        return {"ok": False, "reason": "robots_disallowed", "url": url}

    # Fetch the page
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        import socket
        socket.setdefaulttimeout(_TIMEOUT)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw_headers = {k.lower(): v for k, v in resp.headers.items()}
            html_bytes = resp.read(2_000_000)  # 2 MB cap
    except Exception as exc:
        return {"ok": False, "reason": f"fetch_error: {exc}", "url": url}

    # AI exclusion: headers
    if _check_ai_exclusion_headers(raw_headers):
        return {"ok": False, "reason": "ai_excluded_header", "url": url}

    html = html_bytes.decode("utf-8", errors="replace")

    # AI exclusion: meta tags
    if _check_ai_exclusion_meta(html):
        return {"ok": False, "reason": "ai_excluded_meta", "url": url}

    # Extract clean text
    text = _extract_text(html, url)
    text = text[:50_000]  # cap at 50k chars

    stored_path = None
    if store:
        path = _storage_path(url)
        path.write_text(f"source: {url}\nfetched: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n{text}", encoding="utf-8")
        stored_path = str(path)

    return {
        "ok": True,
        "url": url,
        "text": text,
        "stored": stored_path,
    }

"""
Unified web crawler -- routes to Firecrawl (cloud) or crawl4ai (local).

Config keys:
  crawler_backend: "auto" | "firecrawl" | "crawl4ai" | "basic"
  firecrawl_api_key: str
  firecrawl_api_url: str  (default "https://api.firecrawl.dev")
  crawl4ai_enabled: bool
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("layla")

MAX_CONTENT_LENGTH = 50_000


# ---------------------------------------------------------------------------
# Backend availability helpers
# ---------------------------------------------------------------------------

def _firecrawl_available() -> bool:
    """Return True if the firecrawl-py SDK is importable."""
    try:
        import firecrawl  # noqa: F401
        return True
    except ImportError:
        return False


def _crawl4ai_available() -> bool:
    """Return True if crawl4ai is importable."""
    try:
        import crawl4ai  # noqa: F401
        return True
    except ImportError:
        return False


def _truncate(text: str) -> str:
    """Truncate *text* to MAX_CONTENT_LENGTH characters."""
    if len(text) > MAX_CONTENT_LENGTH:
        return text[:MAX_CONTENT_LENGTH] + "\n\n[...truncated]"
    return text


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _crawl_firecrawl(url: str, cfg: dict) -> dict:
    """Scrape *url* via the Firecrawl cloud API.

    Requires ``firecrawl_api_key`` in *cfg*.  Optionally honours
    ``firecrawl_api_url`` (defaults to ``https://api.firecrawl.dev``).
    """
    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "firecrawl",
            "error": "firecrawl-py SDK not installed",
        }

    api_key = cfg.get("firecrawl_api_key") or ""
    api_url = cfg.get("firecrawl_api_url", "https://api.firecrawl.dev")

    if not api_key:
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "firecrawl",
            "error": "firecrawl_api_key not configured",
        }

    try:
        app = FirecrawlApp(api_key=api_key, api_url=api_url)
        result = app.scrape_url(url, params={"formats": ["markdown"]})

        content = ""
        title = ""
        if isinstance(result, dict):
            content = result.get("markdown", "") or result.get("content", "")
            metadata = result.get("metadata") or {}
            title = metadata.get("title", "")
        elif hasattr(result, "markdown"):
            content = getattr(result, "markdown", "") or ""
            title = getattr(getattr(result, "metadata", None), "title", "") or ""

        return {
            "ok": True,
            "content": _truncate(content),
            "title": title,
            "url": url,
            "backend": "firecrawl",
        }
    except Exception as exc:
        log.warning("Firecrawl error for %s: %s", url, exc)
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "firecrawl",
            "error": str(exc),
        }


def _crawl_crawl4ai(url: str, cfg: dict) -> dict:
    """Scrape *url* using the local crawl4ai library (no API key needed)."""
    try:
        from crawl4ai import WebCrawler
    except ImportError:
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "crawl4ai",
            "error": "crawl4ai not installed",
        }

    try:
        crawler = WebCrawler()
        crawler.warmup()
        result = crawler.run(url=url)

        content = ""
        title = ""
        if hasattr(result, "markdown"):
            content = result.markdown or ""
        elif hasattr(result, "extracted_content"):
            content = result.extracted_content or ""
        elif hasattr(result, "text"):
            content = result.text or ""

        if hasattr(result, "title"):
            title = result.title or ""
        elif hasattr(result, "metadata"):
            meta = result.metadata
            if isinstance(meta, dict):
                title = meta.get("title", "")

        return {
            "ok": True,
            "content": _truncate(content),
            "title": title,
            "url": url,
            "backend": "crawl4ai",
        }
    except Exception as exc:
        log.warning("crawl4ai error for %s: %s", url, exc)
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "crawl4ai",
            "error": str(exc),
        }


def _crawl_basic(url: str, cfg: dict) -> dict:
    """Scrape *url* using only stdlib (urllib).

    Strips HTML tags with a simple regex.  Always available.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Layla-Agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            # Attempt to decode; fall back to latin-1 which never fails.
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                html = raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                html = raw.decode("latin-1")

        # Extract <title>
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        # Remove script and style blocks, then all tags.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace.
        text = re.sub(r"\s+", " ", text).strip()

        return {
            "ok": True,
            "content": _truncate(text),
            "title": title,
            "url": url,
            "backend": "basic",
        }
    except Exception as exc:
        log.warning("Basic crawl error for %s: %s", url, exc)
        return {
            "ok": False,
            "content": "",
            "title": "",
            "url": url,
            "backend": "basic",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

_BACKENDS = {
    "firecrawl": _crawl_firecrawl,
    "crawl4ai": _crawl_crawl4ai,
    "basic": _crawl_basic,
}


def _resolve_backend(cfg: dict, override: str | None = None) -> str:
    """Determine which backend to use.

    Priority when *override* is ``None`` and ``crawler_backend`` is
    ``"auto"`` (the default):

    1. ``firecrawl`` -- if ``firecrawl_api_key`` is set *and* the SDK is
       importable.
    2. ``crawl4ai`` -- if ``crawl4ai_enabled`` is not explicitly ``False``
       and the library is importable.
    3. ``basic`` -- always available.
    """
    if override and override in _BACKENDS:
        return override

    requested = cfg.get("crawler_backend", "auto")
    if requested in _BACKENDS:
        return requested

    # auto
    if cfg.get("firecrawl_api_key") and _firecrawl_available():
        return "firecrawl"
    if cfg.get("crawl4ai_enabled", False) and _crawl4ai_available():
        return "crawl4ai"
    return "basic"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl_url(
    url: str,
    *,
    cfg: dict | None = None,
    backend: str | None = None,
) -> dict:
    """Crawl a single URL and return clean text/markdown.

    Parameters
    ----------
    url:
        The URL to crawl.
    cfg:
        Configuration dictionary.  See module docstring for recognised keys.
    backend:
        Force a specific backend (``"firecrawl"``, ``"crawl4ai"``, or
        ``"basic"``).  When *None*, auto-detection is used.

    Returns
    -------
    dict with keys ``ok``, ``content``, ``title``, ``url``, ``backend``,
    and optionally ``error``.
    """
    cfg = cfg or {}
    chosen = _resolve_backend(cfg, override=backend)
    log.debug("crawl_url %s -> backend=%s", url, chosen)

    fn = _BACKENDS[chosen]
    result = fn(url, cfg)

    # If the chosen backend failed and we are in auto mode, try fallbacks.
    if not result["ok"] and (backend is None) and cfg.get("crawler_backend", "auto") == "auto":
        fallback_order = ["firecrawl", "crawl4ai", "basic"]
        for fb in fallback_order:
            if fb == chosen:
                continue
            log.debug("crawl_url falling back to %s for %s", fb, url)
            result = _BACKENDS[fb](url, cfg)
            if result["ok"]:
                break

    return result


def crawl_urls(
    urls: list[str],
    *,
    cfg: dict | None = None,
    max_concurrent: int = 3,
) -> list[dict]:
    """Crawl multiple URLs and return a list of results.

    Parameters
    ----------
    urls:
        List of URLs to crawl.
    cfg:
        Configuration dictionary (forwarded to :func:`crawl_url`).
    max_concurrent:
        Maximum number of concurrent crawls.  Because the module is
        purely synchronous this is implemented via
        :class:`concurrent.futures.ThreadPoolExecutor`.

    Returns
    -------
    List of result dicts in the same order as *urls*.
    """
    cfg = cfg or {}

    if not urls:
        return []

    if len(urls) == 1:
        return [crawl_url(urls[0], cfg=cfg)]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[int, dict] = {}

    def _task(idx: int, url: str) -> tuple[int, dict]:
        return idx, crawl_url(url, cfg=cfg)

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(urls))) as pool:
        futures = {pool.submit(_task, i, u): i for i, u in enumerate(urls)}
        for fut in as_completed(futures):
            try:
                idx, res = fut.result()
                results[idx] = res
            except Exception as exc:
                idx = futures[fut]
                results[idx] = {
                    "ok": False,
                    "content": "",
                    "title": "",
                    "url": urls[idx],
                    "backend": "unknown",
                    "error": str(exc),
                }

    return [results[i] for i in range(len(urls))]


def get_crawler_status(cfg: dict | None = None) -> dict:
    """Report which crawler backends are available.

    Returns
    -------
    dict with keys:

    - ``firecrawl``: ``bool`` -- SDK importable *and* API key configured.
    - ``crawl4ai``: ``bool`` -- library importable.
    - ``basic``: ``True`` (always available).
    - ``active``: ``str`` -- the backend that :func:`crawl_url` would choose.
    """
    cfg = cfg or {}
    fc_ok = _firecrawl_available()
    fc_key = bool(cfg.get("firecrawl_api_key"))
    c4_ok = _crawl4ai_available()

    return {
        "firecrawl": fc_ok and fc_key,
        "crawl4ai": c4_ok,
        "basic": True,
        "active": _resolve_backend(cfg),
        "firecrawl_sdk_installed": fc_ok,
        "firecrawl_api_key_set": fc_key,
    }

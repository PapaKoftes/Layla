"""Tool implementations — domain: web."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def fetch_url_tool(url: str, store: bool = False) -> dict:
    try:
        import runtime_safety
        from services.http_response_cache import get_cached, set_cached

        cfg = runtime_safety.load_config()
        if not store:
            ck = f"fetch:{url}"
            hit = get_cached(ck, cfg)
            if hit is not None:
                return hit
    except Exception:
        cfg = {}
    from layla.tools.web import fetch_url

    out = fetch_url(url, store=store)
    try:
        if not store and out.get("ok"):
            import runtime_safety
            from services.http_response_cache import set_cached

            set_cached(f"fetch:{url}", out, runtime_safety.load_config())
    except Exception:
        pass
    return out

def browser_navigate(url: str, timeout_ms: int = 15000) -> dict:
    """Navigate to a URL and return its main text content and title."""
    try:
        from services.browser import navigate
        return navigate(url, timeout_ms=timeout_ms)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}

def browser_search(query: str) -> dict:
    """Search the web via DuckDuckGo. Returns top 8 results with titles, URLs, snippets."""
    try:
        from services.browser import search_web
        return search_web(query)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}

def browser_screenshot(url: str) -> dict:
    """Take a full-page screenshot of a URL. Returns path to the screenshot file."""
    try:
        from services.browser import screenshot
        return screenshot(url)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}

def browser_click(url: str, selector: str) -> dict:
    """Navigate to a URL, click a CSS selector, return updated page text."""
    try:
        from services.browser import click_and_extract
        return click_and_extract(url, selector)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}

def browser_fill(url: str, fields: dict, submit_selector: str = "") -> dict:
    """Navigate to a URL, fill form fields {selector: value}, optionally submit."""
    try:
        from services.browser import fill_form
        return fill_form(url, fields, submit_selector)
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: playwright install chromium"}

def fetch_article(url: str) -> dict:
    """
    Extract clean text from a web article using trafilatura.
    Much cleaner than raw fetch — removes nav, ads, footers. Ideal for research.
    """
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"ok": False, "error": "Could not fetch URL"}
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if not text:
            # Fallback to raw text
            text = trafilatura.extract(downloaded, favor_recall=True)
        if not text:
            return {"ok": False, "error": "Could not extract content from page"}
        title = ""
        try:
            meta = trafilatura.extract_metadata(downloaded)
            if meta:
                title = meta.title or ""
        except Exception:
            pass
        return {"ok": True, "url": url, "title": title, "text": text[:10000], "chars": len(text)}
    except ImportError:
        return {"ok": False, "error": "trafilatura not installed: pip install trafilatura"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def wiki_search(query: str, sentences: int = 8, lang: str = "en") -> dict:
    """
    Search Wikipedia and return a summary. sentences controls summary length.
    Returns the intro, URL, and a list of related page titles.
    """
    try:
        import wikipedia
        wikipedia.set_lang(lang)
        try:
            summary = wikipedia.summary(query, sentences=sentences, auto_suggest=True)
            page = wikipedia.page(query, auto_suggest=True)
            return {
                "ok": True,
                "query": query,
                "title": page.title,
                "url": page.url,
                "summary": summary,
                "related": page.links[:10],
            }
        except wikipedia.DisambiguationError as e:
            # Return top options on disambiguation
            return {"ok": True, "query": query, "disambiguation": True, "options": e.options[:8]}
        except wikipedia.PageError:
            results = wikipedia.search(query, results=5)
            return {"ok": False, "query": query, "error": "Page not found", "suggestions": results}
    except ImportError:
        return {"ok": False, "error": "wikipedia package not installed: pip install wikipedia-api"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ddg_search(query: str, max_results: int = 10, region: str = "wt-wt") -> dict:
    """
    DuckDuckGo web search — pure Python, no browser required.
    Returns results with title, href, body snippet.
    """
    try:
        import runtime_safety
        from services.http_response_cache import get_cached, set_cached

        cfg = runtime_safety.load_config()
        ck = f"ddg:{region}:{max_results}:{query}"
        hit = get_cached(ck, cfg)
        if hit is not None:
            return hit
    except Exception:
        cfg = {}
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=region, max_results=max_results))
        out = {"ok": True, "query": query, "results": results, "count": len(results)}
        try:
            import runtime_safety
            from services.http_response_cache import set_cached

            set_cached(f"ddg:{region}:{max_results}:{query}", out, runtime_safety.load_config())
        except Exception:
            pass
        return out
    except ImportError:
        return {"ok": False, "error": "duckduckgo-search not installed: pip install duckduckgo-search"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def arxiv_search(query: str, max_results: int = 5, sort_by: str = "relevance") -> dict:
    """
    Search arXiv for papers. Returns title, authors, abstract, PDF URL, published date.
    sort_by: 'relevance' | 'lastUpdatedDate' | 'submittedDate'
    """
    try:
        import arxiv
        sort_map = {
            "relevance": arxiv.SortCriterion.Relevance,
            "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
            "submittedDate": arxiv.SortCriterion.SubmittedDate,
        }
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_map.get(sort_by, arxiv.SortCriterion.Relevance),
        )
        papers = []
        for r in client.results(search):
            papers.append({
                "title": r.title,
                "authors": [str(a) for a in r.authors[:5]],
                "abstract": (r.summary or "")[:500],
                "pdf_url": r.pdf_url,
                "published": str(r.published)[:10] if r.published else "",
                "arxiv_id": r.entry_id.split("/")[-1],
                "categories": r.categories[:3],
            })
        return {"ok": True, "query": query, "results": papers, "count": len(papers)}
    except ImportError:
        return {"ok": False, "error": "arxiv not installed: pip install arxiv"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def http_request(url: str, method: str = "GET", body: str = "", headers: dict | None = None, timeout: int = 15) -> dict:
    """
    Make an HTTP request. method: GET | POST | PUT | DELETE | PATCH.
    Returns status, response text (truncated to 8000 chars).
    Use for webhooks, REST APIs, testing endpoints.
    """
    import urllib.error
    import urllib.request
    method = method.upper()
    hdrs = {"User-Agent": "Layla/2.0 research agent", "Accept": "application/json,text/html,*/*"}
    if headers:
        hdrs.update(headers)
    try:
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read(80000).decode("utf-8", errors="replace")
            return {
                "ok": resp.status < 400,
                "status": resp.status,
                "url": url,
                "text": content[:8000],
                "headers": dict(resp.headers),
            }
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read(2000).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": str(e), "text": body_text}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def crawl_site(
    url: str,
    max_pages: int = 20,
    max_depth: int = 2,
    same_domain: bool = True,
    store_knowledge: bool = False,
) -> dict:
    """
    Crawl a website starting from url. Extracts clean text from each page.
    max_pages: hard cap on pages visited
    max_depth: link-following depth (1 = only start URL, 2 = start + its links, etc.)
    same_domain: only follow links within the same domain
    store_knowledge: save extracted pages to knowledge/fetched/ for later RAG indexing
    Returns: list of {url, title, text, depth} for all visited pages.
    """
    import time
    from urllib.parse import urljoin, urlparse

    try:
        import trafilatura
        from trafilatura.sitemaps import sitemap_search  # noqa: F401
    except ImportError:
        return {"ok": False, "error": "trafilatura not installed: pip install trafilatura"}

    base_domain = urlparse(url).netloc
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]
    results = []
    start_time = time.time()

    while queue and len(results) < max_pages:
        if time.time() - start_time > 120:  # 2 min hard cap
            break
        current_url, depth = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            downloaded = trafilatura.fetch_url(current_url)
            if not downloaded:
                continue
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True, favor_recall=True)
            if not text or len(text.strip()) < 50:
                continue
            title = ""
            links: list[str] = []  # noqa: F841
            try:
                meta = trafilatura.extract_metadata(downloaded)
                if meta:
                    title = meta.title or ""
            except Exception:
                pass
            # Extract links for deeper crawl
            if depth < max_depth - 1:
                try:
                    from trafilatura.urls import extract_links
                    raw_links = extract_links(downloaded, url) or []
                    for link in raw_links[:30]:
                        full = urljoin(current_url, link)
                        if full not in visited:
                            if not same_domain or urlparse(full).netloc == base_domain:
                                queue.append((full, depth + 1))
                except Exception:
                    pass
            page_result = {
                "url": current_url, "title": title,
                "text": text[:4000], "chars": len(text), "depth": depth,
            }
            results.append(page_result)

            # Optionally save to knowledge/fetched/
            if store_knowledge:
                try:
                    slug = urlparse(current_url).path.strip("/").replace("/", "_")[:50] or "index"
                    fetched_dir = Path(__file__).resolve().parent.parent.parent.parent / "knowledge" / "fetched"
                    fetched_dir.mkdir(parents=True, exist_ok=True)
                    out = fetched_dir / f"{base_domain}_{slug}.txt"
                    out.write_text(f"source: {current_url}\ntitle: {title}\n\n{text[:30000]}", encoding="utf-8")
                except Exception:
                    pass

        except Exception:
            continue

    return {
        "ok": True, "start_url": url, "pages_visited": len(results),
        "pages_requested": max_pages, "same_domain": same_domain,
        "results": results,
    }

def extract_links(url: str, same_domain: bool = False, max_links: int = 100) -> dict:
    """
    Extract all hyperlinks from a webpage.
    same_domain: only return links from the same domain.
    Returns: links with href, internal/external classification, domain.
    """
    from urllib.parse import urljoin, urlparse
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"ok": False, "error": "Could not fetch URL"}
        raw_links: list = []
        try:
            from trafilatura.urls import extract_links as _traf_links
            raw_links = list(_traf_links(downloaded, url) or [])
        except Exception:
            pass
        if len(raw_links) < 5:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(downloaded, "html.parser")
                raw_links += [urljoin(url, a.get("href", "")) for a in soup.find_all("a", href=True)]
            except Exception:
                pass
    except ImportError:
        return {"ok": False, "error": "trafilatura not installed"}

    base_domain = urlparse(url).netloc
    links, seen = [], set()
    for link in raw_links:
        link = str(link).strip()
        if not link or link.startswith(("mailto:", "javascript:", "#")) or link in seen or len(links) >= max_links:
            continue
        seen.add(link)
        is_internal = urlparse(link).netloc == base_domain
        if same_domain and not is_internal:
            continue
        links.append({"url": link, "internal": is_internal, "domain": urlparse(link).netloc})

    return {"ok": True, "source_url": url, "total_links": len(links), "internal": sum(1 for lnk in links if lnk["internal"]), "external": sum(1 for lnk in links if not lnk["internal"]), "links": links}

def check_url(url: str, timeout: int = 10) -> dict:
    """
    Check if a URL is accessible. Returns HTTP status, response time, content type.
    Uses HEAD request for speed. Useful for monitoring, link validation.
    """
    import time as _time
    import urllib.error
    import urllib.request
    start = _time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Layla/2.0 health-check"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = round((_time.time() - start) * 1000, 1)
            return {"ok": True, "url": url, "status": resp.status, "accessible": resp.status < 400, "response_ms": elapsed, "content_type": resp.headers.get("Content-Type", ""), "server": resp.headers.get("Server", "")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "url": url, "status": e.code, "accessible": False, "response_ms": round((_time.time() - start) * 1000, 1), "error": str(e)}
    except Exception as e:
        return {"ok": False, "url": url, "accessible": False, "response_ms": round((_time.time() - start) * 1000, 1), "error": str(e)}

def rss_feed(url: str, max_items: int = 20, include_content: bool = False) -> dict:
    """
    Fetch and parse an RSS or Atom feed.
    Returns: feed title, description, and entry list (title, link, published, author, summary, tags).
    include_content: fetch and extract full article text for each entry (slow but thorough).
    """
    try:
        import feedparser
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return {"ok": False, "error": f"Feed parse error: {feed.bozo_exception}"}
        entries = []
        for entry in feed.entries[:max_items]:
            item: dict = {"title": entry.get("title", ""), "link": entry.get("link", ""), "published": str(entry.get("published", "")), "author": entry.get("author", ""), "tags": [t.get("term", "") for t in entry.get("tags", [])], "summary": (entry.get("summary", "") or "")[:400]}
            if include_content and item["link"]:
                try:
                    import trafilatura
                    dl = trafilatura.fetch_url(item["link"])
                    if dl:
                        item["full_text"] = (trafilatura.extract(dl) or "")[:3000]
                except Exception:
                    pass
            entries.append(item)
        return {"ok": True, "url": url, "feed_title": feed.feed.get("title", ""), "feed_description": (feed.feed.get("description", "") or "")[:200], "entry_count": len(entries), "entries": entries}
    except ImportError:
        return {"ok": False, "error": "feedparser not installed: pip install feedparser"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


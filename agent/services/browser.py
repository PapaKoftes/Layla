"""
Layla browser service — Playwright-based web automation.

Provides tools that let Layla navigate web pages, extract text, take
screenshots, fill forms, and click elements.  All operations run in a
persistent headless Chromium instance that is reused across calls.

Install: playwright install chromium
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("layla.browser")

_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / ".screenshots"
_SCREENSHOT_DIR.mkdir(exist_ok=True)

_playwright_lock = threading.Lock()
_pw = None  # playwright instance
_browser = None  # persistent browser
_context = None  # browser context with shared cookies/session
_loop: Optional[asyncio.AbstractEventLoop] = None
_browser_thread: Optional[threading.Thread] = None


# ── Async internals ──────────────────────────────────────────────────────────

async def _ensure_context():
    global _pw, _browser, _context
    if _context is not None:
        return _context
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    _context = await _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        java_script_enabled=True,
    )
    return _context


async def _new_page():
    ctx = await _ensure_context()
    return await ctx.new_page()


async def _navigate(url: str, timeout_ms: int = 15000) -> dict:
    page = await _new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        title = await page.title()
        text = await page.evaluate(
            """() => {
                const el = document.querySelector('main') ||
                           document.querySelector('article') ||
                           document.body;
                return el ? el.innerText.slice(0, 8000) : '';
            }"""
        )
        final_url = page.url
        return {"ok": True, "url": final_url, "title": title, "text": text.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()


async def _screenshot(url: str, timeout_ms: int = 15000) -> dict:
    page = await _new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        ts = int(time.time())
        fname = f"screenshot_{ts}.png"
        fpath = _SCREENSHOT_DIR / fname
        await page.screenshot(path=str(fpath), full_page=True)
        title = await page.title()
        return {"ok": True, "url": page.url, "title": title, "screenshot_path": str(fpath)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()


async def _click_and_extract(url: str, selector: str, timeout_ms: int = 10000) -> dict:
    page = await _new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.click(selector, timeout=5000)
        await page.wait_for_load_state("networkidle", timeout=5000)
        text = await page.evaluate("() => document.body.innerText.slice(0, 6000)")
        return {"ok": True, "url": page.url, "text": text.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()


async def _fill_form(url: str, fields: dict[str, str], submit_selector: str = "", timeout_ms: int = 10000) -> dict:
    """Fill form fields and optionally submit. fields = {css_selector: value}."""
    page = await _new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        for selector, value in fields.items():
            await page.fill(selector, value, timeout=5000)
        if submit_selector:
            await page.click(submit_selector, timeout=5000)
            await page.wait_for_load_state("networkidle", timeout=8000)
        text = await page.evaluate("() => document.body.innerText.slice(0, 6000)")
        return {"ok": True, "url": page.url, "text": text.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()


async def _search_web(query: str, engine: str = "ddg") -> dict:
    """Search the web via DuckDuckGo (no JS required) and return top results."""
    import urllib.parse
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    page = await _new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        links = await page.evaluate(
            """() => {
                const results = [];
                document.querySelectorAll('.result').forEach(el => {
                    const a = el.querySelector('.result__a');
                    const snip = el.querySelector('.result__snippet');
                    if (a) results.push({
                        title: a.innerText.trim(),
                        url: a.href,
                        snippet: snip ? snip.innerText.trim() : ''
                    });
                });
                return results.slice(0, 8);
            }"""
        )
        return {"ok": True, "query": query, "results": links}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()


# ── Event-loop thread ────────────────────────────────────────────────────────

def _get_loop() -> asyncio.AbstractEventLoop:
    """Get (or create) the dedicated asyncio event loop for browser operations."""
    global _loop, _browser_thread

    def _run_loop(loop: asyncio.AbstractEventLoop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    with _playwright_lock:
        if _loop is None or not _loop.is_running():
            _loop = asyncio.new_event_loop()
            _browser_thread = threading.Thread(
                target=_run_loop, args=(_loop,), daemon=True, name="layla-browser"
            )
            _browser_thread.start()
    return _loop


def _run(coro):
    """Run an async coroutine on the browser event loop from any sync thread."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


# ── Public synchronous API ────────────────────────────────────────────────────

def navigate(url: str, timeout_ms: int = 15000) -> dict:
    """
    Navigate to a URL and extract the main text content.
    Returns: {"ok": bool, "url": str, "title": str, "text": str}
    """
    try:
        return _run(_navigate(url, timeout_ms))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def screenshot(url: str, timeout_ms: int = 15000) -> dict:
    """
    Take a full-page screenshot of a URL.
    Returns: {"ok": bool, "url": str, "title": str, "screenshot_path": str}
    """
    try:
        return _run(_screenshot(url, timeout_ms))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def click_and_extract(url: str, selector: str, timeout_ms: int = 10000) -> dict:
    """
    Navigate to URL, click a CSS selector, return updated page text.
    Returns: {"ok": bool, "url": str, "text": str}
    """
    try:
        return _run(_click_and_extract(url, selector, timeout_ms))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fill_form(url: str, fields: dict, submit_selector: str = "", timeout_ms: int = 10000) -> dict:
    """
    Navigate to URL, fill form fields, optionally submit.
    fields: {css_selector: value}
    Returns: {"ok": bool, "url": str, "text": str}
    """
    try:
        return _run(_fill_form(url, fields, submit_selector, timeout_ms))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_web(query: str) -> dict:
    """
    Search DuckDuckGo and return top 8 results.
    Returns: {"ok": bool, "query": str, "results": [{title, url, snippet}]}
    """
    try:
        return _run(_search_web(query))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def close() -> None:
    """Shut down the browser and playwright instance cleanly."""
    global _pw, _browser, _context

    async def _close():
        global _pw, _browser, _context
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _pw:
            await _pw.stop()
        _context = _browser = _pw = None

    try:
        if _loop and _loop.is_running():
            _run(_close())
    except Exception:
        pass

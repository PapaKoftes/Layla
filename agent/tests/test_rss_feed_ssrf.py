"""rss_feed must fetch the feed body through the SSRF-guarded path (safe_fetch_text,
which re-validates every redirect hop) rather than handing the raw URL to
feedparser.parse — whose own urllib fetch would follow a 302/DNS-rebind into an
internal host with no per-hop check. Regression for SSRF #12.

feedparser may not be installed in the test venv, so we inject a minimal stub
module: the point under test is WHAT rss_feed hands to feedparser.parse (the
fetched body, not the raw URL), which is independent of the real parser.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

_FEED_XML = (
    '<?xml version="1.0"?><rss version="2.0"><channel>'
    "<title>Guarded Feed</title><description>ok</description>"
    "<item><title>Entry One</title><link>http://example.com/1</link></item>"
    "</channel></rss>"
)


class _StubFeed:
    def __init__(self):
        self.bozo = 0
        self.bozo_exception = None
        self.entries = [{"title": "Entry One", "link": "http://example.com/1"}]
        self.feed = {"title": "Guarded Feed", "description": "ok"}


def _install_stub_feedparser(monkeypatch, recorder):
    stub = types.ModuleType("feedparser")

    def parse(arg, *a, **k):
        recorder["parse_arg"] = arg
        return _StubFeed()

    stub.parse = parse
    monkeypatch.setitem(sys.modules, "feedparser", stub)
    return stub


def test_rss_feed_fetches_body_via_guarded_path(monkeypatch):
    from layla.tools.impl import web as web_impl
    from services.safety import url_guard

    calls: dict = {"safe_fetch_text_url": None, "parse_arg": None}
    _install_stub_feedparser(monkeypatch, calls)

    def _fake_safe_fetch_text(url, **kwargs):
        calls["safe_fetch_text_url"] = url
        return _FEED_XML

    # is_safe_url uses DNS on real hosts; force the pre-check to pass without a lookup.
    monkeypatch.setattr(url_guard, "is_safe_url", lambda u, **k: True)
    monkeypatch.setattr(url_guard, "safe_fetch_text", _fake_safe_fetch_text)

    result = web_impl.rss_feed("http://public.example.test/feed.xml")

    assert result.get("ok") is True
    # The guarded fetch was used on the feed URL...
    assert calls["safe_fetch_text_url"] == "http://public.example.test/feed.xml"
    # ...and feedparser received the fetched BODY, never the raw URL (which would
    # trigger its own unguarded HTTP GET / redirect following).
    assert calls["parse_arg"] == _FEED_XML
    assert calls["parse_arg"] != "http://public.example.test/feed.xml"


def test_rss_feed_blocks_when_guarded_fetch_fails(monkeypatch):
    from layla.tools.impl import web as web_impl
    from services.safety import url_guard

    calls: dict = {"parse_arg": None}
    _install_stub_feedparser(monkeypatch, calls)

    # is_safe_url passes the literal pre-check, but the guarded body fetch is blocked
    # (e.g. a redirect hop resolved to an internal host) → safe_fetch_text returns ''.
    monkeypatch.setattr(url_guard, "is_safe_url", lambda u, **k: True)
    monkeypatch.setattr(url_guard, "safe_fetch_text", lambda u, **k: "")

    result = web_impl.rss_feed("http://public.example.test/feed.xml")
    assert result.get("ok") is False
    # feedparser.parse must NOT be reached once the guarded fetch fails.
    assert calls["parse_arg"] is None

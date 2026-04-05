"""Web, HTTP, browser, and search tools."""

TOOLS = {
    "fetch_url": {"fn_key": "fetch_url_tool", "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "fetch_article": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "wiki_search": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "ddg_search": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "arxiv_search": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "http_request": {"dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True},
    "browser_navigate": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_search": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_screenshot": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "browser_click": {"dangerous": False, "require_approval": True, "risk_level": "medium"},
    "browser_fill": {"dangerous": False, "require_approval": True, "risk_level": "medium"},
    "crawl_site": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "extract_links": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "check_url": {"dangerous": False, "require_approval": False, "risk_level": "low"},
    "rss_feed": {"dangerous": False, "require_approval": False, "risk_level": "low"},
}

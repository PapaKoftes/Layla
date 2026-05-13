"""Web, HTTP, browser, and search tools."""

TOOLS = {
    "fetch_url": {
        "fn_key": "fetch_url_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "web",
        "description": "Fetch a URL and return its content. Extracts clean text from HTML pages.",
    },
    "fetch_article": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "web",
        "description": "Fetch a web article and extract its main text content, stripping navigation and ads.",
    },
    "wiki_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "search",
        "description": "Search Wikipedia and return article summaries for a given topic.",
    },
    "ddg_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "search",
        "description": "Search the web via DuckDuckGo. Returns titles, URLs, and snippets.",
    },
    "arxiv_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "search",
        "description": "Search arXiv for academic papers by topic, author, or keyword.",
    },
    "http_request": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "web",
        "description": "Send a custom HTTP request (GET/POST/PUT/DELETE) with headers and body.",
    },
    "browser_navigate": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Navigate a headless browser to a URL and return the rendered page content.",
    },
    "browser_search": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Perform a web search in the headless browser and return results.",
    },
    "browser_screenshot": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Take a screenshot of the current browser page and save it as an image.",
    },
    "browser_click": {
        "dangerous": False, "require_approval": True, "risk_level": "medium",
        "category": "web",
        "description": "Click an element on the current browser page by selector or coordinates.",
    },
    "browser_fill": {
        "dangerous": False, "require_approval": True, "risk_level": "medium",
        "category": "web",
        "description": "Fill in a form field on the current browser page with the given text.",
    },
    "crawl_site": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Crawl a website starting from a URL, following links up to a specified depth.",
    },
    "extract_links": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Extract all hyperlinks from a web page, with optional filtering by domain or pattern.",
    },
    "check_url": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Check if a URL is reachable and return its HTTP status code and response time.",
    },
    "rss_feed": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "web",
        "description": "Parse an RSS/Atom feed and return its entries with titles, links, and dates.",
    },
}

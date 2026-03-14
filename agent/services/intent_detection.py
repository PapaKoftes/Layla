"""
Intent-based tool filtering.
Map user prompt to allowed tool categories; filter TOOLS before passing to LLM.
"""

# Intent keywords -> tool categories
_INTENT_MAP = {
    "coding": ["code", "filesystem"],
    "code": ["code", "filesystem"],
    "debug": ["code", "filesystem", "analysis"],
    "implement": ["code", "filesystem"],
    "fix": ["code", "filesystem"],
    "refactor": ["code", "filesystem"],
    "write": ["code", "filesystem"],
    "create file": ["filesystem"],
    "read file": ["filesystem"],
    "research": ["web", "memory"],
    "search": ["web", "memory"],
    "look up": ["web", "memory"],
    "study": ["web", "memory"],
    "explain": ["memory", "web"],
    "analyze": ["analysis", "code", "data"],
    "data": ["data", "analysis"],
    "chart": ["data", "analysis"],
    "plot": ["data", "analysis"],
    "csv": ["data"],
    "pandas": ["data"],
    "memory": ["memory"],
    "remember": ["memory"],
    "learned": ["memory"],
    "system": ["system"],
    "schedule": ["system"],
    "automate": ["automation", "system"],
    "click": ["automation"],
    "screenshot": ["automation"],
}

# Default: allow all categories when no clear intent
_DEFAULT_CATEGORIES = ["filesystem", "web", "code", "data", "memory", "system", "automation", "analysis"]


def detect_intent(user_prompt: str) -> list[str]:
    """
    Map user prompt to allowed tool categories.
    Returns list of category names for filtering TOOLS.
    """
    if not user_prompt or not user_prompt.strip():
        return _DEFAULT_CATEGORIES
    lower = user_prompt.strip().lower()
    for keywords, cats in _INTENT_MAP.items():
        if keywords in lower:
            return list(dict.fromkeys(cats + ["memory"]))
    return _DEFAULT_CATEGORIES


def filter_tools_by_categories(tools_dict: dict, categories: list[str]) -> dict:
    """Return subset of tools whose category is in categories."""
    if not categories or "all" in categories:
        return tools_dict
    cat_set = set(c.lower() for c in categories)
    out = {}
    for name, meta in tools_dict.items():
        tool_cat = (meta.get("category") or "analysis").lower()
        if tool_cat in cat_set:
            out[name] = meta
    return out if out else tools_dict

"""
Intent-based tool filtering.
Map user prompt to allowed tool categories; filter TOOLS before passing to LLM.
"""

# Tool name -> category for routing (aligns with _INTENT_MAP categories)
# Tools not in map use registry entry.get("category") or "general"
_TOOL_CATEGORY_MAP = {
    "read_file": "filesystem", "write_file": "filesystem", "write_files_batch": "filesystem", "list_dir": "filesystem",
    "file_info": "filesystem", "tail_file": "filesystem", "glob_files": "filesystem",
    "understand_file": "filesystem", "extract_archive": "filesystem", "create_archive": "filesystem",
    "grep_code": "code", "run_python": "code", "code_lint": "code", "python_ast": "code",
    "apply_patch": "code",
    "code_metrics": "code", "code_symbols": "code", "code_format": "code", "find_todos": "code",
    "dependency_graph": "code", "security_scan": "code", "run_tests": "code",
    "search_replace": "code", "rename_symbol": "code", "workspace_map": "code",
    "ddg_search": "web", "fetch_article": "web", "wiki_search": "web", "arxiv_search": "web",
    "browser_search": "web", "browser_screenshot": "web", "crawl_site": "web", "check_url": "web",
    "extract_links": "web", "rss_feed": "web",
    "search_memories": "memory", "memory_search": "memory", "memory_get": "memory",
    "save_note": "memory", "memory_stats": "memory",
    "vector_search": "memory", "vector_store": "memory", "spaced_repetition_review": "memory",
    "schedule_learning_review": "memory",
    "list_file_checkpoints": "memory",
    "restore_file_checkpoint": "memory",
    "ingest_chat_export_to_knowledge": "memory",
    "memory_elasticsearch_search": "memory",
    "read_csv": "data", "read_excel": "data", "read_pdf": "data", "read_docx": "data",
    "plot_chart": "data", "plot_scatter": "data", "plot_histogram": "data",
    "sql_query": "data", "schema_introspect": "data", "generate_sql": "data",
    "dataset_summary": "data", "cluster_data": "data", "scipy_compute": "data",
    "write_csv": "data", "json_query": "data", "json_schema": "data",
    "shell": "system", "shell_session_start": "system", "shell_session_manage": "system",
    "schedule_task": "system", "env_info": "system",
    "list_scheduled_tasks": "system", "cancel_task": "system", "disk_usage": "system",
    "process_list": "system", "check_port": "system", "pip_list": "system", "pip_install": "system",
    "send_webhook": "automation", "send_email": "automation", "discord_send": "automation",
    "browser_navigate": "automation", "browser_click": "automation", "browser_fill": "automation",
    "screenshot_desktop": "automation", "click_ui": "automation", "type_text": "automation",
    "structured_llm_task": "analysis",
    "summarize_text": "analysis", "classify_text": "analysis", "nlp_analyze": "analysis",
    "translate_text": "analysis", "extract_entities": "analysis", "sentiment_timeline": "analysis",
    "git_status": "code", "git_diff": "code", "git_log": "code", "git_add": "code",
    "git_commit": "code", "git_push": "code", "git_pull": "code", "git_stash": "code",
    "git_revert": "code", "git_clone": "code", "git_blame": "code",
}

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
    "analyze": ["analysis", "code", "data"],
    "data": ["data", "analysis"],
    "chart": ["data", "analysis"],
    "plot": ["data", "analysis"],
    "csv": ["data"],
    "pandas": ["data"],
    "memory": ["memory"],
    "remember": ["memory"],
    "learned": ["memory"],
    "restore checkpoint": ["memory"],
    "import chat": ["memory"],
    "chat export": ["memory"],
    "elasticsearch": ["memory"],
    "search past learnings": ["memory"],
    "list checkpoint": ["memory"],
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
    # "explain" is ambiguous: it can mean "explain this error/file" (toolable) or
    # "explain your capabilities / explain yourself" (pure chat). Keep it conservative.
    if "explain" in lower:
        meta_self = any(
            k in lower
            for k in (
                "your capabilities",
                "full capabilities",
                "what can you do",
                "who are you",
                "describe yourself",
                "introduce yourself",
                "your tools",
                "what tools do you have",
                "what tools can you use",
                "list your tools",
            )
        )
        code_signals = any(
            k in lower
            for k in (
                "traceback",
                "stack trace",
                "error",
                "exception",
                "line ",
                "file ",
                "repo",
                "workspace",
                "agent/",
            )
        ) or any(ext in lower for ext in (".py", ".ts", ".tsx", ".js", ".json", ".toml", ".yml", ".yaml")) or ("```" in lower) or (
            "/" in lower or "\\" in lower or ":" in lower
        )
        if not meta_self and code_signals:
            return list(dict.fromkeys(["analysis", "code", "filesystem", "web", "memory"]))
    return _DEFAULT_CATEGORIES


def _get_tool_category(name: str, meta: dict | None) -> str:
    """Return category for a tool from map or registry entry."""
    if name in _TOOL_CATEGORY_MAP:
        return _TOOL_CATEGORY_MAP[name]
    if meta:
        return (meta.get("category") or "general").lower()
    return "general"


def filter_tools_by_categories(tools_dict: dict, categories: list[str]) -> dict:
    """Return subset of tools whose category is in categories."""
    if not categories or "all" in categories:
        return tools_dict
    cat_set = set(c.lower() for c in categories)
    out = {}
    for name, meta in tools_dict.items():
        tool_cat = _get_tool_category(name, meta)
        if tool_cat in cat_set:
            out[name] = meta
    return out if out else tools_dict


def get_tool_names_for_goal(goal: str, tools_dict: dict) -> frozenset:
    """
    Return frozenset of tool names for the given goal (intent-based subset).
    Always includes: reason, read_file, list_dir, search_memories, save_note.
    If category filter yields < 10 tools, merges with tool_recommend top 15.
    """
    from layla.tools.registry import tool_recommend
    SAFETY_NET = {"reason", "read_file", "list_dir", "search_memories", "save_note"}
    categories = detect_intent(goal)
    filtered = filter_tools_by_categories(tools_dict, categories)
    names = set(filtered.keys()) | SAFETY_NET
    if len(names) < 10:
        try:
            rec = tool_recommend(goal)
            for rec_item in (rec.get("recommendations") or [])[:15]:
                t = rec_item.get("tool")
                if t and t in tools_dict:
                    names.add(t)
        except Exception:
            pass
    return frozenset(names)

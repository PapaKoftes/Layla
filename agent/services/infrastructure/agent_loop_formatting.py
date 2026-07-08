"""Shared formatting helpers for the agent loop (extracted from agent_loop for testability)."""

from __future__ import annotations

from typing import Any


def format_tool_steps_for_prompt(steps: list, cfg: dict[str, Any] | None = None) -> str:
    """Format tool steps for feeding back into the next iteration or reason prompt."""
    if not steps:
        return ""
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    from services.context.context_manager import truncate_tool_output_for_prompt

    max_tok = int(cfg.get("tool_step_context_max_tokens", 500) or 500)
    if cfg.get("context_aggressive_compress_enabled"):
        max_tok = min(max_tok, 320)

    # A4: content fetched from the network can carry injected instructions. Redact known injection
    # phrases and frame these results as reference data (parity with the document-ingest path)
    # before they flow into the next reasoning prompt — the ingest path did this, the live
    # fetch/crawl path did not.
    _NET_ACTIONS = {
        "fetch_url", "fetch_article", "crawl_site", "web_crawl", "crawl_url", "read_url",
        "browser_navigate", "browser_get_text", "web_search", "search_web",
    }
    _guard = bool(cfg.get("doc_injection_guard_enabled", True))

    lines = []
    for s in steps:
        action = s.get("action", "")
        result = s.get("result", {})
        if isinstance(result, dict):
            summary = result.get("content") or result.get("output") or result.get("matches")
            if summary is None and result.get("entries"):
                summary = str(result["entries"])[:300]
            if summary is None:
                summary = "ok" if result.get("ok") else result.get("error", str(result)[:200])
            if isinstance(summary, (list, dict)):
                summary = str(summary)[:400]
            blob = str(summary)
        else:
            blob = str(result)
        blob = truncate_tool_output_for_prompt(blob, max_tokens=max_tok)
        if _guard and blob and action in _NET_ACTIONS:
            try:
                from services.workspace.doc_ingestion import _apply_injection_guard, _data_framing_prefix
                blob = _data_framing_prefix() + _apply_injection_guard(blob, True)
            except Exception:
                pass
        lines.append(f"{action}: {blob}")
    return "\n".join(lines)

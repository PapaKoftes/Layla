from __future__ import annotations


def test_extract_citations_basic():
    from services.research_report import extract_citations

    state = {
        "cited_knowledge_sources": ["docs/CORE_LOOP.md"],
        "steps": [
            {"tool": "web_search", "result": "See https://example.com/a and https://example.com/b"},
            {"tool": "read_file", "args": {"path": r"C:\Users\me\repo\README.md"}, "result": "ok"},
            {"tool": "http_get", "args": {"url": "https://example.com/c"}},
        ],
    }
    c = extract_citations(state, text_fallback="Also /health endpoint.")
    assert "docs/CORE_LOOP.md" in c["knowledge_sources"]
    assert "https://example.com/a" in c["urls"]
    assert r"C:\Users\me\repo\README.md" in c["file_paths"]
    assert "/health" in c["api_endpoints"]


def test_format_research_report_contains_headers():
    from services.research_report import format_research_report

    md = format_research_report(
        "Findings here.",
        tool_steps=[{"tool": "read_file"}],
        template_type="technical_report",
        title="X",
        citations={"knowledge_sources": ["k1"], "urls": ["https://x"], "file_paths": ["a/b"], "api_endpoints": ["/agent"]},
    )
    assert md.startswith("# X")
    assert "## Summary" in md
    assert "## Citations" in md


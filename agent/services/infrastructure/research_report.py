from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_URL_RE = re.compile(r"https?://[^\s\)\]]+")
_WIN_PATH_RE = re.compile(r"\b[a-zA-Z]:\\\\[^\s\)\]]+")
_POSIX_PATH_RE = re.compile(r"(?<![\w/])/(?:[\w\-. ]+/)*[\w\-. ]+\b")
_API_RE = re.compile(r"(?<![\w/])/[a-zA-Z0-9][a-zA-Z0-9_\-\/]{0,80}")


def _uniq(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in seq:
        ss = (s or "").strip()
        if not ss or ss in seen:
            continue
        seen.add(ss)
        out.append(ss)
    return out


def extract_citations(state: dict[str, Any] | None = None, *, text_fallback: str = "") -> dict[str, list[str]]:
    """
    Deterministic citation extraction for research outputs.
    Walks known state fields + tool steps; falls back to regex over text.
    """
    state = state or {}
    steps = state.get("steps") or []
    cited = state.get("cited_knowledge_sources") or []

    urls: list[str] = []
    file_paths: list[str] = []
    api_endpoints: list[str] = []
    knowledge_sources: list[str] = []

    if isinstance(cited, list):
        for x in cited:
            s = str(x).strip()
            if s:
                knowledge_sources.append(s)

    def _scan_obj(obj: Any) -> None:
        try:
            if obj is None:
                return
            if isinstance(obj, str):
                urls.extend(_URL_RE.findall(obj))
                file_paths.extend(_WIN_PATH_RE.findall(obj))
                file_paths.extend(_POSIX_PATH_RE.findall(obj))
                api_endpoints.extend(_API_RE.findall(obj))
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if str(k).lower() in ("path", "file", "filepath", "file_path"):
                        s = str(v).strip()
                        if s:
                            file_paths.append(s)
                    _scan_obj(v)
                return
            if isinstance(obj, (list, tuple)):
                for it in obj:
                    _scan_obj(it)
        except Exception:
            return

    if isinstance(steps, list):
        for st in steps:
            if not isinstance(st, dict):
                continue
            _scan_obj(st.get("tool"))
            _scan_obj(st.get("name"))
            _scan_obj(st.get("args"))
            _scan_obj(st.get("result"))
            _scan_obj(st.get("output"))

    if text_fallback:
        _scan_obj(text_fallback)

    return {
        "knowledge_sources": _uniq(knowledge_sources)[:50],
        "urls": _uniq(urls)[:80],
        "file_paths": _uniq(file_paths)[:80],
        "api_endpoints": _uniq(api_endpoints)[:40],
    }


def format_research_report(
    raw_output: str,
    tool_steps: list[dict[str, Any]] | None,
    template_type: str,
    title: str,
    citations: dict[str, list[str]] | None,
) -> str:
    raw_output = (raw_output or "").strip()
    template = (template_type or "technical_report").strip().lower()
    title = (title or "Research report").strip()
    citations = citations or {"knowledge_sources": [], "urls": [], "file_paths": [], "api_endpoints": []}

    steps = tool_steps or []
    tool_count = len([s for s in steps if isinstance(s, dict) and (s.get("tool") or s.get("name"))])

    def _cit_md() -> str:
        ks = citations.get("knowledge_sources") or []
        urls = citations.get("urls") or []
        fps = citations.get("file_paths") or []
        apis = citations.get("api_endpoints") or []
        lines: list[str] = []
        if ks:
            lines.append("### Knowledge sources")
            lines.extend([f"- {k}" for k in ks[:30]])
            lines.append("")
        if fps:
            lines.append("### Files referenced")
            lines.extend([f"- `{p}`" for p in fps[:30]])
            lines.append("")
        if apis:
            lines.append("### API endpoints referenced")
            lines.extend([f"- `{p}`" for p in apis[:30]])
            lines.append("")
        if urls:
            lines.append("### URLs")
            lines.extend([f"- {u}" for u in urls[:40]])
            lines.append("")
        return "\n".join(lines).strip()

    citations_md = _cit_md()

    if template in ("briefing", "brief"):
        return (
            f"# {title}\n\n"
            f"## Executive briefing\n"
            f"{raw_output or '(no output)'}\n\n"
            f"## Method\n"
            f"- Tool steps observed: {tool_count}\n\n"
            f"## Citations\n"
            f"{citations_md or '(none)'}\n"
        ).strip() + "\n"

    if template in ("comparison_report", "compare"):
        return (
            f"# {title}\n\n"
            f"## Comparison\n"
            f"{raw_output or '(no output)'}\n\n"
            f"## Criteria & trade-offs\n"
            f"- Performance\n- Correctness\n- Maintainability\n- Security\n- UX\n\n"
            f"## Recommendation\n"
            f"- (Operator decision)\n\n"
            f"## Citations\n"
            f"{citations_md or '(none)'}\n"
        ).strip() + "\n"

    # default: technical_report
    return (
        f"# {title}\n\n"
        f"## Summary\n"
        f"{raw_output or '(no output)'}\n\n"
        f"## Evidence & trace\n"
        f"- Tool steps observed: {tool_count}\n\n"
        f"## Recommendations\n"
        f"- (Actionable next steps)\n\n"
        f"## Citations\n"
        f"{citations_md or '(none)'}\n"
    ).strip() + "\n"


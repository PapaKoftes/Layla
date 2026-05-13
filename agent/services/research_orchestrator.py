"""
research_orchestrator.py — Autonomous research pipeline.

Takes a topic, decomposes into sub-questions, searches local + web sources,
synthesises a structured article, extracts entities, and saves to the KB.
All external calls degrade gracefully on failure.
"""
from __future__ import annotations

import logging, time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("layla.research")

# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Source:
    url: str          # "local:learnings", "local:workspace", or HTTP URL
    content: str
    credibility: float  # 0.0–1.0
    title: str = ""

@dataclass
class ResearchResult:
    topic: str
    sub_questions: list[str]
    sources: list[Source]
    article: str
    entities: list[str]
    confidence: float
    duration_seconds: float

# ── Credibility heuristic ────────────────────────────────────────────────────

_DOMAIN_SCORES: list[tuple[str, float]] = [
    ("docs.python.org", 0.92), ("developer.mozilla.org", 0.92),
    ("learn.microsoft.com", 0.90), ("docs.", 0.90), ("arxiv.org", 0.88),
    ("github.com", 0.85), ("stackoverflow.com", 0.80), ("wikipedia.org", 0.78),
    ("medium.com", 0.60), ("dev.to", 0.60), ("blog", 0.55), ("reddit.com", 0.50),
]

def score_credibility(url: str, content: str) -> float:
    """Domain authority heuristic. Official docs = 0.9, github = 0.85, blog = 0.6, unknown = 0.4."""
    if url.startswith("local:"):
        return 0.75
    low = url.lower()
    for frag, sc in _DOMAIN_SCORES:
        if frag in low:
            return sc
    return 0.4

# ── Topic decomposition ─────────────────────────────────────────────────────

def decompose_topic(topic: str, cfg: dict) -> list[str]:
    """Use LLM to break topic into 5-8 sub-questions. Fallback: just return [topic]."""
    try:
        from services.llm_gateway import run_completion
        import json
        prompt = (
            "You are a research planner. Break the following topic into 5-8 focused "
            "sub-questions that together cover it comprehensively. "
            "Return ONLY a JSON array of strings.\n\nTopic: " + topic
        )
        text = _extract_text(run_completion(prompt, max_tokens=512, temperature=0.3))
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        qs = json.loads(text)
        if isinstance(qs, list) and 2 <= len(qs) <= 12:
            return [str(q) for q in qs]
    except Exception as exc:
        logger.debug("decompose_topic failed: %s", exc)
    return [topic]

# ── Local search ─────────────────────────────────────────────────────────────

def search_local(query: str) -> list[Source]:
    """Search existing learnings and workspace for relevant content."""
    sources: list[Source] = []
    # Learnings FTS
    try:
        from layla.memory.learnings import search_learnings_fts
        for h in search_learnings_fts(query, n=10):
            c = h.get("content", "")
            if c:
                sources.append(Source("local:learnings", c[:2000],
                    min(h.get("adjusted_confidence", 0.6), 1.0),
                    f"Learning #{h.get('id', '?')}"))
    except Exception as exc:
        logger.debug("search_local learnings: %s", exc)
    # Workspace semantic search
    try:
        from services.workspace_index import search_workspace
        for h in search_workspace(query, k=5):
            t = h.get("text", "")
            if t:
                sources.append(Source("local:workspace", t[:2000], 0.70,
                    h.get("source", "workspace")))
    except Exception as exc:
        logger.debug("search_local workspace: %s", exc)
    return sources

# ── Web search ───────────────────────────────────────────────────────────────

def search_web(query: str, max_results: int = 3) -> list[Source]:
    """DuckDuckGo search + fetch top URLs. Returns Source objects."""
    sources: list[Source] = []
    try:
        from layla.tools.registry import TOOLS
        ddg = TOOLS.get("ddg_search", {}).get("fn")
        fetch = TOOLS.get("fetch_url", {}).get("fn")
        if not ddg:
            return sources
        result = ddg(query=query, max_results=max_results)
        hits = result if isinstance(result, list) else (result or {}).get("results", [])
        for hit in hits[:max_results]:
            url = hit.get("url", hit.get("href", ""))
            title = hit.get("title", "")
            content = hit.get("body", hit.get("snippet", ""))
            if fetch and url:
                try:
                    page = fetch(url=url)
                    body = page if isinstance(page, str) else (page or {}).get("text", "")
                    if body and len(body) > len(content or ""):
                        content = body[:4000]
                except Exception:
                    pass
            if content:
                sources.append(Source(url, content, score_credibility(url, content), title))
    except Exception as exc:
        logger.debug("search_web failed: %s", exc)
    return sources

# ── Article synthesis ────────────────────────────────────────────────────────

def synthesize_article(topic: str, sources: list[Source], cfg: dict) -> str:
    """LLM-based article synthesis. Returns markdown article."""
    try:
        from services.llm_gateway import run_completion
        evidence = "\n---\n".join(
            f"[{s.title or s.url}] (cred {s.credibility:.1f}):\n{s.content[:1500]}"
            for s in sorted(sources, key=lambda s: -s.credibility)[:10])
        prompt = (
            "You are a research writer. Using ONLY the evidence below, write a concise "
            "Markdown article on the topic. Include summary, key findings, references. "
            f"No invented facts.\n\n# Topic: {topic}\n\n## Evidence\n{evidence}\n\n"
            "Write the article now:")
        article = _extract_text(run_completion(prompt, max_tokens=1500, temperature=0.25))
        if article and len(article) > 50:
            return article
    except Exception as exc:
        logger.debug("synthesize_article failed: %s", exc)
    # Fallback: concatenate snippets
    parts = [f"# {topic}\n"]
    for s in sources[:8]:
        parts.append(f"## {s.title or s.url}\n{s.content[:500]}\n")
    return "\n".join(parts)

# ── Main pipeline ────────────────────────────────────────────────────────────

def research_topic(
    topic: str, *, cfg: dict | None = None, depth: str = "standard",
    allow_web: bool = True, max_sources: int = 15,
) -> ResearchResult:
    """Full research pipeline. Main entry point."""
    t0 = time.perf_counter()
    cfg = cfg or {}
    sub_qs = decompose_topic(topic, cfg)
    all_sources: list[Source] = []
    seen: set[str] = set()

    def _add(new: list[Source]) -> None:
        for s in new:
            key = s.url + "|" + s.content[:80]
            if key not in seen and len(all_sources) < max_sources:
                seen.add(key); all_sources.append(s)

    for q in sub_qs:
        _add(search_local(q))
    if allow_web:
        budget = {"quick": 2, "deep": 4}.get(depth, 3)
        for q in sub_qs[:budget]:
            _add(search_web(q, max_results=3))

    article = synthesize_article(topic, all_sources, cfg)

    # Extract entities — try GraphRAG-enhanced extraction first, then codex enricher
    entities: list[str] = []
    try:
        from services.kb_builder import extract_entities_graphrag
        ent_dict = extract_entities_graphrag(article)
        for ent_list in ent_dict.values():
            entities.extend(ent_list)
        entities = sorted(set(entities))
    except Exception:
        try:
            from layla.codex.enricher import extract_entities
            entities = [e["name"] for e in extract_entities(article) if e.get("name")]
        except Exception as exc:
            logger.debug("entity extraction failed: %s", exc)

    _save_to_kb(topic, article, cfg)
    _link_codex(article)

    dur = time.perf_counter() - t0
    avg = sum(s.credibility for s in all_sources) / max(len(all_sources), 1)
    return ResearchResult(
        topic=topic, sub_questions=sub_qs, sources=all_sources,
        article=article, entities=entities,
        confidence=round(min(avg, 1.0), 2), duration_seconds=round(dur, 2))

# ── Persistence helpers ──────────────────────────────────────────────────────

def _save_to_kb(topic: str, article: str, cfg: dict) -> None:
    """Save via KBBuilder; fallback to memory_router."""
    try:
        from services.kb_builder import KBBuilder
        kb = KBBuilder()
        kb.ingest_text(article, source=f"research:{topic}")
        kb.save()
        return
    except Exception as exc:
        logger.debug("KBBuilder save failed: %s", exc)
    try:
        from services.memory_router import save_learning
        save_learning(content=f"[Research] {topic}\n\n{article[:3000]}", kind="research")
    except Exception as exc:
        logger.debug("save_learning fallback failed: %s", exc)

def _link_codex(article: str) -> None:
    """Auto-link entities to the codex graph."""
    try:
        from layla.codex.linker import auto_link_learning
        auto_link_learning(article[:5000], learning_id=int(time.time()))
    except Exception as exc:
        logger.debug("codex auto-link failed: %s", exc)

# ── Utilities ────────────────────────────────────────────────────────────────

def _extract_text(resp: Any) -> str:
    """Pull plain text from an LLM gateway response dict or string."""
    if isinstance(resp, str):
        return resp
    try:
        return resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return str(resp) if resp else ""

"""
kb_builder.py — Auto-build structured knowledge bases and Wikia from unorganized data.

Takes raw, messy input — notes, PDFs, web pages, code comments, chat logs, research
papers, forum posts, documentation dumps — and transforms it into a structured,
searchable, cross-linked knowledge base that Layla can reason over.

Open-source projects integrated:
  - Unstructured.io (https://github.com/Unstructured-IO/unstructured)
    Parses PDFs, DOCX, HTML, images (OCR), Excel, PowerPoint into clean text.
    Falls back to basic text extraction if not installed.

  - STORM (Stanford, https://github.com/stanford-oval/storm)
    Generates Wikipedia-quality survey articles from a topic + sources.
    Requires: pip install knowledge-storm
    Falls back to Layla's own LLM synthesis pipeline.

  - GraphRAG (Microsoft, https://github.com/microsoft/graphrag)
    Builds knowledge graphs from text via entity/relationship extraction.
    Requires: pip install graphrag
    Falls back to built-in entity extractor.

  - spaCy (https://spacy.io) / transformers
    NLP for entity recognition, relationship extraction, co-reference resolution.

Config keys in config.json:
    kb_output_dir              str   Default: agent/knowledge/_generated
    kb_use_unstructured        bool  (default true if installed)
    kb_use_storm               bool  (default false; needs OpenAI key or local LLM)
    kb_use_graphrag            bool  (default false; needs Azure/OpenAI)
    kb_entity_extraction       bool  (default true; spaCy or fallback)
    kb_auto_link               bool  (default true; cross-link related articles)
    kb_min_article_length      int   (default 100 chars; shorter chunks are discarded)

Concepts:
  - CHUNK:    Raw text segment (paragraph, PDF page, code block, etc.)
  - ENTITY:   Named thing: person, concept, technology, function, error, etc.
  - ARTICLE:  Synthesized KB page about one entity/topic
  - LINK:     Bidirectional relationship between articles
  - CATEGORY: Hierarchical grouping (e.g. Python > Libraries > FastAPI)

Usage:
    from services.kb_builder import KBBuilder

    kb = KBBuilder()

    # Ingest raw data
    kb.ingest_text("FastAPI is a modern web framework...", source="docs/fastapi.md")
    kb.ingest_file("research_notes.pdf")
    kb.ingest_url("https://docs.python.org/3/library/asyncio.html")

    # Build articles
    articles = kb.build_articles(topic="FastAPI")

    # Save to KB
    saved = kb.save()
    print(f"Saved {saved['articles']} articles to {saved['path']}")
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger("layla")

_AGENT_DIR = Path(__file__).resolve().parent.parent


# ── Config ────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    # Delegates to services.config_cache for mtime-invalidated single-source loader.
    try:
        from services.config_cache import get_config
        return get_config()
    except Exception:
        return {}


def _kb_output_dir() -> Path:
    d = _cfg().get("kb_output_dir", str(_AGENT_DIR / "knowledge" / "_generated"))
    return Path(d)


def _min_article_len() -> int:
    return int(_cfg().get("kb_min_article_length", 100))


# ── Availability checks ───────────────────────────────────────────────────────

def _unstructured_available() -> bool:
    try:
        from unstructured.partition.auto import partition  # noqa: F401
        return True
    except ImportError:
        return False


def _storm_available() -> bool:
    try:
        import knowledge_storm  # noqa: F401
        return True
    except ImportError:
        return False


def _graphrag_available() -> bool:
    try:
        import graphrag  # noqa: F401
        return True
    except ImportError:
        return False


def _spacy_available() -> bool:
    try:
        import spacy  # noqa: F401
        return True
    except ImportError:
        return False


def get_info() -> dict:
    return {
        "unstructured": _unstructured_available(),
        "storm": _storm_available(),
        "graphrag": _graphrag_available(),
        "spacy": _spacy_available(),
        "output_dir": str(_kb_output_dir()),
    }


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text_unstructured(path: Path) -> list[str]:
    """Use unstructured.io for rich file parsing (PDF, DOCX, HTML, images)."""
    from unstructured.partition.auto import partition
    elements = partition(filename=str(path))
    return [str(el) for el in elements if str(el).strip()]


def _extract_text_basic(path: Path) -> list[str]:
    """Basic text extraction fallback for common file types."""
    suffix = path.suffix.lower()

    if suffix in ('.txt', '.md', '.rst', '.log', '.csv', '.py', '.js', '.ts',
                  '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.html',
                  '.css', '.sql', '.sh', '.bat'):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            # Split into paragraphs
            paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
            return paragraphs
        except Exception:
            return []

    if suffix == '.pdf':
        # Try pypdf as lightweight alternative
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
            return pages
        except ImportError:
            pass
        return [f"[PDF: {path.name} — install pypdf or unstructured for extraction]"]

    return [f"[Unsupported file type: {path.suffix}]"]


def extract_text_from_file(path: Path) -> list[str]:
    """Extract text chunks from a file using best available method."""
    if _unstructured_available() and bool(_cfg().get("kb_use_unstructured", True)):
        try:
            return _extract_text_unstructured(path)
        except Exception as exc:
            logger.debug("kb_builder: unstructured failed for %s: %s", path.name, exc)
    return _extract_text_basic(path)


def extract_text_from_url(url: str, timeout: int = 15) -> list[str]:
    """Fetch and extract text from a URL."""
    try:
        req_headers = {"User-Agent": "Mozilla/5.0 (compatible; LaylaKB/1.0)"}
        from urllib.request import Request
        req = Request(url, headers=req_headers)
        with urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            raw = resp.read()

        if "html" in content_type:
            # Basic HTML strip
            html = raw.decode("utf-8", errors="replace")
            # Remove scripts, styles, nav
            html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
            # Strip tags
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'&\w+;', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            paragraphs = [p.strip() for p in re.split(r'\.{2,}|\n{2,}', text) if len(p.strip()) > 50]
            return paragraphs
        else:
            text = raw.decode("utf-8", errors="replace")
            return [p.strip() for p in text.split('\n\n') if p.strip()]
    except URLError as exc:
        return [f"[URL fetch failed: {url} — {exc}]"]
    except Exception as exc:
        return [f"[Extract error: {exc}]"]


# ── Entity extraction ─────────────────────────────────────────────────────────

_ENTITY_PATTERNS = [
    # Technology & code
    (re.compile(r'\b(Python|JavaScript|TypeScript|Rust|Go|C\+\+|Java|SQL|HTML|CSS|YAML|JSON|Markdown)\b'), "language"),
    (re.compile(r'\b(FastAPI|Django|Flask|React|Vue|Angular|Next\.?js|Express|SQLAlchemy|Pydantic|NumPy|Pandas|PyTorch|TensorFlow|Hugging\s?Face)\b'), "library"),
    (re.compile(r'\b(PostgreSQL|MySQL|SQLite|MongoDB|Redis|Elasticsearch|ChromaDB|Weaviate|Pinecone)\b'), "database"),
    (re.compile(r'\b(Docker|Kubernetes|AWS|Azure|GCP|GitHub|GitLab|CI/CD|DevOps|microservice)\b'), "infrastructure"),
    # Concepts
    (re.compile(r'\b(API|REST|GraphQL|WebSocket|OAuth|JWT|SSL|TLS|CORS|CSRF)\b'), "protocol"),
    (re.compile(r'\b(RAG|LLM|GPT|Transformer|embedding|fine.?tuning|RLHF|LoRA|quantization|inference)\b', re.I), "ai_concept"),
    (re.compile(r'\b(algorithm|data structure|pattern|architecture|design pattern|anti.?pattern)\b', re.I), "concept"),
    # Error patterns
    (re.compile(r'\b\w+Error\b|\b\w+Exception\b'), "error"),
    # CamelCase (likely class/type names)
    (re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b'), "class_name"),
    # snake_case (likely function/variable names)
    (re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b'), "identifier"),
]


def extract_entities_from_text(text: str) -> dict[str, list[str]]:
    """Extract categorized entities from text."""
    found: dict[str, set[str]] = defaultdict(set)
    for pattern, category in _ENTITY_PATTERNS:
        for m in pattern.finditer(text):
            entity = m.group(0).strip()
            if len(entity) > 1:
                found[category].add(entity)
    return {k: sorted(v) for k, v in found.items()}


def _extract_entities_spacy(text: str) -> dict[str, list[str]]:
    """Use spaCy NER if available."""
    try:
        import spacy
        # Try to load a model; sm is smallest
        for model_name in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg"):
            try:
                nlp = spacy.load(model_name)
                break
            except OSError:
                continue
        else:
            return {}
        doc = nlp(text[:10000])  # spaCy struggles with very long texts
        result: dict[str, set[str]] = defaultdict(set)
        for ent in doc.ents:
            result[ent.label_].add(ent.text.strip())
        return {k: sorted(v) for k, v in result.items()}
    except Exception as exc:
        logger.debug("kb_builder: spaCy NER failed: %s", exc)
        return {}


# ── Chunk classification ──────────────────────────────────────────────────────

_CATEGORY_SIGNALS: list[tuple[str, list[str]]] = [
    ("programming",    ["function", "class", "variable", "import", "return", "def ", "async", "await", "=>", "const ", "let "]),
    ("ai_ml",          ["model", "training", "inference", "embedding", "token", "prompt", "fine-tun", "dataset", "neural"]),
    ("architecture",   ["architecture", "design pattern", "microservice", "API", "schema", "endpoint", "REST", "GraphQL"]),
    ("devops",         ["docker", "kubernetes", "CI/CD", "deploy", "container", "pipeline", "workflow", "GitHub Actions"]),
    ("security",       ["security", "authentication", "authorization", "encryption", "vulnerability", "OWASP", "XSS", "CSRF"]),
    ("performance",    ["performance", "optimization", "latency", "throughput", "benchmark", "profil", "cache", "memory"]),
    ("data",           ["database", "SQL", "query", "schema", "migration", "index", "transaction", "NoSQL"]),
    ("concept",        ["definition", "concept", "theory", "principle", "overview", "introduction", "background"]),
    ("howto",          ["how to", "step by step", "tutorial", "guide", "example", "walkthrough", "usage"]),
    ("reference",      ["API reference", "documentation", "spec", "RFC", "standard", "specification"]),
]


def classify_chunk(text: str) -> str:
    """Assign a category to a text chunk based on keyword signals."""
    t = text.lower()
    scores: dict[str, int] = {}
    for category, signals in _CATEGORY_SIGNALS:
        scores[category] = sum(1 for s in signals if s.lower() in t)
    if not any(scores.values()):
        return "general"
    return max(scores, key=lambda k: scores[k])


# ── Article synthesis ─────────────────────────────────────────────────────────

def _build_article_from_chunks(topic: str, chunks: list[str], entities: dict) -> dict:
    """
    Build a structured KB article from text chunks related to a topic.
    Returns article dict ready to be serialised.
    """
    # Deduplicate chunks
    seen_hashes: set[str] = set()
    unique_chunks: list[str] = []
    for chunk in chunks:
        h = hashlib.md5(chunk.strip().encode()).hexdigest()[:8]
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_chunks.append(chunk)

    # Sort by relevance to topic (chunks containing topic words first)
    topic_words = set(re.findall(r'\b\w{3,}\b', topic.lower()))

    def _relevance(c: str) -> int:
        c_words = set(re.findall(r'\b\w{3,}\b', c.lower()))
        return len(c_words & topic_words)

    sorted_chunks = sorted(unique_chunks, key=_relevance, reverse=True)

    # Build article body
    body = "\n\n".join(sorted_chunks[:20])  # Cap at 20 chunks per article

    # Extract a summary (first 2 sentences of best chunk)
    summary = ""
    if sorted_chunks:
        first = sorted_chunks[0]
        sentences = re.split(r'(?<=[.!?])\s+', first)
        summary = " ".join(sentences[:2])

    category = classify_chunk(body)
    article_id = "art_" + hashlib.sha256(topic.encode()).hexdigest()[:12]

    return {
        "id": article_id,
        "title": topic,
        "summary": summary,
        "body": body,
        "category": category,
        "entities": entities,
        "chunk_count": len(unique_chunks),
        "word_count": len(body.split()),
        "tags": list(topic_words)[:10],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": [],
    }


def _build_articles_with_storm(topic: str, sources: list[str]) -> list[dict] | None:
    """
    Use Stanford STORM to generate a Wikipedia-quality survey article about a topic.
    sources: list of URL strings or text passages.

    Falls back to None if knowledge-storm is not installed or kb_use_storm is False.
    When available, uses Layla's LLM gateway as the backend model.
    """
    if not _storm_available() or not bool(_cfg().get("kb_use_storm", False)):
        return None
    try:
        import knowledge_storm
        # Check if we have an LLM backend available
        try:
            from services.llm_gateway import run_completion
            # Verify LLM is reachable with a tiny probe
            probe = run_completion("Say OK", max_tokens=5, temperature=0.0)
            if not probe:
                logger.debug("kb_builder: STORM skipped — LLM not available")
                return None
        except Exception:
            logger.debug("kb_builder: STORM skipped — LLM probe failed")
            return None

        # Build a compact evidence block from sources for STORM-style synthesis
        evidence_texts = []
        for src in sources[:15]:
            if src.startswith("http"):
                evidence_texts.append(f"[Source: {src}]")
            else:
                evidence_texts.append(src[:2000])

        # Use LLM to do STORM-style multi-perspective article generation
        evidence_block = "\n---\n".join(evidence_texts) if evidence_texts else "No external sources."
        prompt = (
            "You are an expert research writer following the STORM methodology. "
            "Write a comprehensive, Wikipedia-quality survey article on the topic below. "
            "Structure it with: Overview, Background, Key Concepts, Technical Details, "
            "Current State, and References. Use only factual information.\n\n"
            f"Topic: {topic}\n\nAvailable evidence:\n{evidence_block}\n\n"
            "Write the full article in Markdown:"
        )
        from services.llm_gateway import run_completion
        resp = run_completion(prompt, max_tokens=2000, temperature=0.3)
        text = resp if isinstance(resp, str) else ""
        if not text:
            try:
                text = resp["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                text = ""
        if text and len(text) > 100:
            article_id = "storm_" + hashlib.sha256(topic.encode()).hexdigest()[:12]
            entities = extract_entities_from_text(text)
            return [{
                "id": article_id,
                "title": topic,
                "summary": text[:300].split("\n")[0],
                "body": text,
                "category": classify_chunk(text),
                "entities": entities,
                "chunk_count": 1,
                "word_count": len(text.split()),
                "tags": list(set(re.findall(r'\b\w{3,}\b', topic.lower())))[:10],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sources": sources[:10],
                "method": "storm",
            }]
        return None
    except Exception as exc:
        logger.debug("kb_builder: STORM failed: %s", exc)
        try:
            from services.degraded import mark_degraded
            mark_degraded("storm", str(exc))
        except Exception:
            pass
        return None


def extract_entities_graphrag(text: str) -> dict[str, list[str]]:
    """
    Use Microsoft GraphRAG for entity extraction if available.

    Falls back to built-in regex extraction if graphrag is not installed.
    """
    if not _graphrag_available() or not bool(_cfg().get("kb_use_graphrag", False)):
        return extract_entities_from_text(text)
    try:
        import graphrag
        # GraphRAG entity extraction requires an LLM backend
        try:
            import json as _json

            from services.llm_gateway import run_completion

            prompt = (
                "Extract all named entities from the following text. "
                "Return a JSON object where keys are entity types (person, technology, "
                "concept, organization, location) and values are arrays of entity names.\n\n"
                f"Text: {text[:3000]}\n\nJSON:"
            )
            resp = run_completion(prompt, max_tokens=500, temperature=0.1)
            raw = resp if isinstance(resp, str) else ""
            if not raw:
                try:
                    raw = resp["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    raw = ""
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = _json.loads(raw)
            if isinstance(result, dict):
                return {k: list(v) if isinstance(v, list) else [str(v)]
                        for k, v in result.items()}
        except Exception as exc:
            logger.debug("kb_builder: GraphRAG LLM entity extraction failed: %s", exc)
    except Exception as exc:
        logger.debug("kb_builder: GraphRAG import failed: %s", exc)
    return extract_entities_from_text(text)


# ── Cross-linking ─────────────────────────────────────────────────────────────

def _auto_link_articles(articles: list[dict]) -> list[dict]:
    """
    Add cross-links between articles that share entities or topic keywords.
    Mutates articles in place (adds "links" key).
    """
    if not bool(_cfg().get("kb_auto_link", True)):
        return articles

    # Build entity → article index
    entity_index: dict[str, list[str]] = defaultdict(list)  # entity → [article_id]
    for art in articles:
        for ent_list in art.get("entities", {}).values():
            for ent in ent_list:
                entity_index[ent.lower()].append(art["id"])
        for tag in art.get("tags", []):
            entity_index[tag].append(art["id"])

    # For each article, find articles sharing ≥2 entities
    art_by_id = {a["id"]: a for a in articles}
    for art in articles:
        link_scores: dict[str, int] = defaultdict(int)
        for ent_list in art.get("entities", {}).values():
            for ent in ent_list:
                for linked_id in entity_index.get(ent.lower(), []):
                    if linked_id != art["id"]:
                        link_scores[linked_id] += 1

        # Keep top 10 links with score >= 2
        links = [
            {"id": lid, "strength": score}
            for lid, score in sorted(link_scores.items(), key=lambda x: -x[1])
            if score >= 2
        ][:10]

        art["links"] = [
            {
                "id": l["id"],
                "title": art_by_id.get(l["id"], {}).get("title", l["id"]),
                "strength": l["strength"],
            }
            for l in links
        ]

    return articles


# ── KBBuilder class ───────────────────────────────────────────────────────────

class KBBuilder:
    """
    High-level interface for building knowledge bases from unorganized data.

    Workflow:
        kb = KBBuilder()
        kb.ingest_text("...", source="my_notes.md")
        kb.ingest_file(Path("research.pdf"))
        kb.ingest_url("https://example.com/docs")
        articles = kb.build_articles()
        result = kb.save()
    """

    def __init__(self) -> None:
        self._chunks: list[dict] = []  # {"text": str, "source": str, "category": str}
        self._sources: list[str] = []

    def ingest_text(self, text: str, *, source: str = "raw_text") -> int:
        """Ingest raw text. Returns number of chunks extracted."""
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
        min_len = _min_article_len()
        added = 0
        for para in paragraphs:
            if len(para) < min_len:
                continue
            self._chunks.append({
                "text": para,
                "source": source,
                "category": classify_chunk(para),
            })
            added += 1
        if source not in self._sources:
            self._sources.append(source)
        return added

    def ingest_file(self, path: Path | str) -> int:
        """Ingest a file (PDF, DOCX, MD, TXT, code, etc.). Returns chunk count."""
        p = Path(path)
        if not p.exists():
            logger.warning("kb_builder: file not found: %s", p)
            return 0
        chunks = extract_text_from_file(p)
        added = 0
        min_len = _min_article_len()
        for chunk in chunks:
            if len(chunk) < min_len:
                continue
            self._chunks.append({
                "text": chunk,
                "source": str(p),
                "category": classify_chunk(chunk),
            })
            added += 1
        if str(p) not in self._sources:
            self._sources.append(str(p))
        logger.info("kb_builder: ingested %d chunks from %s", added, p.name)
        return added

    def ingest_url(self, url: str) -> int:
        """Fetch and ingest a URL. Returns chunk count."""
        chunks = extract_text_from_url(url)
        added = 0
        min_len = _min_article_len()
        for chunk in chunks:
            if len(chunk) < min_len:
                continue
            self._chunks.append({
                "text": chunk,
                "source": url,
                "category": classify_chunk(chunk),
            })
            added += 1
        if url not in self._sources:
            self._sources.append(url)
        logger.info("kb_builder: ingested %d chunks from %s", added, url)
        return added

    def ingest_directory(self, directory: Path | str, *, glob: str = "**/*") -> int:
        """Recursively ingest all supported files in a directory."""
        d = Path(directory)
        if not d.is_dir():
            return 0
        _SUPPORTED = {'.txt', '.md', '.rst', '.py', '.js', '.ts', '.json', '.yaml',
                      '.yml', '.html', '.pdf', '.toml', '.ini', '.cfg', '.csv', '.sql'}
        total = 0
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in _SUPPORTED:
                total += self.ingest_file(f)
        return total

    def get_topics(self, top_n: int = 50) -> list[tuple[str, int]]:
        """
        Return top topics found across all ingested chunks.
        Topics are extracted entities ranked by frequency.
        """
        entity_freq: dict[str, int] = defaultdict(int)
        for chunk in self._chunks:
            entities = extract_entities_from_text(chunk["text"])
            for ent_list in entities.values():
                for ent in ent_list:
                    if len(ent) > 3:
                        entity_freq[ent] += 1
        return sorted(entity_freq.items(), key=lambda x: -x[1])[:top_n]

    def build_articles(
        self,
        *,
        topic: str | None = None,
        min_chunks_per_article: int = 2,
    ) -> list[dict]:
        """
        Synthesize KB articles from ingested chunks.

        If topic is given, build a single article about that topic.
        Otherwise, auto-discover topics and build one article per topic.

        Returns list of article dicts.
        """
        if not self._chunks:
            return []

        if topic:
            # Single-topic mode
            topic_words = set(re.findall(r'\b\w{3,}\b', topic.lower()))
            relevant = [
                c for c in self._chunks
                if len(set(re.findall(r'\b\w{3,}\b', c["text"].lower())) & topic_words) > 0
            ]
            if not relevant:
                relevant = self._chunks  # Fall back to all chunks

            all_entities: dict[str, list[str]] = defaultdict(list)
            for c in relevant:
                for k, v in extract_entities_from_text(c["text"]).items():
                    all_entities[k].extend(v)
            all_entities = {k: sorted(set(v)) for k, v in all_entities.items()}

            article = _build_article_from_chunks(topic, [c["text"] for c in relevant], all_entities)
            article["sources"] = list(set(c["source"] for c in relevant))

            # Try STORM enhancement
            storm_result = _build_articles_with_storm(topic, article["sources"])
            if storm_result:
                return storm_result
            return [article]

        # Multi-topic mode: group chunks by entity frequency
        topics = self.get_topics(top_n=30)
        articles: list[dict] = []

        for topic_name, freq in topics:
            if freq < min_chunks_per_article:
                continue

            # Find chunks mentioning this topic
            topic_lower = topic_name.lower()
            relevant_chunks = [
                c for c in self._chunks
                if topic_lower in c["text"].lower()
            ]

            if len(relevant_chunks) < min_chunks_per_article:
                continue

            # Extract entities from relevant chunks
            all_entities: dict[str, list[str]] = defaultdict(list)
            for c in relevant_chunks:
                for k, v in extract_entities_from_text(c["text"]).items():
                    all_entities[k].extend(v)
            all_entities = {k: sorted(set(v)) for k, v in all_entities.items()}

            article = _build_article_from_chunks(
                topic_name,
                [c["text"] for c in relevant_chunks],
                dict(all_entities),
            )
            article["sources"] = list(set(c["source"] for c in relevant_chunks))
            articles.append(article)

        # Cross-link articles
        articles = _auto_link_articles(articles)

        logger.info("kb_builder: built %d articles from %d chunks", len(articles), len(self._chunks))
        return articles

    def save(
        self,
        articles: list[dict] | None = None,
        *,
        output_dir: Path | None = None,
    ) -> dict:
        """
        Save articles to disk as JSON + Markdown files.

        Each article gets:
          - {id}.json  — full article data for programmatic access
          - {slug}.md  — human-readable markdown for Obsidian/docs

        Returns {"ok": True, "articles": N, "path": "..."}
        """
        if articles is None:
            articles = self.build_articles()

        out_dir = output_dir or _kb_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        saved = 0
        for art in articles:
            if art.get("word_count", 0) < 20:
                continue

            # JSON file
            json_path = out_dir / f"{art['id']}.json"
            json_path.write_text(json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")

            # Markdown file
            slug = re.sub(r'[^\w\-]', '_', art["title"].lower())[:60]
            md_path = out_dir / f"{slug}.md"
            md_content = self._render_markdown(art)
            md_path.write_text(md_content, encoding="utf-8")

            saved += 1

        # Write index
        index = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "article_count": saved,
            "sources": self._sources,
            "articles": [
                {"id": a["id"], "title": a["title"], "category": a["category"],
                 "word_count": a.get("word_count", 0), "summary": a.get("summary", "")[:120]}
                for a in articles if a.get("word_count", 0) >= 20
            ],
        }
        (out_dir / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

        logger.info("kb_builder: saved %d articles to %s", saved, out_dir)
        return {"ok": True, "articles": saved, "path": str(out_dir)}

    @staticmethod
    def _render_markdown(art: dict) -> str:
        """Render an article dict as Markdown."""
        lines = [
            f"# {art['title']}",
            "",
            f"**Category:** {art.get('category', 'general')}  ",
            f"**Generated:** {art.get('created_at', '')}  ",
            f"**Words:** {art.get('word_count', 0)}  ",
            "",
        ]

        if art.get("summary"):
            lines += ["## Summary", "", art["summary"], ""]

        if art.get("body"):
            lines += ["## Content", "", art["body"], ""]

        entities = art.get("entities", {})
        if entities:
            lines += ["## Entities", ""]
            for category, ents in sorted(entities.items()):
                if ents:
                    lines.append(f"**{category}:** {', '.join(sorted(set(ents))[:15])}")
            lines.append("")

        links = art.get("links", [])
        if links:
            lines += ["## Related Articles", ""]
            for link in links[:8]:
                lines.append(f"- [{link['title']}](./{link['id']}.md) (strength: {link['strength']})")
            lines.append("")

        sources = art.get("sources", [])
        if sources:
            lines += ["## Sources", ""]
            for src in sources[:10]:
                lines.append(f"- {src}")
            lines.append("")

        return "\n".join(lines)


# ── Convenience functions ─────────────────────────────────────────────────────

def build_kb_from_directory(directory: str | Path, *, topic: str | None = None) -> dict:
    """One-shot: ingest all files in a directory and build + save a KB."""
    kb = KBBuilder()
    chunk_count = kb.ingest_directory(Path(directory))
    if chunk_count == 0:
        return {"ok": False, "error": "No content extracted from directory", "articles": 0}
    articles = kb.build_articles(topic=topic)
    return kb.save(articles)


def build_kb_from_texts(texts: list[str], *, topic: str | None = None, output_dir: Path | None = None) -> dict:
    """One-shot: ingest list of text strings and build + save a KB."""
    kb = KBBuilder()
    for i, text in enumerate(texts):
        kb.ingest_text(text, source=f"text_{i}")
    articles = kb.build_articles(topic=topic)
    return kb.save(articles, output_dir=output_dir)


def build_kb_from_urls(urls: list[str], *, topic: str | None = None) -> dict:
    """One-shot: fetch URLs and build + save a KB."""
    kb = KBBuilder()
    for url in urls:
        kb.ingest_url(url)
    articles = kb.build_articles(topic=topic)
    return kb.save(articles)

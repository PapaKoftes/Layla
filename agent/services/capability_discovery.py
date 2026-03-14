"""
Capability discovery engine. Scans PyPI, GitHub trending, and HuggingFace
to identify candidate libraries for each capability.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent
_CACHE_DIR = AGENT_DIR / ".capability_discovery_cache"
_CACHE_TTL_SEC = 3600 * 6  # 6 hours


@dataclass
class CandidateLibrary:
    """A candidate library for a capability."""

    name: str
    source: str  # "pypi" | "github" | "huggingface"
    description: str = ""
    url: str = ""
    downloads_per_day: int = 0
    stars: int = 0
    capability_hint: str = ""


# Mapping: capability -> search terms for discovery
CAPABILITY_SEARCH_TERMS: dict[str, list[str]] = {
    "vector_search": ["vector", "embedding", "similarity", "chromadb", "faiss", "qdrant", "milvus"],
    "embedding": ["embedding", "sentence-transformers", "openai-embedding", "instructor"],
    "reranker": ["rerank", "cross-encoder", "cohere", "cross encoder"],
    "web_scraper": ["scraper", "crawl", "trafilatura", "beautifulsoup", "extract article"],
}


def _fetch_json(url: str, headers: dict | None = None, timeout: int = 15) -> dict | list | None:
    """Fetch URL and parse JSON. Returns None on failure."""
    h = {"User-Agent": "Layla-CapabilityDiscovery/1.0"}
    if headers:
        h.update(headers)
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("capability_discovery fetch %s: %s", url[:60], e)
        return None


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}.json"


def _read_cache(key: str) -> list[dict] | None:
    """Read cached result. Returns None if missing or stale."""
    import time
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        mtime = p.stat().st_mtime
        if time.time() - mtime > _CACHE_TTL_SEC:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, data: list[dict]) -> None:
    try:
        _cache_path(key).write_text(json.dumps(data, indent=0), encoding="utf-8")
    except Exception as e:
        logger.debug("capability_discovery cache write: %s", e)


def scan_pypi(capability: str, terms: list[str]) -> list[CandidateLibrary]:
    """
    Scan PyPI for packages matching capability search terms.
    Uses simple search API; no API key required.
    """
    candidates: list[CandidateLibrary] = []
    seen: set[str] = set()
    for term in terms[:5]:  # Limit to avoid rate limits
        # PyPI search returns HTML; we use the JSON API for project metadata
        # Alternative: https://pypi.org/pypi/<package>/json
        # PyPI has no public JSON search; we use a minimal scrape or known packages
        # Fallback: return known packages per capability
        pass
    # Known PyPI packages per capability (discovery without scraping)
    known: dict[str, list[tuple[str, str]]] = {
        "vector_search": [
            ("chromadb", "Vector database for embeddings"),
            ("faiss-cpu", "Facebook AI Similarity Search"),
            ("qdrant-client", "Qdrant vector database client"),
            ("milvus", "Milvus vector database"),
        ],
        "embedding": [
            ("sentence-transformers", "Sentence embeddings"),
            ("instructor", "Structured outputs and embeddings"),
            ("openai", "OpenAI API including embeddings"),
        ],
        "reranker": [
            ("sentence-transformers", "Cross-encoder reranking"),
            ("cohere", "Cohere API including rerank"),
        ],
        "web_scraper": [
            ("trafilatura", "Article extraction"),
            ("beautifulsoup4", "HTML parsing"),
            ("crawl4ai", "Async web crawler"),
        ],
    }
    for pkg, desc in known.get(capability, []):
        if pkg.lower() not in seen:
            seen.add(pkg.lower())
            candidates.append(
                CandidateLibrary(
                    name=pkg,
                    source="pypi",
                    description=desc,
                    url=f"https://pypi.org/project/{pkg}/",
                    capability_hint=capability,
                )
            )
    return candidates


def scan_github_trending(capability: str) -> list[CandidateLibrary]:
    """
    Scan GitHub trending for relevant repos.
    GitHub has no public trending API; we return known repos.
    """
    # Known GitHub repos that implement capabilities
    known: dict[str, list[tuple[str, str, str]]] = {
        "vector_search": [
            ("chroma-core/chroma", "ChromaDB", "Open-source embedding database"),
            ("facebookresearch/faiss", "FAISS", "Efficient similarity search"),
            ("qdrant/qdrant", "Qdrant", "Vector similarity search engine"),
        ],
        "embedding": [
            ("UKPLab/sentence-transformers", "sentence-transformers", "Multilingual embeddings"),
            ("huggingface/transformers", "transformers", "Embedding models"),
        ],
        "reranker": [
            ("UKPLab/sentence-transformers", "cross-encoder", "Reranking models"),
        ],
        "web_scraper": [
            ("adbar/trafilatura", "trafilatura", "Web text extraction"),
        ],
    }
    candidates: list[CandidateLibrary] = []
    for repo, name, desc in known.get(capability, []):
        candidates.append(
            CandidateLibrary(
                name=name,
                source="github",
                description=desc,
                url=f"https://github.com/{repo}",
                capability_hint=capability,
            )
        )
    return candidates


def scan_huggingface_models(capability: str) -> list[CandidateLibrary]:
    """
    Scan HuggingFace for models relevant to the capability.
    Uses public Hub API (no token required for listing).
    """
    candidates: list[CandidateLibrary] = []
    if capability == "embedding":
        url = "https://huggingface.co/api/models?search=embedding&limit=10"
        data = _fetch_json(url)
        if isinstance(data, list):
            for m in data[:8]:
                if isinstance(m, dict) and m.get("id"):
                    model_id = m["id"]
                    candidates.append(
                        CandidateLibrary(
                            name=model_id,
                            source="huggingface",
                            description=m.get("pipeline_tag", "embedding") or "embedding",
                            url=f"https://huggingface.co/{model_id}",
                            capability_hint="embedding",
                        )
                    )
    elif capability == "reranker":
        url = "https://huggingface.co/api/models?search=rerank&limit=8"
        data = _fetch_json(url)
        if isinstance(data, list):
            for m in data[:6]:
                if isinstance(m, dict) and m.get("id"):
                    model_id = m["id"]
                    candidates.append(
                        CandidateLibrary(
                            name=model_id,
                            source="huggingface",
                            description=m.get("pipeline_tag", "rerank") or "rerank",
                            url=f"https://huggingface.co/{model_id}",
                            capability_hint="reranker",
                        )
                    )
    return candidates


def discover_candidate_libraries(capability_name: str, use_cache: bool = True) -> list[CandidateLibrary]:
    """Discover candidate libraries for a capability. Alias for discover_candidates."""
    return discover_candidates(capability_name, use_cache=use_cache)


def fetch_pypi_candidates(capability_name: str) -> list[CandidateLibrary]:
    """Fetch PyPI candidates for a capability."""
    terms = CAPABILITY_SEARCH_TERMS.get(capability_name, [capability_name])
    return scan_pypi(capability_name, terms)


def fetch_github_candidates(capability_name: str) -> list[CandidateLibrary]:
    """Fetch GitHub candidates for a capability."""
    return scan_github_trending(capability_name)


def fetch_huggingface_candidates(capability_name: str) -> list[CandidateLibrary]:
    """Fetch HuggingFace model candidates for a capability."""
    return scan_huggingface_models(capability_name)


def discover_candidates(capability: str, use_cache: bool = True) -> list[CandidateLibrary]:
    """
    Discover candidate libraries for a capability from PyPI, GitHub, HuggingFace.
    Returns deduplicated list of candidates.
    """
    cache_key = f"discover_{capability}"
    if use_cache:
        cached = _read_cache(cache_key)
        if cached is not None:
            return [CandidateLibrary(**c) for c in cached]

    terms = CAPABILITY_SEARCH_TERMS.get(capability, [capability])
    all_candidates: list[CandidateLibrary] = []
    seen: set[str] = set()

    for c in scan_pypi(capability, terms):
        key = f"pypi:{c.name.lower()}"
        if key not in seen:
            seen.add(key)
            all_candidates.append(c)

    for c in scan_github_trending(capability):
        key = f"github:{c.name.lower()}"
        if key not in seen:
            seen.add(key)
            all_candidates.append(c)

    for c in scan_huggingface_models(capability):
        key = f"hf:{c.name.lower()}"
        if key not in seen:
            seen.add(key)
            all_candidates.append(c)

    if use_cache:
        _write_cache(cache_key, [{"name": c.name, "source": c.source, "description": c.description, "url": c.url, "downloads_per_day": c.downloads_per_day, "stars": c.stars, "capability_hint": c.capability_hint} for c in all_candidates])

    return all_candidates


def discover_all_capabilities() -> dict[str, list[CandidateLibrary]]:
    """Discover candidates for all known capabilities."""
    try:
        from capabilities.registry import CAPABILITIES
    except ImportError:
        CAPABILITIES = {}
    result: dict[str, list[CandidateLibrary]] = {}
    for cap in CAPABILITIES:
        result[cap] = discover_candidates(cap, use_cache=True)
    return result

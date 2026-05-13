"""
enricher.py — Named entity extraction for the codex auto-linker.

Tries spaCy NER first (if installed); falls back to regex heuristics that
detect capitalised multi-word phrases, @mentions, file paths, URLs,
camelCase identifiers, and common programming terms.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("layla.codex")


# ── Public API ───────────────────────────────────────────────────────────────

def extract_entities(text: str) -> list[dict]:
    """
    Extract named entities from *text*.

    Returns a list of dicts, each with keys:
        name:       str   — the entity surface form
        type:       str   — an EntityType-compatible value
        confidence: float — extraction confidence 0.0-1.0
    """
    if not text or not text.strip():
        return []

    # Try spaCy first (lazy import; skip if not installed)
    try:
        entities = _extract_spacy(text)
        if entities:
            return entities
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("spaCy extraction failed, falling back to regex: %s", exc)

    return _extract_regex(text)


# ── spaCy backend ────────────────────────────────────────────────────────────

def _extract_spacy(text: str) -> list[dict]:
    """NER via spaCy. Raises ImportError if spaCy is not available."""
    import spacy  # noqa: F811 — intentional lazy import

    nlp = _get_spacy_model()
    doc = nlp(text[:10_000])  # cap input size

    _SPACY_TYPE_MAP = {
        "PERSON": "person",
        "ORG": "organisation",
        "GPE": "concept",
        "PRODUCT": "technology",
        "WORK_OF_ART": "concept",
        "EVENT": "event",
        "LANGUAGE": "technology",
        "FAC": "concept",
        "NORP": "concept",
        "LAW": "concept",
        "LOC": "concept",
    }

    seen: set[str] = set()
    entities: list[dict] = []
    for ent in doc.ents:
        name = ent.text.strip()
        key = name.lower()
        if key in seen or len(name) < 2:
            continue
        seen.add(key)
        etype = _SPACY_TYPE_MAP.get(ent.label_, "concept")
        entities.append({
            "name": name,
            "type": etype,
            "confidence": 0.75,
        })

    return entities


_spacy_model = None


def _get_spacy_model():
    """Cache the spaCy model across calls."""
    global _spacy_model
    if _spacy_model is None:
        import spacy
        try:
            _spacy_model = spacy.load("en_core_web_sm")
        except OSError:
            # Model not downloaded — fall back
            raise ImportError("spaCy model en_core_web_sm not found")
    return _spacy_model


# ── Regex fallback ───────────────────────────────────────────────────────────

# Common programming language / framework names (case-insensitive match)
_TECH_NAMES = frozenset({
    "python", "javascript", "typescript", "rust", "go", "golang", "java",
    "kotlin", "swift", "ruby", "php", "perl", "scala", "haskell", "clojure",
    "elixir", "erlang", "lua", "r", "julia", "dart", "zig", "nim", "ocaml",
    "c++", "c#", "objective-c", "assembly",
    # frameworks / tools
    "react", "vue", "angular", "svelte", "nextjs", "next.js", "nuxt",
    "django", "flask", "fastapi", "express", "nestjs", "spring",
    "rails", "laravel", "phoenix", "actix",
    "docker", "kubernetes", "terraform", "ansible", "nginx",
    "postgres", "postgresql", "mysql", "sqlite", "redis", "mongodb",
    "elasticsearch", "kafka", "rabbitmq", "celery",
    "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "scipy",
    "spacy", "huggingface", "transformers", "langchain",
    "git", "github", "gitlab", "bitbucket",
    "aws", "azure", "gcp", "vercel", "netlify", "heroku",
    "linux", "macos", "windows", "ubuntu", "debian", "fedora",
    "chromadb", "networkx", "pydantic", "sqlalchemy", "alembic",
    "arduino", "raspberry pi", "cnc", "polyboard", "optinest", "nchops",
})

# Words to skip as entities (too generic)
_STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "what", "which", "who", "when", "where", "why", "how",
    "not", "no", "yes", "all", "each", "every", "any", "some",
    "if", "then", "else", "so", "also", "just", "only", "very",
    "new", "old", "first", "last", "next", "use", "using", "used",
})


def _extract_regex(text: str) -> list[dict]:
    """Regex-based entity extraction fallback."""
    seen: set[str] = set()
    entities: list[dict] = []

    def _add(name: str, etype: str, confidence: float) -> None:
        key = name.strip().lower()
        if key in seen or len(key) < 2 or key in _STOP_WORDS:
            return
        seen.add(key)
        entities.append({"name": name.strip(), "type": etype, "confidence": confidence})

    # 1. Known technology / framework names
    text_lower = text.lower()
    for tech in _TECH_NAMES:
        # Word-boundary match
        pattern = r'\b' + re.escape(tech) + r'\b'
        if re.search(pattern, text_lower):
            _add(tech, "technology", 0.85)

    # 2. @mentions  (e.g. @username)
    for m in re.finditer(r'@([A-Za-z_]\w{1,39})', text):
        _add("@" + m.group(1), "person", 0.7)

    # 3. File paths (Unix or Windows)
    for m in re.finditer(r'(?:[A-Za-z]:\\|/)[\w./-]{4,}', text):
        _add(m.group(0), "file", 0.6)

    # 4. URLs
    for m in re.finditer(r'https?://[^\s)<>]{4,}', text):
        _add(m.group(0), "concept", 0.5)

    # 5. camelCase / PascalCase identifiers (likely code entities)
    for m in re.finditer(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', text):
        _add(m.group(1), "concept", 0.6)

    # 6. Capitalised multi-word phrases (2-4 words, likely proper nouns)
    for m in re.finditer(r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3})\b', text):
        phrase = m.group(1)
        # Filter out sentence-start false positives: skip if preceded by ". " or is at start
        start = m.start()
        if start > 0 and text[start - 1] not in ('.', '!', '?', '\n'):
            _add(phrase, "concept", 0.55)
        elif start == 0:
            # Could be a real entity at the start of text
            _add(phrase, "concept", 0.4)

    # 7. ALL_CAPS identifiers (constants, acronyms, >=3 chars)
    for m in re.finditer(r'\b([A-Z][A-Z_]{2,})\b', text):
        name = m.group(1)
        if name not in ("THE", "AND", "FOR", "NOT", "BUT", "ARE", "WAS", "HAS"):
            _add(name, "concept", 0.45)

    return entities

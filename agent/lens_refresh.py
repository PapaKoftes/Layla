"""
Lens knowledge refresh: regenerate lens_knowledge/*.md from approved structured sources.

No external crawling. Uses only curated reference material in agent/lens_knowledge/sources/.
"""
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
LENS_KNOWLEDGE_DIR = AGENT_DIR / "lens_knowledge"
SOURCES_DIR = LENS_KNOWLEDGE_DIR / "sources"

_MAX_WORDS = 800


def _truncate_to_words(text: str, max_words: int = _MAX_WORDS) -> str:
    """Return text truncated to at most max_words (by whitespace split)."""
    text = (text or "").strip()
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def rebuild_lens_knowledge() -> None:
    """
    For each approved source file in agent/lens_knowledge/sources/*.md,
    regenerate summary (truncate to 800 words) and overwrite agent/lens_knowledge/{name}.md.

    No external crawling. Curated reference material only.
    """
    if not SOURCES_DIR.exists():
        return
    for path in sorted(SOURCES_DIR.glob("*.md")):
        name = path.stem
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not content:
            continue
        summary = _truncate_to_words(content, _MAX_WORDS)
        out_path = LENS_KNOWLEDGE_DIR / f"{name}.md"
        try:
            out_path.write_text(summary, encoding="utf-8")
        except Exception:
            continue

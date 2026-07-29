"""
Honesty guard for the ship-on-clone RAG knowledge library (../knowledge/*.md).

These files are indexed into the retrieval store (vector_store excludes only
.identity/) and can surface to the model as "Reference docs" on questions that do
NOT trip the narrow capability regex. If they drift from the verified capability
manifest (.identity/capabilities.md), the model gets a stale competing source with
no correction — the exact defect the manifest work closed at the primary source.

This test pins the two claims that historically drifted:
  1. TTS has NO silent browser-SpeechSynthesis fallback (removed; endpoint 503s).
  2. Hard-coded "current total tool count" claims must not contradict the live
     registry. Historical roadmap *tier* rows (e.g. "1-59 tools") are allowed;
     phrasings that assert a current inventory total are not.
"""

from __future__ import annotations

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


def _md_files() -> list[Path]:
    if not KNOWLEDGE_DIR.is_dir():
        return []
    return sorted(KNOWLEDGE_DIR.rglob("*.md")) + sorted(KNOWLEDGE_DIR.rglob("*.txt"))


def test_no_browser_speechsynthesis_fallback_claim():
    """The manifest states the browser-voice fallback was removed. No knowledge
    doc may claim TTS silently falls back to the browser's SpeechSynthesis."""
    offenders = []
    for f in _md_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        if "browser speechsynthesis" in low or "speechsynthesis automatically" in low:
            offenders.append(str(f.relative_to(KNOWLEDGE_DIR)))
    assert not offenders, (
        "Stale TTS fallback claim in knowledge docs (manifest says the browser-voice "
        f"fallback was removed): {offenders}"
    )


def test_no_stale_current_total_tool_count():
    """Ban the specific stale 'current total' phrasings that contradicted the live
    registry. Historical roadmap tier ranges are intentionally NOT matched."""
    banned = ("191 tools", "all 59 tools", "59 tools with")
    offenders = []
    for f in _md_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for phrase in banned:
            if phrase in text:
                offenders.append(f"{f.relative_to(KNOWLEDGE_DIR)}: '{phrase}'")
    assert not offenders, (
        "Stale current-total tool count in knowledge docs — the live registry ships "
        f"202 tools (see test_registered_tools_count.py): {offenders}"
    )

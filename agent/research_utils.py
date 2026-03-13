"""Shared utilities for research_stages.py and research_intelligence.py."""
import json
import re


def normalize_stage_text(text: str) -> str:
    """Replace Unicode em-dash with ASCII hyphen so stage goals are never invalid if mistaken for code."""
    if not text or not isinstance(text, str):
        return text or ""
    return text.replace("\u2014", "-").replace("\u2013", "-").replace("—", "-")


def _extract_json_block(text: str) -> dict | None:
    """Try to extract a JSON object from markdown or raw text."""
    if not text:
        return None
    # Code block
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Raw JSON
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start: i + 1])
                    except json.JSONDecodeError:
                        break
    return None

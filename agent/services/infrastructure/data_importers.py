"""Best-effort parsers for chat exports and media cataloging (privacy-preserving)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("layla")

_WHATSAPP_LINE = re.compile(
    r"^\s*\[?(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})[,\s]+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\]?\s*[-–—]\s*(.+?):\s*(.*)\s*$"
)


def parse_whatsapp_txt(text: str) -> list[dict[str, str]]:
    """Parse a WhatsApp export ``_chat.txt`` style (best effort)."""
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        m = _WHATSAPP_LINE.match(line)
        if not m:
            continue
        rows.append({"date": m.group(1), "time": m.group(2), "sender": m.group(3).strip(), "text": m.group(4).strip()})
    return rows


def whatsapp_export_to_markdown(text: str, title: str = "WhatsApp import") -> str:
    rows = parse_whatsapp_txt(text)
    lines = [f"# {title}", "", f"Messages: {len(rows)}", ""]
    for r in rows[:5000]:
        lines.append(f"- **{r['sender']}** ({r['date']} {r['time']}): {r['text']}")
    if len(rows) > 5000:
        lines.append(f"\n… {len(rows) - 5000} more lines omitted …")
    return "\n".join(lines)

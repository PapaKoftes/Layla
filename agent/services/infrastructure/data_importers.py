"""Best-effort parsers for chat exports and media cataloging (privacy-preserving)."""
from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

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


def parse_telegram_result_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    msgs = data.get("messages") if isinstance(data, dict) else None
    return msgs if isinstance(msgs, list) else []


def media_folder_catalog(root: Path, limit: int = 5000) -> list[dict[str, Any]]:
    """Non-content index: path, size, mtime only."""
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    count = 0
    for p in root.rglob("*"):
        if count >= limit:
            break
        if not p.is_file():
            continue
        try:
            st = p.stat()
            out.append(
                {
                    "path": str(p),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "suffix": p.suffix.lower(),
                }
            )
            count += 1
        except Exception:
            continue
    return out


def extract_zip_safe(zpath: Path, dest: Path) -> dict[str, Any]:
    """Extract zip if all members stay under dest (zip-slip safe)."""
    dest = dest.resolve()
    with zipfile.ZipFile(zpath, "r") as zf:
        for m in zf.infolist():
            target = (dest / m.filename).resolve()
            if not str(target).startswith(str(dest)):
                return {"ok": False, "error": "unsafe_zip"}
        zf.extractall(dest)
    return {"ok": True, "dest": str(dest)}

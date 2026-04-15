from __future__ import annotations

from services.data_importers import parse_whatsapp_txt, whatsapp_export_to_markdown


def test_parse_whatsapp_line():
    line = "12/31/2024, 11:59 PM - Alice: Hello there"
    rows = parse_whatsapp_txt(line)
    assert len(rows) >= 1
    assert "Alice" in rows[0]["sender"]


def test_whatsapp_md():
    md = whatsapp_export_to_markdown("1/1/2025, 10:00 - Bob: Hi", title="T")
    assert "Bob" in md

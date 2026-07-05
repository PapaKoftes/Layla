"""BL-230: visual understanding — VLM backend + unified analyze_image."""
from __future__ import annotations

import pytest

from services.vision import image_analysis as ia
from services.vision import vlm_backend as vb


# ── vlm_backend availability ──────────────────────────────────────────────────
def test_vlm_unavailable_without_paths(monkeypatch):
    monkeypatch.setattr(vb, "_cfg", lambda: {})
    assert vb.vlm_available() is False
    r = vb.vlm_describe("x.png")
    assert not r["ok"] and r["error"] == "vlm_unavailable"


def test_vlm_unavailable_when_files_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(vb, "_cfg", lambda: {
        "vision_model_path": str(tmp_path / "nope.gguf"),
        "vision_mmproj_path": str(tmp_path / "nope-mmproj.gguf"),
    })
    assert vb.vlm_available() is False


# ── unified analyze_image orchestration ──────────────────────────────────────
def test_analyze_prefers_vlm(monkeypatch):
    monkeypatch.setattr("services.vision.vlm_backend.vlm_available", lambda cfg=None: True)
    monkeypatch.setattr("services.vision.vlm_backend.vlm_describe",
                        lambda path, prompt="", **kw: {"ok": True, "description": "a red car"})
    monkeypatch.setattr("layla.tools.impl.analysis.ocr_image",
                        lambda path, **kw: {"ok": True, "text": "PLATE-123", "method": "easyocr"})
    r = ia.analyze_image("car.png", "what colour?")
    assert r["ok"] and r["description"] == "a red car"
    assert r["description_method"] == "gguf_vlm"
    assert r["ocr_text"] == "PLATE-123"


def test_analyze_falls_back_to_blip(monkeypatch):
    monkeypatch.setattr("services.vision.vlm_backend.vlm_available", lambda cfg=None: False)
    monkeypatch.setattr("layla.tools.impl.analysis.describe_image",
                        lambda path, **kw: {"ok": True, "caption": "a cat on a mat"})
    monkeypatch.setattr("layla.tools.impl.analysis.ocr_image",
                        lambda path, **kw: {"ok": False})
    r = ia.analyze_image("cat.png")
    assert r["ok"] and r["description"] == "a cat on a mat"
    assert r["description_method"] == "blip"


def test_analyze_all_backends_absent(monkeypatch):
    monkeypatch.setattr("services.vision.vlm_backend.vlm_available", lambda cfg=None: False)
    monkeypatch.setattr("layla.tools.impl.analysis.describe_image",
                        lambda path, **kw: {"ok": False, "error": "transformers missing"})
    monkeypatch.setattr("layla.tools.impl.analysis.ocr_image", lambda path, **kw: {"ok": False})
    r = ia.analyze_image("x.png")
    assert not r["ok"] and "transformers missing" in r["error"]


def test_analyze_ocr_only(monkeypatch):
    # description fails but OCR succeeds → still ok, driven by text
    monkeypatch.setattr("services.vision.vlm_backend.vlm_available", lambda cfg=None: False)
    monkeypatch.setattr("layla.tools.impl.analysis.describe_image", lambda path, **kw: {"ok": False, "error": "no model"})
    monkeypatch.setattr("layla.tools.impl.analysis.ocr_image",
                        lambda path, **kw: {"ok": True, "text": "hello world", "method": "pytesseract"})
    r = ia.analyze_image("scan.png")
    assert r["ok"] and r["ocr_text"] == "hello world" and r["ocr_method"] == "pytesseract"


def test_analyze_image_tool_registered():
    from layla.tools.registry import TOOLS
    assert "analyze_image" in TOOLS and callable(TOOLS["analyze_image"]["fn"])


# ── /v1 image content-parts ──────────────────────────────────────────────────
_IMG_PART = {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGk="}}
_TXT_PART = {"type": "text", "text": "what is this?"}


def test_v1_image_part_ignored_when_vision_off(monkeypatch):
    from routers import openai_compat as oc
    monkeypatch.setattr(oc, "_vision_enabled", lambda: False)
    out = oc._normalize_openai_content([_TXT_PART, _IMG_PART])
    assert out == "what is this?"   # image dropped, text kept


def test_v1_image_part_analyzed_when_vision_on(monkeypatch):
    from routers import openai_compat as oc
    monkeypatch.setattr(oc, "_vision_enabled", lambda: True)
    monkeypatch.setattr(oc, "_analyze_image_part", lambda url: "[Image: a diagram | text in image: START]")
    out = oc._normalize_openai_content([_TXT_PART, _IMG_PART])
    assert "what is this?" in out
    assert "[Image: a diagram | text in image: START]" in out


def test_v1_image_part_non_datauri_ignored():
    from routers import openai_compat as oc
    # http URL → no outbound fetch, returns "" (SSRF-safe)
    assert oc._analyze_image_part("https://example.com/x.png") == ""

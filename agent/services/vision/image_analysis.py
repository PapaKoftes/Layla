"""Unified image analysis (BL-230) — one entry point over the vision backends.

`analyze_image` picks the best available describer — the local GGUF VLM when configured
(free-form, prompt-aware), otherwise the existing BLIP captioner — and optionally layers
Tesseract/EasyOCR text extraction on top. It returns a single structured result recording
which method answered, so callers get graceful degradation without knowing the backends.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def analyze_image(path: str, prompt: str = "", *, ocr: bool = True, detail: str = "brief") -> dict[str, Any]:
    """Describe an image (VLM if available, else BLIP) and optionally OCR its text."""
    result: dict[str, Any] = {"ok": False, "path": path}

    # 1) description — prefer the local GGUF VLM (prompt-aware), else BLIP captioner
    described = False
    try:
        from services.vision.vlm_backend import vlm_available, vlm_describe
        if vlm_available():
            v = vlm_describe(path, prompt)
            if v.get("ok"):
                result.update(ok=True, description=v["description"], description_method="gguf_vlm")
                described = True
    except Exception as e:  # noqa: BLE001
        logger.debug("analyze_image: vlm path skipped: %s", e)

    if not described:
        try:
            from layla.tools.impl.analysis import describe_image
            d = describe_image(path, detail=detail)
            if d.get("ok"):
                result.update(ok=True, description=d.get("caption", ""), description_method="blip")
                if d.get("ocr_text") and "ocr_text" not in result:
                    result["ocr_text"] = d["ocr_text"]
            else:
                result["describe_error"] = d.get("error")
        except Exception as e:  # noqa: BLE001
            result["describe_error"] = str(e)

    # 2) OCR — best-effort, independent of the describer
    if ocr and "ocr_text" not in result:
        try:
            from layla.tools.impl.analysis import ocr_image
            o = ocr_image(path)
            if o.get("ok") and o.get("text"):
                result["ok"] = True
                result["ocr_text"] = o["text"]
                result["ocr_method"] = o.get("method")
        except Exception as e:  # noqa: BLE001
            logger.debug("analyze_image: ocr skipped: %s", e)

    if not result["ok"]:
        result["error"] = result.get("describe_error") or "no vision backend available"
    return result

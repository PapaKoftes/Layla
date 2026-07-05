"""GGUF multimodal vision backend (BL-230) — LLaVA / moondream2 / Qwen2-VL via llama.cpp.

An *optional*, fully-local vision backend built on `llama-cpp-python`'s multimodal chat
handler: point `vision_model_path` at a vision GGUF and `vision_mmproj_path` at its
mmproj projector, and Layla can answer free-form questions about an image with the same
runtime it already uses for text. This is prebuilt-OSS all the way down (llama.cpp).
Everything degrades gracefully — no model/library ⇒ `vlm_available()` is False and callers
fall back to the BLIP captioner + Tesseract/EasyOCR paths that already exist.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# module-level cache so the (expensive) model + projector load once
_CACHE: dict[str, Any] = {}


def _cfg() -> dict:
    try:
        import runtime_safety
        return runtime_safety.load_config() or {}
    except Exception:
        return {}


def vision_paths(cfg: dict | None = None) -> tuple[str, str]:
    cfg = cfg if cfg is not None else _cfg()
    return str(cfg.get("vision_model_path") or "").strip(), str(cfg.get("vision_mmproj_path") or "").strip()


def vlm_available(cfg: dict | None = None) -> bool:
    """True when a vision GGUF + mmproj are configured, present, and llama_cpp is importable."""
    model, mmproj = vision_paths(cfg)
    if not model or not mmproj:
        return False
    if not (Path(model).exists() and Path(mmproj).exists()):
        return False
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def _load(cfg: dict) -> Any:
    model, mmproj = vision_paths(cfg)
    key = f"{model}::{mmproj}"
    if key in _CACHE:
        return _CACHE[key]
    from llama_cpp import Llama
    from llama_cpp.llama_chat_format import Llava15ChatHandler

    handler = Llava15ChatHandler(clip_model_path=mmproj, verbose=False)
    llm = Llama(
        model_path=model, chat_handler=handler,
        n_ctx=int(cfg.get("vision_n_ctx", 4096) or 4096),
        n_gpu_layers=int(cfg.get("vision_n_gpu_layers", 0) or 0),
        logits_all=False, verbose=False,
    )
    _CACHE[key] = llm
    return llm


def _data_uri(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "tif": "tiff"}.get(ext, ext)
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def vlm_describe(path: str, prompt: str = "", *, cfg: dict | None = None, max_tokens: int = 256) -> dict[str, Any]:
    """Answer a free-form question about an image using the local GGUF VLM."""
    cfg = cfg if cfg is not None else _cfg()
    if not vlm_available(cfg):
        return {"ok": False, "error": "vlm_unavailable", "reason": "no vision GGUF + mmproj configured, or llama_cpp missing"}
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "file not found"}
    question = (prompt or "").strip() or "Describe this image in detail."
    try:
        llm = _load(cfg)
        out = llm.create_chat_completion(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _data_uri(str(p))}},
                    {"type": "text", "text": question},
                ],
            }],
            max_tokens=max_tokens,
        )
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
        return {"ok": True, "method": "gguf_vlm", "path": str(p), "description": text.strip(), "prompt": question}
    except Exception as e:  # noqa: BLE001
        logger.warning("vlm_describe failed: %s", e)
        return {"ok": False, "error": "vlm_error", "detail": str(e)}

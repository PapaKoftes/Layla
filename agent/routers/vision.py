"""Vision router (BL-230) — unified image analysis endpoint (feature: vision)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/vision", tags=["vision"])


class AnalyzeBody(BaseModel):
    path: str
    prompt: str = ""
    ocr: bool = True


@router.get("/status")
def status():
    from services.vision.vlm_backend import vlm_available, vision_paths
    model, mmproj = vision_paths()
    return {
        "gguf_vlm_available": vlm_available(),
        "vision_model_path": model,
        "vision_mmproj_path": mmproj,
    }


@router.post("/analyze")
def analyze(body: AnalyzeBody):
    from services.vision.image_analysis import analyze_image
    return analyze_image(body.path, body.prompt, ocr=body.ocr)

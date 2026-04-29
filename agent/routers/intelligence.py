"""
intelligence.py — REST API for Layla's intelligence enhancement layer.

Exposes:
  /intelligence/info            GET   — Capability status for all intelligence services
  /intelligence/airllm/info     GET   — AirLLM model info
  /intelligence/airllm/generate POST  — Generate text via local large model
  /intelligence/airllm/unload   POST  — Unload model from memory
  /intelligence/compress        POST  — Compress text or RAG context
  /intelligence/optimize        POST  — Optimize user prompt for LLM
  /intelligence/kb/build        POST  — Build KB articles from raw text/files/URLs
  /intelligence/kb/info         GET   — KB library info
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("layla")
router = APIRouter(prefix="/intelligence", tags=["intelligence"])


# ── /intelligence/info ────────────────────────────────────────────────────────

@router.get("/info")
def intelligence_info():
    """
    Return availability and configuration status for all intelligence services:
    AirLLM, prompt compression, prompt optimization, and KB builder.
    """
    info: dict[str, Any] = {}

    try:
        from services.airllm_runner import get_info as _airllm_info
        info["airllm"] = _airllm_info()
    except Exception as exc:
        info["airllm"] = {"error": str(exc)}

    try:
        from services.prompt_compressor import get_info as _comp_info
        info["compression"] = _comp_info()
    except Exception as exc:
        info["compression"] = {"error": str(exc)}

    try:
        from services.prompt_optimizer import get_available_tier as _opt_tier, _use_dspy, _use_guidance
        info["optimizer"] = {
            "enabled": True,
            "dspy_requested": _use_dspy(),
            "guidance_requested": _use_guidance(),
        }
        try:
            import dspy
            info["optimizer"]["dspy_installed"] = True
        except ImportError:
            info["optimizer"]["dspy_installed"] = False
        try:
            import guidance
            info["optimizer"]["guidance_installed"] = True
        except ImportError:
            info["optimizer"]["guidance_installed"] = False
    except Exception as exc:
        info["optimizer"] = {"error": str(exc)}

    try:
        from services.kb_builder import get_info as _kb_info
        info["kb_builder"] = _kb_info()
    except Exception as exc:
        info["kb_builder"] = {"error": str(exc)}

    return info


# ── AirLLM endpoints ──────────────────────────────────────────────────────────

@router.get("/airllm/info")
def airllm_info():
    """Return AirLLM configuration and availability status."""
    from services.airllm_runner import get_info
    return get_info()


class AirLLMGenerateRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt to complete")
    max_tokens: int = Field(512, ge=1, le=8192, description="Maximum tokens to generate")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    stop: list[str] = Field(default_factory=list, description="Stop sequences")
    model_path: str | None = Field(None, description="Override model path from config")


class AirLLMChatRequest(BaseModel):
    messages: list[dict] = Field(..., description="Chat messages: [{role, content}]")
    max_tokens: int = Field(512, ge=1, le=8192)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    model_path: str | None = None


@router.post("/airllm/generate")
def airllm_generate(req: AirLLMGenerateRequest):
    """
    Generate text from a local large model via AirLLM layer-by-layer inference.
    Requires airllm_enabled=true and airllm_model_path set in config.json.
    Generation is slower than full-VRAM inference but works on consumer GPUs.
    """
    from services.airllm_runner import generate, is_available
    if not is_available():
        from services.airllm_runner import get_info
        return JSONResponse({"ok": False, "error": "AirLLM not available", "info": get_info()}, status_code=503)
    result = generate(
        req.prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        stop=req.stop or None,
        model_path=req.model_path,
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=500)
    return result


@router.post("/airllm/chat")
def airllm_chat(req: AirLLMChatRequest):
    """Chat-style generation via AirLLM. Applies the model's chat template if available."""
    from services.airllm_runner import generate_chat, is_available
    if not is_available():
        return JSONResponse({"ok": False, "error": "AirLLM not available"}, status_code=503)
    result = generate_chat(
        req.messages,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        model_path=req.model_path,
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=500)
    return result


@router.post("/airllm/unload")
def airllm_unload(model_path: str | None = None):
    """Unload AirLLM model from memory to free VRAM/RAM."""
    from services.airllm_runner import unload_model
    unload_model(model_path)
    return {"ok": True, "message": f"Model {'all models' if not model_path else model_path} unloaded"}


# ── Compression endpoints ─────────────────────────────────────────────────────

class CompressRequest(BaseModel):
    text: str = Field(..., description="Text to compress")
    target_ratio: float = Field(0.5, ge=0.05, le=0.95, description="Target output/input length ratio")
    question: str = Field("", description="Optional question to guide compression (keeps relevant tokens)")
    token_budget: int | None = Field(None, description="Hard token budget (overrides target_ratio)")
    force_heuristic: bool = Field(False, description="Skip LLMLingua even if installed")


class CompressRAGRequest(BaseModel):
    documents: list[str] = Field(..., description="List of retrieved document strings")
    query: str = Field(..., description="User query guiding which content to keep")
    token_budget: int = Field(1000, ge=100, description="Max tokens in compressed output")
    target_ratio: float | None = Field(None, description="Alternative to token_budget")


@router.post("/compress")
def compress_text(req: CompressRequest):
    """
    Compress text to target length using LLMLingua (if installed) or heuristic scoring.
    Returns compressed text, achieved ratio, and method used.
    """
    from services.prompt_compressor import compress
    return compress(
        req.text,
        target_ratio=req.target_ratio,
        question=req.question,
        token_budget=req.token_budget,
        force_heuristic=req.force_heuristic,
    )


@router.post("/compress/rag")
def compress_rag(req: CompressRAGRequest):
    """
    Compress retrieved RAG documents for inclusion in a prompt.
    Uses LongLLMLingua (question-aware, multi-doc) if available.
    Returns a single compressed context string ready for prompt injection.
    """
    from services.prompt_compressor import compress_rag_context
    return compress_rag_context(
        req.documents,
        req.query,
        token_budget=req.token_budget,
        target_ratio=req.target_ratio,
    )


# ── Prompt optimization endpoints ─────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    message: str = Field(..., description="Raw user message to optimize")
    context: dict = Field(default_factory=dict, description="Optional context: aspect, workspace, user_level, output_format, history_summary")
    force_tier: int | None = Field(None, ge=0, le=3, description="Force specific optimization tier (0=off, 1=heuristic, 2=structural, 3=DSPy)")


@router.post("/optimize")
def optimize_prompt(req: OptimizeRequest):
    """
    Transform a raw user message into the optimal LLM prompt.

    Applies a multi-tier pipeline:
    - Tier 1: Intent classification, entity extraction, ambiguity detection
    - Tier 2: Structural rewrite using intent-specific templates
    - Tier 3: DSPy-based programmatic prompt optimization (if installed)
    + Context enrichment, output format hints, and guidance constraints

    Returns the optimized prompt plus analysis metadata.
    """
    from services.prompt_optimizer import optimize
    return optimize(req.message, context=req.context, force_tier=req.force_tier)


# ── KB builder endpoints ──────────────────────────────────────────────────────

class KBBuildFromTextRequest(BaseModel):
    texts: list[str] = Field(..., description="List of raw text strings to ingest")
    topic: str | None = Field(None, description="Optional topic to focus article building")
    output_dir: str | None = Field(None, description="Override output directory")


class KBBuildFromURLsRequest(BaseModel):
    urls: list[str] = Field(..., description="List of URLs to fetch and ingest")
    topic: str | None = Field(None, description="Optional topic to focus article building")


class KBBuildFromDirectoryRequest(BaseModel):
    directory: str = Field(..., description="Directory path to ingest recursively")
    topic: str | None = Field(None)


@router.get("/kb/info")
def kb_info():
    """Return KB builder capability info and output directory status."""
    from services.kb_builder import get_info
    info = get_info()

    # Add article count from index if it exists
    try:
        from pathlib import Path as _Path
        import json as _json
        idx = _Path(info["output_dir"]) / "_index.json"
        if idx.exists():
            data = _json.loads(idx.read_text(encoding="utf-8"))
            info["saved_articles"] = data.get("article_count", 0)
            info["last_generated"] = data.get("generated_at", "")
        else:
            info["saved_articles"] = 0
    except Exception:
        info["saved_articles"] = 0

    return info


@router.post("/kb/build/text")
def kb_build_from_text(req: KBBuildFromTextRequest):
    """
    Build a knowledge base from a list of raw text strings.
    Auto-discovers topics and synthesizes structured articles.
    Articles are saved as JSON + Markdown in the KB output directory.
    """
    from services.kb_builder import build_kb_from_texts
    out = Path(req.output_dir) if req.output_dir else None
    result = build_kb_from_texts(req.texts, topic=req.topic, output_dir=out)
    return result


@router.post("/kb/build/urls")
def kb_build_from_urls(req: KBBuildFromURLsRequest):
    """
    Build a knowledge base from a list of URLs.
    Fetches each URL, extracts text, discovers topics, and synthesizes articles.
    """
    from services.kb_builder import build_kb_from_urls
    return build_kb_from_urls(req.urls, topic=req.topic)


@router.post("/kb/build/directory")
def kb_build_from_directory(req: KBBuildFromDirectoryRequest):
    """
    Build a knowledge base from all supported files in a directory.
    Recursively ingests .txt, .md, .py, .js, .json, .yaml, .pdf, etc.
    """
    from services.kb_builder import build_kb_from_directory
    if not Path(req.directory).is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.directory}")
    return build_kb_from_directory(req.directory, topic=req.topic)


@router.get("/kb/articles")
def kb_list_articles():
    """List all KB articles from the index."""
    try:
        from services.kb_builder import _kb_output_dir
        import json as _json
        idx = _kb_output_dir() / "_index.json"
        if not idx.exists():
            return {"articles": [], "message": "No KB index found. Run a build first."}
        data = _json.loads(idx.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/kb/articles/{article_id}")
def kb_get_article(article_id: str):
    """Get a single KB article by ID."""
    try:
        from services.kb_builder import _kb_output_dir
        import json as _json
        art_path = _kb_output_dir() / f"{article_id}.json"
        if not art_path.exists():
            raise HTTPException(status_code=404, detail=f"Article {article_id} not found")
        return _json.loads(art_path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

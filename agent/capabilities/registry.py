"""
Capability registry. Each capability may have multiple implementations.
Example: vector_search → chromadb, faiss, qdrant.
Dynamic selection uses benchmark results from capability_implementations table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class CapabilityImpl:
    """A single implementation of a capability."""

    id: str
    package: str
    module_path: str
    description: str = ""
    min_python: str = "3.11"
    dependencies: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    is_default: bool = False


# Capability definitions: name -> list of implementations
CAPABILITIES: dict[str, list[CapabilityImpl]] = {
    "vector_search": [
        CapabilityImpl(
            id="chromadb",
            package="chromadb",
            module_path="layla.memory.vector_store",
            description="ChromaDB persistent vector store (current default)",
            is_default=True,
        ),
        CapabilityImpl(
            id="faiss",
            package="faiss-cpu",
            module_path="capabilities.impl.faiss_vector",
            description="Facebook FAISS in-memory ANN search",
            dependencies=["faiss-cpu"],
        ),
        CapabilityImpl(
            id="qdrant",
            package="qdrant-client",
            module_path="capabilities.impl.qdrant_vector",
            description="Qdrant client for local or remote vector DB",
            dependencies=["qdrant-client"],
        ),
    ],
    "embedding": [
        CapabilityImpl(
            id="sentence_transformers",
            package="sentence-transformers",
            module_path="layla.memory.vector_store",
            description="sentence-transformers (nomic-embed-text, all-MiniLM fallback)",
            is_default=True,
        ),
        CapabilityImpl(
            id="openai",
            package="openai",
            module_path="capabilities.impl.openai_embed",
            description="OpenAI embeddings API (requires API key)",
            config_keys=["openai_api_key"],
        ),
    ],
    "reranker": [
        CapabilityImpl(
            id="cross_encoder",
            package="sentence-transformers",
            module_path="layla.memory.vector_store",
            description="Cross-encoder reranking via sentence-transformers",
            is_default=True,
        ),
        CapabilityImpl(
            id="cohere",
            package="cohere",
            module_path="capabilities.impl.cohere_rerank",
            description="Cohere rerank API (requires API key)",
            config_keys=["cohere_api_key"],
        ),
    ],
    "web_scraper": [
        CapabilityImpl(
            id="trafilatura",
            package="trafilatura",
            module_path="layla.tools.registry",
            description="Trafilatura article extraction (current default)",
            is_default=True,
        ),
        CapabilityImpl(
            id="beautifulsoup",
            package="beautifulsoup4",
            module_path="capabilities.impl.bs4_scraper",
            description="BeautifulSoup HTML parsing",
        ),
    ],
    "geometry_kernel_ezdxf": [
        CapabilityImpl(
            id="ezdxf",
            package="ezdxf",
            module_path="layla.geometry.backends.ezdxf_backend",
            description="2D DXF generation (layla.geometry)",
            is_default=True,
        ),
    ],
    "geometry_kernel_cadquery": [
        CapabilityImpl(
            id="cadquery",
            package="cadquery",
            module_path="layla.geometry.backends.cadquery_backend",
            description="3D solids export via cadquery (subprocess)",
            is_default=True,
        ),
    ],
    "geometry_kernel_trimesh": [
        CapabilityImpl(
            id="trimesh",
            package="trimesh",
            module_path="layla.geometry.backends.mesh_backend",
            description="Mesh load / info via trimesh",
            is_default=True,
        ),
    ],
    # Local GGUF code specialist vs default stack (llama_cpp always importable when installed)
    "llm_model_coding": [
        CapabilityImpl(
            id="magicoder",
            package="llama_cpp",
            module_path="llama_cpp",
            description="Magicoder-S-DS-6.7B-class GGUF code specialist (set coding_model / models.code)",
            is_default=False,
        ),
        CapabilityImpl(
            id="default_coding",
            package="llama_cpp",
            module_path="llama_cpp",
            description="Primary model for coding tasks (same stack as chat)",
            is_default=True,
        ),
    ],
}


def list_implementations(capability: str) -> list[CapabilityImpl]:
    """Return all known implementations for a capability."""
    return list(CAPABILITIES.get(capability, []))


def get_best_llm_filename_for_task(task_type: str, cfg: dict | None = None) -> str | None:
    """
    Capability + benchmark aware GGUF basename for routing (currently coding / Magicoder path).
    Returns None to fall back to select_model / route_model logic.
    """
    if task_type != "coding":
        return None
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    try:
        impl = get_active_implementation("llm_model_coding", cfg)
        if impl and impl.id == "magicoder":
            raw = (cfg.get("coding_model") or "").strip()
            if not raw:
                return None
            from services.model_router import _resolve_models_block_alias

            return _resolve_models_block_alias(raw) or raw
    except Exception as e:
        logger.debug("get_best_llm_filename_for_task: %s", e)
    return None


def _module_importable(module_path: str) -> bool:
    """Return True if module_path can be imported (e.g. capabilities.impl.faiss_vector exists)."""
    try:
        __import__(module_path)
        return True
    except Exception:
        return False


def get_active_implementation(capability: str, cfg: dict | None = None) -> CapabilityImpl | None:
    """
    Return the active implementation for a capability.
    Priority: 1) runtime_config capability_impls override, 2) best benchmark score, 3) default fallback.
    If the selected impl's module_path cannot be imported, falls back to default.
    """
    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception as e:
            logger.debug("get_active_implementation load_config failed: %s", e)
            cfg = {}

    impls = list_implementations(capability)
    if not impls:
        return None

    def _pick_impl(candidates: list[CapabilityImpl]) -> CapabilityImpl | None:
        for impl in candidates:
            if _module_importable(impl.module_path):
                return impl
            logger.debug("capability %s impl %s module %s not importable, skipping", capability, impl.id, impl.module_path)
        return None

    # 1. Config override: capability_impls.vector_search = "faiss"
    if cfg:
        overrides = cfg.get("capability_impls") or {}
        override_id = overrides.get(capability)
        if override_id:
            for impl in impls:
                if impl.id == override_id:
                    if _module_importable(impl.module_path):
                        return impl
                    logger.warning("capability_impls.%s=%s: module %s not found, falling back to default", capability, override_id, impl.module_path)
                    break

    # 2. Best benchmarked (lowest latency, sandbox_valid)
    try:
        from layla.memory.db import get_best_capability_implementation
        best = get_best_capability_implementation(capability)
        if best:
            impl_id = best.get("implementation_id")
            for impl in impls:
                if impl.id == impl_id and _module_importable(impl.module_path):
                    return impl
    except Exception as e:
        logger.debug("get_active_implementation get_best failed: %s", e)

    # 3. Default fallback (default impls use layla.memory.vector_store or layla.tools.registry)
    for impl in impls:
        if impl.is_default:
            return impl
    return impls[0]


def register_implementation(capability: str, impl: CapabilityImpl) -> None:
    """Register a new implementation for a capability. Used by plugins and discovery."""
    if capability not in CAPABILITIES:
        CAPABILITIES[capability] = []
    existing_ids = {i.id for i in CAPABILITIES[capability]}
    if impl.id not in existing_ids:
        CAPABILITIES[capability].append(impl)
        logger.info("Registered capability impl: %s.%s", capability, impl.id)

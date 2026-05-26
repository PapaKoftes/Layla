"""
Benchmark suite for capability implementations.
Measures latency, throughput, memory usage. Stores results locally in DB.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent


def _get_db():
    from layla.memory.db import (
        get_capability_implementation,
        migrate,
        upsert_capability_implementation,
    )
    migrate()
    return get_capability_implementation, upsert_capability_implementation


def benchmark_embedding(impl_id: str, n_samples: int = 50) -> dict[str, Any]:
    """
    Benchmark embedding implementation. Returns latency_ms, throughput_per_sec, memory_mb.
    """
    result: dict[str, Any] = {"latency_ms": None, "throughput_per_sec": None, "memory_mb": None, "error": None}
    try:
        import psutil
        proc = psutil.Process()
        mem_before = proc.memory_info().rss / (1024 * 1024)

        if impl_id == "sentence_transformers":
            from layla.memory.vector_store import embed
            samples = ["This is a test sentence for benchmarking."] * min(n_samples, 20)
            start = time.perf_counter()
            for s in samples:
                embed(s)
            elapsed = time.perf_counter() - start
            result["latency_ms"] = round((elapsed / len(samples)) * 1000, 2)
            result["throughput_per_sec"] = round(len(samples) / elapsed, 1)
        else:
            result["error"] = f"Unknown embedding impl: {impl_id}"
            return result

        mem_after = proc.memory_info().rss / (1024 * 1024)
        result["memory_mb"] = round(mem_after - mem_before, 1)
    except Exception as e:
        result["error"] = str(e)
        logger.warning("benchmark_embedding %s: %s", impl_id, e)
    return result


def benchmark_reranker(impl_id: str, n_pairs: int = 20) -> dict[str, Any]:
    """
    Benchmark reranker implementation. Returns latency_ms, throughput_per_sec, memory_mb.
    """
    result: dict[str, Any] = {"latency_ms": None, "throughput_per_sec": None, "memory_mb": None, "error": None}
    try:
        import psutil
        proc = psutil.Process()
        mem_before = proc.memory_info().rss / (1024 * 1024)

        if impl_id in ("cross_encoder", "sentence_transformers"):
            from layla.memory.vector_store import rerank
            pairs = [("query " + str(i), "document content for reranking " + str(i)) for i in range(min(n_pairs, 15))]
            start = time.perf_counter()
            rerank("benchmark query", [{"content": p[1]} for p in pairs], k=5)
            elapsed = time.perf_counter() - start
            result["latency_ms"] = round(elapsed * 1000, 2)
            result["throughput_per_sec"] = round(1.0 / elapsed if elapsed > 0 else 0, 1)
        else:
            result["error"] = f"Unknown reranker impl: {impl_id}"
            return result

        mem_after = proc.memory_info().rss / (1024 * 1024)
        result["memory_mb"] = round(mem_after - mem_before, 1)
    except Exception as e:
        result["error"] = str(e)
        logger.warning("benchmark_reranker %s: %s", impl_id, e)
    return result


def benchmark_web_scraper(impl_id: str, n_fetches: int = 5) -> dict[str, Any]:
    """
    Benchmark web scraper implementation. Uses minimal HTML. Returns latency_ms, throughput_per_sec, memory_mb.
    """
    result: dict[str, Any] = {"latency_ms": None, "throughput_per_sec": None, "memory_mb": None, "error": None}
    sample_html = "<html><body><article><p>Sample article text for benchmark extraction.</p></article></body></html>"
    try:
        import psutil
        proc = psutil.Process()
        mem_before = proc.memory_info().rss / (1024 * 1024)

        if impl_id == "trafilatura":
            from trafilatura import extract
            start = time.perf_counter()
            for _ in range(min(n_fetches, 10)):
                extract(sample_html)
            elapsed = time.perf_counter() - start
            result["latency_ms"] = round((elapsed / min(n_fetches, 10)) * 1000, 2)
            result["throughput_per_sec"] = round(min(n_fetches, 10) / elapsed, 1)
        elif impl_id == "beautifulsoup":
            from bs4 import BeautifulSoup
            start = time.perf_counter()
            for _ in range(min(n_fetches, 10)):
                soup = BeautifulSoup(sample_html, "html.parser")
                soup.get_text()
            elapsed = time.perf_counter() - start
            result["latency_ms"] = round((elapsed / min(n_fetches, 10)) * 1000, 2)
            result["throughput_per_sec"] = round(min(n_fetches, 10) / elapsed, 1)
        else:
            result["error"] = f"Unknown web_scraper impl: {impl_id}"
            return result

        mem_after = proc.memory_info().rss / (1024 * 1024)
        result["memory_mb"] = round(mem_after - mem_before, 1)
    except Exception as e:
        result["error"] = str(e)
        logger.warning("benchmark_web_scraper %s: %s", impl_id, e)
    return result


def benchmark_vector_search(impl_id: str, n_queries: int = 20) -> dict[str, Any]:
    """
    Benchmark vector search implementation.
    """
    result: dict[str, Any] = {"latency_ms": None, "throughput_per_sec": None, "memory_mb": None, "error": None}
    try:
        import psutil
        proc = psutil.Process()
        mem_before = proc.memory_info().rss / (1024 * 1024)

        if impl_id == "chromadb":
            from layla.memory.vector_store import _get_chroma_collection, embed
            coll = _get_chroma_collection()
            if coll.count() < 5:
                # Seed minimal data
                for i in range(5):
                    vec = embed(f"benchmark seed {i}").tolist()
                    coll.upsert(ids=[f"bench_{i}"], embeddings=[vec], documents=[f"doc {i}"], metadatas=[{}])
            qvec = embed("benchmark query").tolist()
            start = time.perf_counter()
            for _ in range(min(n_queries, 20)):
                coll.query(query_embeddings=[qvec], n_results=3)
            elapsed = time.perf_counter() - start
            result["latency_ms"] = round((elapsed / min(n_queries, 20)) * 1000, 2)
            result["throughput_per_sec"] = round(min(n_queries, 20) / elapsed, 1)
        else:
            result["error"] = f"Unknown vector_search impl: {impl_id}"
            return result

        mem_after = proc.memory_info().rss / (1024 * 1024)
        result["memory_mb"] = round(mem_after - mem_before, 1)
    except Exception as e:
        result["error"] = str(e)
        logger.warning("benchmark_vector_search %s: %s", impl_id, e)
    return result


def run_benchmark(capability: str, implementation_id: str, package_name: str) -> dict[str, Any]:
    """
    Run benchmark for a capability implementation. Stores results in DB.
    Returns {ok, latency_ms, throughput_per_sec, memory_mb, error}.
    """
    result: dict[str, Any] = {"ok": False, "latency_ms": None, "throughput_per_sec": None, "memory_mb": None, "error": None}
    bench_fn = {
        "embedding": benchmark_embedding,
        "vector_search": benchmark_vector_search,
        "reranker": benchmark_reranker,
        "web_scraper": benchmark_web_scraper,
    }.get(capability)
    if not bench_fn:
        result["error"] = f"No benchmark for capability: {capability}"
        return result

    data = bench_fn(implementation_id)
    if data.get("error"):
        result["error"] = data["error"]
        return result

    result["ok"] = True
    result["latency_ms"] = data.get("latency_ms")
    result["throughput_per_sec"] = data.get("throughput_per_sec")
    result["memory_mb"] = data.get("memory_mb")

    try:
        import json
        _, upsert = _get_db()
        upsert(
            capability_name=capability,
            implementation_id=implementation_id,
            package_name=package_name,
            status="benchmarked",
            latency_ms=result["latency_ms"],
            throughput_per_sec=result["throughput_per_sec"],
            memory_mb=result["memory_mb"],
            benchmark_results=json.dumps(data),
            sandbox_valid=True,
        )
    except Exception as e:
        logger.warning("benchmark_suite store result: %s", e)

    return result


def get_stored_benchmarks(capability: str | None = None) -> list[dict]:
    """Return stored benchmark results from DB."""
    try:
        from layla.memory.db import list_capability_implementations
        return list_capability_implementations(capability)
    except Exception:
        return []

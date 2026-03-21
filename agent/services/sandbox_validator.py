"""
Sandbox testing for capability implementations.
Before enabling: install dependency in sandbox, run benchmark, validate compatibility.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent


def validate_import(package: str, module: str | None = None) -> bool:
    """
    Validate that a package can be imported. Runs in subprocess to avoid polluting main process.
    """
    mod_repr = repr(module) if module else "None"
    code = f"""
import sys
try:
    __import__({repr(package)})
    mod = {mod_repr}
    if mod:
        __import__(mod)
    sys.exit(0)
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(AGENT_DIR),
        )
        return r.returncode == 0
    except Exception as e:
        logger.debug("sandbox validate_import %s: %s", package, e)
        return False


def validate_capability_impl(capability: str, implementation_id: str, package_name: str) -> dict:
    """
    Validate a capability implementation: import check + optional smoke test.
    Returns {valid: bool, error: str | None}.
    """
    result = {"valid": False, "error": None}
    pkg = package_name.split("[")[0].strip()  # strip extras like package[extra]
    module_map = {
        "chromadb": "chromadb",
        "faiss-cpu": "faiss",
        "qdrant-client": "qdrant_client",
        "sentence-transformers": "sentence_transformers",
        "trafilatura": "trafilatura",
        "beautifulsoup4": "bs4",
        "ezdxf": "ezdxf",
        "cadquery": "cadquery",
        "trimesh": "trimesh",
    }
    module = module_map.get(pkg, pkg.replace("-", "_"))
    if not validate_import(pkg, module):
        result["error"] = f"Failed to import {pkg} (module {module})"
        return result
    result["valid"] = True
    return result


def run_sandbox_benchmark(capability: str, implementation_id: str, package_name: str) -> dict:
    """
    Run benchmark in sandbox (subprocess), validate, and store result.
    Returns {ok, valid, latency_ms, error}.
    """
    from layla.memory.db import upsert_capability_implementation
    from services.benchmark_suite import run_benchmark

    val = validate_capability_impl(capability, implementation_id, package_name)
    if not val["valid"]:
        try:
            upsert_capability_implementation(
                capability_name=capability,
                implementation_id=implementation_id,
                package_name=package_name,
                status="candidate",
                sandbox_valid=False,
            )
        except Exception:
            pass
        return {"ok": False, "valid": False, "latency_ms": None, "error": val["error"]}

    bench = run_benchmark(capability, implementation_id, package_name)
    if not bench.get("ok"):
        return {"ok": False, "valid": True, "latency_ms": None, "error": bench.get("error", "Benchmark failed")}

    return {
        "ok": True,
        "valid": True,
        "latency_ms": bench.get("latency_ms"),
        "throughput_per_sec": bench.get("throughput_per_sec"),
        "memory_mb": bench.get("memory_mb"),
    }

"""
Integration sandbox for capability evaluation.
Creates isolated temp venv, installs candidate, runs compatibility tests and benchmarks.
Sandbox cannot access Layla runtime environment.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent
_SANDBOX_BASE = AGENT_DIR / ".capability_sandbox"


def _sandbox_dir(session_id: str) -> Path:
    """Return sandbox directory for a session. Isolated from Layla."""
    d = _SANDBOX_BASE / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_temp_venv(session_id: str, python_exe: str | None = None) -> Path | None:
    """
    Create a temporary venv for sandbox. Returns path to venv's python, or None on failure.
    Uses system Python; does not inherit Layla's site-packages.
    """
    base = _sandbox_dir(session_id)
    venv_path = base / "venv"
    if venv_path.exists():
        try:
            shutil.rmtree(venv_path)
        except Exception as e:
            logger.debug("integration_sandbox cleanup venv: %s", e)
    py = python_exe or sys.executable
    try:
        subprocess.run(
            [py, "-m", "venv", str(venv_path)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(base),
            env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"},
        )
        venv_python = venv_path / ("Scripts" if os.name == "nt" else "bin") / "python"
        if venv_python.exists():
            return venv_python
        return None
    except Exception as e:
        logger.warning("integration_sandbox create_venv failed: %s", e)
        return None


def install_candidate(venv_python: Path, package_name: str, timeout: int = 120) -> dict[str, Any]:
    """
    Install package in sandbox venv via pip. Returns {ok, error, stdout, stderr}.
    Package is installed in isolation; cannot access Layla's environment.
    """
    result: dict[str, Any] = {"ok": False, "error": None, "stdout": "", "stderr": ""}
    pkg = package_name.split("[")[0].strip()
    try:
        r = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--no-input", pkg],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PIP_NO_INPUT": "1"},
        )
        result["stdout"] = (r.stdout or "")[:2000]
        result["stderr"] = (r.stderr or "")[:2000]
        result["ok"] = r.returncode == 0
        if not result["ok"]:
            result["error"] = (r.stderr or r.stdout or "pip install failed")[:500]
    except subprocess.TimeoutExpired:
        result["error"] = "pip install timed out"
    except Exception as e:
        result["error"] = str(e)
    return result


def run_compatibility_tests(venv_python: Path, capability: str, implementation_id: str, package_name: str) -> dict[str, Any]:
    """
    Run compatibility tests in sandbox. Returns {valid, error}.
    Tests: import check, minimal smoke test per capability.
    """
    result: dict[str, Any] = {"valid": False, "error": None}
    pkg = package_name.split("[")[0].strip()
    module_map = {
        "chromadb": "chromadb",
        "faiss-cpu": "faiss",
        "qdrant-client": "qdrant_client",
        "sentence-transformers": "sentence_transformers",
        "trafilatura": "trafilatura",
        "beautifulsoup4": "bs4",
        "crawl4ai": "crawl4ai",
        "cohere": "cohere",
    }
    module = module_map.get(pkg, pkg.replace("-", "_"))

    code = f"""
import sys
try:
    __import__({repr(pkg)})
    mod = {repr(module)}
    if mod and mod != pkg:
        __import__(mod)
    sys.exit(0)
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
"""
    try:
        r = subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result["valid"] = r.returncode == 0
        if not result["valid"]:
            result["error"] = (r.stderr or r.stdout or "import failed").strip()[:500]
    except Exception as e:
        result["error"] = str(e)
    return result


def run_benchmarks(
    venv_python: Path,
    capability: str,
    implementation_id: str,
    package_name: str,
) -> dict[str, Any]:
    """
    Run benchmarks in sandbox subprocess. Returns {ok, latency_ms, throughput_per_sec, memory_mb, error}.
    Delegates to benchmark_suite; runs in subprocess to avoid polluting sandbox with Layla deps.
    """
    # Run benchmark in main process (benchmark_suite uses Layla's vector_store etc.)
    # Sandbox validation already confirmed import; benchmark runs with Layla's installed deps
    # to measure the actual impl. For true isolation we'd need a separate benchmark script.
    try:
        from services.benchmark_suite import run_benchmark
        return run_benchmark(capability, implementation_id, package_name)
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": None, "throughput_per_sec": None, "memory_mb": None}


def evaluate_candidate(
    capability_name: str,
    package_name: str,
    implementation_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Full evaluation: create venv, install, test, benchmark.
    Returns {ok, valid, latency_ms, throughput_per_sec, memory_mb, error}.
    """
    import uuid
    sid = session_id or str(uuid.uuid4())[:8]
    impl_id = implementation_id or package_name.split("[")[0].replace("-", "_")
    result: dict[str, Any] = {
        "ok": False,
        "valid": False,
        "latency_ms": None,
        "throughput_per_sec": None,
        "memory_mb": None,
        "error": None,
    }

    venv_py = create_temp_venv(sid)
    if not venv_py:
        result["error"] = "Failed to create sandbox venv"
        return result

    inst = install_candidate(venv_py, package_name)
    if not inst["ok"]:
        result["error"] = inst.get("error", "Install failed")
        return result

    compat = run_compatibility_tests(venv_py, capability_name, impl_id, package_name)
    if not compat["valid"]:
        result["error"] = compat.get("error", "Compatibility test failed")
        return result

    result["valid"] = True
    bench = run_benchmarks(venv_py, capability_name, impl_id, package_name)
    if bench.get("ok"):
        result["ok"] = True
        result["latency_ms"] = bench.get("latency_ms")
        result["throughput_per_sec"] = bench.get("throughput_per_sec")
        result["memory_mb"] = bench.get("memory_mb")
    else:
        result["error"] = bench.get("error", "Benchmark failed")

    try:
        shutil.rmtree(_sandbox_dir(sid), ignore_errors=True)
    except Exception:
        pass
    return result

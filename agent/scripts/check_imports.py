# -*- coding: utf-8 -*-
"""
check_imports.py — Validate that all top-level Python imports in the Layla
agent package resolve without errors.

Strategy:
  1. Collect every `import X` / `from X import Y` statement at module level
     from all .py files (excluding venv, __pycache__, test fixtures).
  2. Attempt importlib.util.find_spec() for each unique top-level package.
  3. Report any that cannot be found — these are either missing dependencies
     or stale references to renamed/deleted modules.

Usage:
    cd agent/ && python scripts/check_imports.py
    echo $?   # 0 = all found, 1 = missing imports
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", "models",
             "chroma_db", "layla.egg-info", "build", "dist",
             "fabrication_assist", "openclaude-main", "claw-code-main",
             "discord_bot", "integrations", "cursor-layla-mcp"}

# These are optional/conditional dependencies — warn but don't fail
OPTIONAL_PACKAGES = {
    # AI / inference
    "llama_cpp", "chromadb", "anthropic", "openai", "sentence_transformers",
    "kokoro_onnx", "pyttsx3", "soundfile", "sounddevice", "onnxruntime",
    "whisper", "pyaudio", "git", "playwright", "langfuse", "elasticsearch",
    "torch", "transformers", "scipy", "sklearn", "numpy", "pandas",
    "PIL", "cv2", "faiss", "psutil", "setproctitle", "outlines",
    # Intelligence enhancement (Phase 6) — all optional install-time extras
    "airllm",           # AirLLM layer-by-layer large model inference
    "llmlingua",        # LLMLingua / LongLLMLingua prompt compression
    "dspy",             # DSPy programmatic prompt optimisation
    "guidance",         # guidance constrained generation
    "graphrag",         # Microsoft GraphRAG knowledge graph
    "knowledge_storm",  # Stanford STORM article synthesis
    "unstructured",     # Unstructured.io document parsing (PDF/DOCX/HTML)
    "pypdf",            # Lightweight PDF fallback
    "selective_context","context_cite",  # Token pruning / attribution (Phase 8)
    # NLP
    "spacy", "textblob", "loguru", "tree_sitter", "tree_sitter_python",
    # CAD / engineering (FreeCAD, Blender, etc.) — only present when those tools installed
    "FreeCAD", "FreeCADGui", "OCC", "Part", "PySide", "PySide2",
    "cadquery", "ezdxf", "rhino3dm", "trimesh", "svgwrite", "rectpack",
    "opencamlib", "bpy", "bmesh", "mathutils",
    # Fabrication assist internal (these are in fabrication_assist/ subdirectory)
    "ai", "bim", "commands", "demo_browser_viewer", "design", "fab",
    "fabrication_assist", "fea", "generators", "geom", "joints", "lifecycle",
    "product", "solver", "standards", "structural", "system", "ui_config", "worklist",
    # Observability (Phase 3) — optional, graceful fallback
    "prometheus_client",   # Prometheus metrics (fallback: internal dict counters)
    "structlog",           # Structured logging (fallback: stdlib logging)
    # Misc optional
    "ffmpeg", "geopy", "icalendar", "pyautogui", "pyperclip", "pytesseract",
    "qrcode", "scenedetect", "ultralytics", "pandas_datareader", "tomli",
    "hosts",
}

# Internal top-level packages (always resolvable if AGENT_DIR in path)
INTERNAL_PACKAGES = {
    "layla", "services", "routers", "core", "runtime_safety",
    "agent_loop", "main", "config_schema", "decision_schema",
    "execution_state", "shared_state", "version",
}


def _extract_imports(path: Path) -> list[str]:
    """Return list of top-level package names imported in path."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute imports only
                names.append(node.module.split(".")[0])
    return names


def _py_files():
    for f in AGENT_DIR.rglob("*.py"):
        if any(p in f.parts for p in SKIP_DIRS):
            continue
        if "tests" in f.parts:
            continue  # skip test fixtures; they have extra deps
        yield f


def run():
    print("=" * 60)
    print("Import Resolver Check")
    print("=" * 60)

    all_imports: set[str] = set()
    for f in _py_files():
        all_imports.update(_extract_imports(f))

    # Filter stdlib
    import sys as _sys
    stdlib = set(_sys.stdlib_module_names) if hasattr(_sys, "stdlib_module_names") else set()

    missing: list[str] = []
    optional_missing: list[str] = []
    checked = 0

    for pkg in sorted(all_imports):
        if pkg in stdlib:
            continue
        if pkg in INTERNAL_PACKAGES:
            continue
        checked += 1
        spec = importlib.util.find_spec(pkg)
        if spec is None:
            if pkg in OPTIONAL_PACKAGES:
                optional_missing.append(pkg)
            else:
                missing.append(pkg)

    print(f"  Packages checked: {checked}")
    if optional_missing:
        print(f"\n  OPTIONAL (not installed — features degraded gracefully):")
        for p in optional_missing:
            print(f"    - {p}")
    if missing:
        print(f"\n  MISSING (hard dependency — will raise ImportError at runtime):")
        for p in missing:
            print(f"    FAIL: {p}")
        print(f"\nFAIL: {len(missing)} hard missing import(s)")
        return 1
    else:
        print(f"\n  All hard dependencies resolvable.")
        if optional_missing:
            print(f"  {len(optional_missing)} optional package(s) not installed (expected).")
        print("PASS")
        return 0


if __name__ == "__main__":
    sys.exit(run())

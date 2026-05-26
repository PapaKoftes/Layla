"""
Optional dependency recovery: try allowlisted pip installs, then return structured errors
with exact install commands and doc pointers so setup stays seamless.

Governed by runtime_config.json: auto_pip_install_optional (default False — use installer or manual pip).
Set to true only on trusted machines for convenience. Only packages in _PIP_ALLOWLIST may be installed automatically.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_DIR = Path(__file__).resolve().parent.parent

# Pip package names allowed for automatic install (security: no arbitrary packages).
_PIP_ALLOWLIST: frozenset[str] = frozenset(
    {
        "faster-whisper",
        "kokoro-onnx",
        "soundfile",
        "pyttsx3",
        "llama-cpp-python",
        "PyMuPDF",
        "pypdf",
        "trafilatura",
        "duckduckgo-search",
        "arxiv",
        "wikipedia-api",
        "sympy",
        "pyperclip",
        "easyocr",
        "pytesseract",
        "Pillow",
        "matplotlib",
        "python-docx",
        "trimesh",
        "sounddevice",
    }
)

_pip_lock = threading.Lock()

# Human-oriented pointers (no hardcoded external URLs; repo is source of truth).
DOCS = {
    "models_gguf": "MODELS.md (repo root) — which GGUF to download and where to put it",
    "install": "INSTALL.bat (Windows) or install.sh (Linux/macOS) at repo root",
    "first_run": "agent/first_run.py — hardware wizard; writes agent/runtime_config.json",
    "diagnose": "Run from repo root: cd agent && python diagnose_startup.py",
    "doctor": "With server up: GET http://127.0.0.1:8000/doctor or: python layla.py doctor",
    "requirements": "agent/requirements.txt — full dependency list",
    "voice": "agent/runtime_config.example.json — whisper_model, tts_voice",
}

FEATURES: dict[str, dict[str, Any]] = {
    "faster_whisper": {
        "pip": ["faster-whisper"],
        "imports": ["faster_whisper"],
        "label": "Speech-to-text (faster-whisper)",
        "detail": (
            "The Whisper *weight* file downloads automatically on first use (~50–500 MB) "
            "into the Hugging Face cache after the Python package is installed."
        ),
    },
    "kokoro_tts": {
        "pip": ["kokoro-onnx", "soundfile"],
        "imports": ["kokoro_onnx", "soundfile"],
        "label": "Text-to-speech (kokoro-onnx)",
        "detail": "Kokoro ONNX weights download on first synthesis (~80 MB).",
    },
    "pyttsx3_tts": {
        "pip": ["pyttsx3"],
        "imports": ["pyttsx3"],
        "label": "Text-to-speech fallback (system voice via pyttsx3)",
        "detail": "Uses OS speech APIs; lower quality than kokoro-onnx but no large download.",
    },
    "llama_cpp": {
        "pip": ["llama-cpp-python"],
        "imports": ["llama_cpp"],
        "label": "Local GGUF inference (llama-cpp-python)",
        "detail": (
            "Windows: install Visual Studio Build Tools (C++ workload). "
            "Linux: build-essential, cmake. macOS: Xcode CLI tools. "
            "Then: pip may compile from source; see llama-cpp-python docs if wheels fail."
        ),
    },
}


def _auto_pip_enabled(cfg: dict | None) -> bool:
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            return False
    v = cfg.get("auto_pip_install_optional")
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on")


def pip_install_command(packages: list[str]) -> str:
    q = " ".join(packages)
    return f'{sys.executable} -m pip install {q}'


def try_pip_install(packages: list[str], timeout_sec: int = 180) -> dict[str, Any]:
    """
    Run pip install for allowlisted packages only. Returns ok, returncode, stderr tail.
    """
    out: dict[str, Any] = {
        "ok": False,
        "packages": list(packages),
        "returncode": -1,
        "stderr": "",
        "stdout": "",
        "command": pip_install_command(packages),
    }
    bad = [p for p in packages if p not in _PIP_ALLOWLIST]
    if bad:
        out["error"] = f"Refused non-allowlisted packages (safety): {bad}"
        return out
    if not packages:
        out["error"] = "No packages to install"
        return out

    cmd = [sys.executable, "-m", "pip", "install", *packages]
    with _pip_lock:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=str(REPO_ROOT),
            )
            out["returncode"] = proc.returncode
            out["stdout"] = (proc.stdout or "")[-4000:]
            out["stderr"] = (proc.stderr or "")[-4000:]
            out["ok"] = proc.returncode == 0
            if not out["ok"]:
                out["error"] = out["stderr"] or out["stdout"] or f"pip exited {proc.returncode}"
        except subprocess.TimeoutExpired:
            out["error"] = f"pip install timed out after {timeout_sec}s"
        except Exception as e:
            out["error"] = str(e)
    if out["ok"]:
        logger.info("dependency_recovery: pip install ok: %s", packages)
    else:
        logger.warning("dependency_recovery: pip install failed: %s — %s", packages, out.get("error", ""))
    return out


def _imports_available(import_names: list[str]) -> bool:
    for name in import_names:
        try:
            __import__(name)
        except ImportError:
            return False
        except Exception:
            return False
    return True


def ensure_feature(feature_id: str, cfg: dict | None = None) -> tuple[bool, dict[str, Any] | None]:
    """
    Ensure all imports for a feature exist. Optionally run allowlisted pip install
    when auto_pip_install_optional is true, then re-check imports.

    Returns (success, recovery_dict_or_none). recovery_dict is always returned on failure.
    """
    spec = FEATURES.get(feature_id)
    if not spec:
        return False, {
            "feature": feature_id,
            "error": "Unknown feature id",
            "docs": DOCS,
        }

    import_names: list[str] = list(spec["imports"])
    pip_names: list[str] = list(spec["pip"])
    label = str(spec.get("label") or feature_id)
    detail = str(spec.get("detail") or "")

    if _imports_available(import_names):
        return True, None

    recovery: dict[str, Any] = {
        "feature": feature_id,
        "label": label,
        "what_failed": f"Missing Python package(s) for: {label}",
        "pip_packages": pip_names,
        "install_command": pip_install_command(pip_names),
        "detail": detail,
        "docs": {
            "requirements": DOCS["requirements"],
            "install_script": DOCS["install"],
            "diagnose": DOCS["diagnose"],
        },
        "pip_attempt": None,
    }

    if _auto_pip_enabled(cfg):
        recovery["pip_attempt"] = try_pip_install(pip_names)
        if recovery["pip_attempt"].get("ok") and _imports_available(import_names):
            logger.info("dependency_recovery: recovered feature %s after pip install", feature_id)
            return True, recovery
    else:
        recovery["note"] = (
            "Automatic pip install is off (auto_pip_install_optional=false in runtime_config.json). "
            "Run the install_command manually in the same Python environment as Layla."
        )

    recovery["next_steps"] = [
        f"1) In a terminal: {recovery['install_command']}",
        f"2) If that fails: {DOCS['diagnose']}",
        f"3) Full deps: {DOCS['requirements']}",
        f"4) Still stuck: {DOCS['doctor']}",
    ]
    return False, recovery


def missing_gguf_recovery(
    model_filename: str,
    models_dir: Path,
    *,
    resolved_path: Path | None = None,
) -> dict[str, Any]:
    """Structured guidance when no valid GGUF is on disk."""
    fn = (model_filename or "").strip() or "(not set)"
    md = models_dir.resolve() if models_dir else REPO_ROOT / "models"
    exists = md.exists()
    ggufs = sorted(p.name for p in md.glob("*.gguf")) if exists else []

    return {
        "what_failed": "No usable GGUF model file for inference",
        "model_filename_config": fn,
        "models_dir": str(md),
        "models_dir_exists": exists,
        "gguf_files_found": ggufs[:20],
        "next_steps": [
            f"1) Download a .gguf (see {DOCS['models_gguf']}) into: {md}",
            "2) Set model_filename in agent/runtime_config.json to that file's basename",
            f"3) Or run: {DOCS['first_run']}",
            f"4) Verify: {DOCS['diagnose']}",
        ],
        "docs": {"models": DOCS["models_gguf"], "install": DOCS["install"]},
    }


def llama_cpp_import_recovery(exc: str | None = None) -> dict[str, Any]:
    r = {
        "what_failed": "llama_cpp (llama-cpp-python) is not importable",
        "pip_packages": ["llama-cpp-python"],
        "install_command": pip_install_command(["llama-cpp-python"]),
        "detail": FEATURES["llama_cpp"]["detail"],
        "exception": exc or "",
        "next_steps": [
            f"1) {pip_install_command(['llama-cpp-python'])}",
            f"2) {DOCS['diagnose']}",
            f"3) {DOCS['install']} (installs toolchain + deps)",
            f"4) {DOCS['doctor']}",
        ],
        "docs": {"requirements": DOCS["requirements"]},
    }
    return r


def get_optional_features(cfg: dict | None = None) -> list[dict[str, Any]]:
    """List known optional feature bundles and whether imports resolve."""
    if cfg is None:
        try:
            import runtime_safety

            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}
    out: list[dict[str, Any]] = []
    for fid, spec in FEATURES.items():
        pip_names = list(spec.get("pip") or [])
        import_names = list(spec.get("imports") or [])
        installed = _imports_available(import_names)
        out.append(
            {
                "id": fid,
                "label": str(spec.get("label") or fid),
                "installed": installed,
                "pip": pip_names,
                "detail": str(spec.get("detail") or ""),
                "auto_pip_enabled": _auto_pip_enabled(cfg),
            }
        )
    return out


def install_feature(feature_id: str, cfg: dict | None = None) -> dict[str, Any]:
    """
    Run allowlisted pip install for a feature id. Does not require auto_pip_install_optional
    (operator explicitly requested install via UI/API).
    """
    spec = FEATURES.get((feature_id or "").strip())
    if not spec:
        return {"ok": False, "error": "unknown_feature", "feature": feature_id}
    pip_names = list(spec.get("pip") or [])
    import_names = list(spec.get("imports") or [])
    if _imports_available(import_names):
        return {"ok": True, "already_installed": True, "feature": feature_id}
    attempt = try_pip_install(pip_names)
    ok = bool(attempt.get("ok")) and _imports_available(import_names)
    return {"ok": ok, "feature": feature_id, "pip_attempt": attempt}


def merge_recovery_message(d: dict[str, Any]) -> str:
    """Single string for logs or simple error fields."""
    parts = [d.get("what_failed") or d.get("error") or "Setup incomplete"]
    if d.get("install_command"):
        parts.append(f"Try: {d['install_command']}")
    ns = d.get("next_steps")
    if isinstance(ns, list) and ns:
        parts.append(ns[0])
    return " | ".join(str(p) for p in parts if p)

#!/usr/bin/env python3
"""
Layla first-time setup and runtime validation.

Creates .venv under the repo root, installs agent/requirements.txt, validates Chroma/embeddings,
merges minimal runtime_config keys from the example template, and normalizes path strings on Windows.

Run from repo root:
  python scripts/setup_layla.py
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
REQ_FILE = AGENT_DIR / "requirements.txt"
RUNTIME_CFG = AGENT_DIR / "runtime_config.json"
RUNTIME_EXAMPLE = AGENT_DIR / "runtime_config.example.json"

_OPTIONAL_IMPORTS = ("fastapi", "uvicorn", "sentence_transformers", "chromadb")

# Mirror layla.memory.vector_store CHROMA_PATH without importing layla in the parent process.
_CHROMA_DB_DIR = AGENT_DIR / "layla" / "memory" / "chroma_db"

_PIP_NAME = {
    "sentence_transformers": "sentence-transformers",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "chromadb": "chromadb",
}


def _venv_python(repo: Path) -> Path:
    if sys.platform == "win32":
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def _venv_pip(repo: Path) -> Path:
    if sys.platform == "win32":
        return repo / ".venv" / "Scripts" / "pip.exe"
    return repo / ".venv" / "bin" / "pip"


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> int:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env)
    return int(r.returncode)


def _ensure_venv(repo: Path) -> Path:
    vpy = _venv_python(repo)
    if vpy.exists():
        return vpy
    print("[setup] Creating virtual environment at .venv …")
    rc = _run([sys.executable, "-m", "venv", str(repo / ".venv")], cwd=repo)
    if rc != 0:
        raise SystemExit("Failed to create .venv")
    if not vpy.exists():
        raise SystemExit(f"venv python missing after creation: {vpy}")
    return vpy


def _pip_install_requirements(repo: Path, pip_exe: Path) -> None:
    print("[setup] pip install -r agent/requirements.txt …")
    rc = _run(
        [str(pip_exe), "install", "--upgrade", "pip"],
        cwd=repo,
        env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
    )
    if rc != 0:
        raise SystemExit("pip upgrade failed")
    rc = _run(
        [str(pip_exe), "install", "-r", str(REQ_FILE)],
        cwd=repo,
        env=os.environ.copy(),
    )
    if rc != 0:
        raise SystemExit("pip install -r agent/requirements.txt failed")


def _verify_imports(py: Path) -> None:
    print("[setup] Verifying core imports …")
    base = [
        str(py),
        "-c",
        "import sqlite3, threading, concurrent.futures; "
        + "; ".join(f"import {m}" for m in _OPTIONAL_IMPORTS),
    ]
    if _run(base, cwd=AGENT_DIR) != 0:
        pip = _venv_pip(REPO_ROOT)
        for mod in _OPTIONAL_IMPORTS:
            print(f"[setup] retry pip install for {mod} …")
            pkg = _PIP_NAME.get(mod, mod)
            _run([str(pip), "install", pkg], cwd=REPO_ROOT)
        if _run(base, cwd=AGENT_DIR) != 0:
            raise SystemExit("Import verification failed after retries.")


def _deep_merge_missing(dst: dict, defaults: dict) -> bool:
    changed = False
    for k, v in defaults.items():
        if k.startswith("_"):
            continue
        if k not in dst or dst[k] is None:
            dst[k] = json.loads(json.dumps(v)) if isinstance(v, (dict, list)) else v
            changed = True
    return changed


def _normalize_path_keys(cfg: dict) -> bool:
    changed = False
    for key in ("models_dir", "sandbox_root"):
        if key not in cfg or not isinstance(cfg[key], str):
            continue
        raw = cfg[key].strip()
        if not raw:
            continue
        try:
            n = str(Path(raw).expanduser())
        except Exception:
            continue
        if n != cfg[key]:
            cfg[key] = n
            changed = True
    return changed


def _ensure_runtime_config() -> dict:
    if not RUNTIME_EXAMPLE.is_file():
        raise SystemExit(f"Missing template: {RUNTIME_EXAMPLE}")
    example = json.loads(RUNTIME_EXAMPLE.read_text(encoding="utf-8"))
    if not RUNTIME_CFG.is_file():
        print(f"[setup] Creating {RUNTIME_CFG.name} from example …")
        shutil.copy2(RUNTIME_EXAMPLE, RUNTIME_CFG)
    cfg = json.loads(RUNTIME_CFG.read_text(encoding="utf-8"))
    if _deep_merge_missing(cfg, example):
        print("[setup] Merged missing keys from runtime_config.example.json …")
    if _normalize_path_keys(cfg):
        print("[setup] Normalized path fields …")
    RUNTIME_CFG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


def _reload_cfg() -> dict:
    return json.loads(RUNTIME_CFG.read_text(encoding="utf-8"))


def _persist_cfg(cfg: dict) -> None:
    RUNTIME_CFG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _resolve_model_file(cfg: dict) -> Path | None:
    try:
        sys.path.insert(0, str(AGENT_DIR))
        import runtime_safety  # noqa: WPS433

        p = runtime_safety.resolve_model_path(cfg)
        return Path(p) if p else None
    except Exception:
        return None


def _resolve_model_file_with_retry(cfg: dict, *, attempts: int = 5) -> Path | None:
    """Windows FS can be briefly inconsistent after rename; retry Path.exists()."""
    for _ in range(attempts):
        p = _resolve_model_file(cfg)
        if p and p.is_file():
            return p
        time.sleep(0.5)
    return None


def _normalize_model_filename_in_cfg(cfg: dict) -> None:
    mf = cfg.get("model_filename")
    if mf and isinstance(mf, str) and (Path(mf).is_absolute() or "/" in mf or "\\" in mf):
        bn = Path(mf).name
        print(f"[setup] WARNING: model_filename must be a basename — normalizing to {bn!r}")
        cfg["model_filename"] = bn
    av = cfg.get("available_models")
    if isinstance(av, list):
        cfg["available_models"] = list(
            dict.fromkeys(Path(str(x)).name for x in av if x),
        )


def _model_exists(cfg: dict) -> bool:
    p = _resolve_model_file_with_retry(cfg)
    return bool(p and p.is_file())


def _print_hardware_one_line() -> None:
    try:
        path = REPO_ROOT / "scripts" / "hardware_detect.py"
        spec = importlib.util.spec_from_file_location("layla_hw", path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            s = mod.summarize_hardware()
            pub = {k: v for k, v in s.items() if not str(k).startswith("_")}
            print(
                "[setup] Hardware:",
                f"RAM ~{pub.get('ram_gb', '?')} GiB",
                f"GPU {pub.get('gpu', '?')}",
                f"VRAM {pub.get('gpu_vram_gb')}",
            )
    except Exception as e:
        print(f"[setup] Hardware probe skipped: {e}")


def _run_model_selector(interactive: bool) -> tuple[bool, str]:
    path = REPO_ROOT / "scripts" / "model_selector.py"
    spec = importlib.util.spec_from_file_location("layla_model_selector", path)
    if spec is None or spec.loader is None:
        print("[setup] ERROR: model_selector.py not found.")
        return False, "aborted"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_model_selection(interactive=interactive)


def _chroma_smoke(py: Path) -> tuple[bool, str]:
    code = r"""
import sys
sys.path.insert(0, sys.argv[1])
from layla.memory import vector_store as vs
vs.reset_chroma_clients()
if not vs._use_chroma():
    print("chromadb import failed")
    sys.exit(2)
c = vs._get_chroma_collection()
n = c.count()
k = vs._get_knowledge_collection()
_ = k.count()
print("ok", n)
"""
    r = subprocess.run(
        [str(py), "-c", code, str(AGENT_DIR)],
        cwd=str(AGENT_DIR),
        capture_output=True,
        text=True,
    )
    return (r.returncode == 0, (r.stdout or "") + (r.stderr or ""))


def _repair_chroma(py: Path, pip: Path) -> bool:
    print("[setup] Reinstalling chromadb …")
    _run([str(pip), "uninstall", "-y", "chromadb"], cwd=REPO_ROOT)
    _run([str(pip), "install", "chromadb"], cwd=REPO_ROOT)
    ok, msg = _chroma_smoke(py)
    if ok:
        return True
    print(f"[setup] WARN: Chroma still failing after reinstall: {msg.strip()}")
    if _CHROMA_DB_DIR.exists():
        print(f"[setup] WARN: Removing on-disk Chroma DB directory: {_CHROMA_DB_DIR}")
        shutil.rmtree(_CHROMA_DB_DIR, ignore_errors=True)
    ok2, msg2 = _chroma_smoke(py)
    if not ok2:
        print(f"[setup] ERROR: Chroma repair failed: {msg2.strip()}")
    return ok2


def _validate_chroma(
    py: Path,
    pip: Path,
    *,
    allow_repair: bool,
    strict: bool,
) -> bool:
    """Return True if semantic/Chroma layer is operational; else False (caller may disable use_chroma)."""
    print("[setup] Validating Chroma / vector_store …")
    ok, detail = _chroma_smoke(py)
    if ok:
        print("[setup] Chroma OK:", detail.strip())
        return True
    print("[setup] Chroma validation failed:", detail.strip())
    if not allow_repair:
        if strict:
            raise SystemExit(
                "Chroma did not initialize. Fix dependencies or re-run without --no-chroma-repair."
            )
        return False
    if not _repair_chroma(py, pip):
        if strict:
            raise SystemExit("Could not repair Chroma store.")
        return False
    print("[setup] Chroma OK after repair.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Layla environment setup and validation.")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip pip install (only validate venv + imports + chroma).",
    )
    parser.add_argument(
        "--no-chroma-repair",
        action="store_true",
        help="Do not reinstall chromadb or delete chroma_db on validation failure.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip pip install (still creates .venv if missing and runs import/chroma checks).",
    )
    parser.add_argument(
        "--strict-chroma",
        action="store_true",
        help="Exit with error if Chroma cannot be initialized (default: disable use_chroma and continue).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Non-interactive model selection (auto catalog pick).",
    )
    parser.add_argument(
        "--force-model",
        action="store_true",
        help="Always run model selection/download even if a GGUF is already configured.",
    )
    parser.add_argument(
        "--strict-model",
        action="store_true",
        help="Exit with error if model download/selection fails (default: warn and continue when possible).",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)
    if not AGENT_DIR.is_dir():
        print(f"ERROR: agent directory not found: {AGENT_DIR}")
        return 1

    skip_install = args.skip_install or args.validate_only
    noninteractive = args.yes or (os.environ.get("LAYLA_SETUP_NONINTERACTIVE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    model_ok = False
    chroma_ok = False

    try:
        py = _ensure_venv(REPO_ROOT)
        pip = _venv_pip(REPO_ROOT)
        if not skip_install:
            _pip_install_requirements(REPO_ROOT, pip)
        _verify_imports(py)

        cfg = _ensure_runtime_config()
        _normalize_model_filename_in_cfg(cfg)
        _persist_cfg(cfg)

        _print_hardware_one_line()

        had_model = _model_exists(cfg)
        if had_model and not args.force_model:
            rp0 = _resolve_model_file_with_retry(cfg)
            print(f"[setup] Model detected: {(rp0.name if rp0 else cfg.get('model_filename'))}")

        elif not had_model or args.force_model:
            if args.force_model and had_model:
                print("[setup] --force-model: re-running model selection.")
            else:
                print("[setup] No GGUF found for current config — starting model selection.")
            try:
                ok_sel, reason = _run_model_selector(interactive=not noninteractive)
            except RuntimeError as e:
                print(f"[setup] ERROR: {e}")
                raise SystemExit(1)
            cfg = _reload_cfg()
            _normalize_model_filename_in_cfg(cfg)
            _persist_cfg(cfg)
            if not ok_sel:
                print("[setup] WARNING: Model selection did not complete successfully.")
                if args.strict_model:
                    print("[setup] ERROR: Strict model mode — exiting.")
                    raise SystemExit(1)
                if reason == "download_failed":
                    print(
                        "[setup] Continuing without a new download — fix network or place a .gguf under models/, "
                        "then re-run setup."
                    )

        if _model_exists(cfg):
            model_ok = True
        else:
            if noninteractive:
                print(
                    "[setup] ERROR: No model found.\n"
                    "   Run interactively without --yes, or place a .gguf under models/ and set model_filename."
                )
            else:
                print(
                    "[setup] ERROR: No model found.\n"
                    "   Please download or select a model (re-run setup), or see MODELS.md."
                )

        chroma_ok = _validate_chroma(
            py,
            pip,
            allow_repair=not args.no_chroma_repair,
            strict=args.strict_chroma,
        )
        cfg = _reload_cfg()
        _normalize_model_filename_in_cfg(cfg)
        if not chroma_ok:
            cfg["use_chroma"] = False
            _persist_cfg(cfg)

        want_chroma = bool(chroma_ok and cfg.get("use_chroma", True))
        if want_chroma:
            os.environ.pop("LAYLA_CHROMA_DISABLED", None)
        else:
            os.environ["LAYLA_CHROMA_DISABLED"] = "1"

        if os.getenv("LAYLA_CHROMA_DISABLED") == "1":
            print("[setup] Semantic memory: DISABLED")
        else:
            print("[setup] Semantic memory: ENABLED")

        if model_ok:
            rp = _resolve_model_file_with_retry(cfg)
            print(f"[setup] Model ready: {(rp.name if rp else Path(cfg.get('model_filename') or '').name)}")

        print("[setup] Done.")
        return 0 if model_ok else 1
    except SystemExit as e:
        code = int(e.code) if isinstance(e.code, int) else 1
        raise SystemExit(code)


if __name__ == "__main__":
    raise SystemExit(main())

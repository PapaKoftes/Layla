#!/usr/bin/env python3
"""
Run setup validation, start the Layla server, print status, open the browser, and probe /health.

Usage (from repo root):
  python scripts/run_layla.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_layla.py"
AGENT_DIR = REPO_ROOT / "agent"
PENDING_MODEL_FILE = AGENT_DIR / ".layla_pending_model.json"
RUNTIME_CFG = AGENT_DIR / "runtime_config.json"


def _venv_python(repo: Path) -> Path:
    if sys.platform == "win32":
        return repo / ".venv" / "Scripts" / "python.exe"
    return repo / ".venv" / "bin" / "python"


def _load_cfg() -> dict:
    p = RUNTIME_CFG
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _wait_health(port: int, timeout_s: float = 120.0) -> dict:
    url = f"http://127.0.0.1:{port}/health?deep=true"
    deadline = time.monotonic() + timeout_s
    last_err = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                body = r.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = str(e)
            time.sleep(1.0)
    raise RuntimeError(f"/health did not become ready: {last_err}")


def _maybe_background_model_download() -> None:
    enabled = (os.environ.get("LAYLA_BACKGROUND_MODEL") or "").strip().lower() in ("1", "true", "yes")

    def worker() -> None:
        try:
            if not PENDING_MODEL_FILE.is_file():
                return
            raw = json.loads(PENDING_MODEL_FILE.read_text(encoding="utf-8"))
            want = (raw.get("name") or raw.get("model_name") or "").strip()
            if not want:
                return
            py = _venv_python(REPO_ROOT)
            code = (
                "import json,sys\n"
                "from pathlib import Path\n"
                "repo = Path(sys.argv[1])\n"
                "agent = repo / 'agent'\n"
                "sys.path.insert(0, str(agent))\n"
                "from install.model_selector import load_catalog, validate_catalog_entries\n"
                "from install.model_downloader import download_model, get_canonical_models_dir\n"
                "want = sys.argv[2]\n"
                "cfg_path = agent / 'runtime_config.json'\n"
                "cfg = json.loads(cfg_path.read_text(encoding='utf-8'))\n"
                "md_raw = cfg.get('models_dir') or ''\n"
                "models_dir = Path(md_raw).expanduser() if str(md_raw).strip() else get_canonical_models_dir()\n"
                "models_dir.mkdir(parents=True, exist_ok=True)\n"
                "cat = validate_catalog_entries(load_catalog())\n"
                "entry = next((m for m in cat if (m.get('name') or '').strip() == want), None)\n"
                "if entry is None:\n"
                "    raise SystemExit('catalog entry not found: ' + want)\n"
                "res = download_model(entry, models_dir=models_dir, progress=True)\n"
                "if not res.get('ok'):\n"
                "    raise SystemExit(res.get('error') or 'download failed')\n"
                "fn = res.get('filename') or entry.get('filename')\n"
                "if fn:\n"
                "    cfg['model_filename'] = __import__('pathlib').Path(str(fn)).name\n"
                "tmp = cfg_path.with_suffix(cfg_path.suffix + '.tmp')\n"
                "tmp.write_text(json.dumps(cfg, indent=2) + '\\n', encoding='utf-8')\n"
                "__import__('os').replace(str(tmp), str(cfg_path))\n"
                "p = agent / '.layla_pending_model.json'\n"
                "p.unlink(missing_ok=True)\n"
                "ready = agent / '.layla_model_ready.flag'\n"
                "tmp_r = ready.with_suffix(ready.suffix + '.tmp')\n"
                "tmp_r.write_text(__import__('json').dumps({'model_filename': cfg.get('model_filename')}), encoding='utf-8')\n"
                "__import__('os').replace(str(tmp_r), str(ready))\n"
                "print('[background-model] Done:', cfg['model_filename'])\n"
            )
            r = subprocess.run(
                [str(py), "-c", code, str(REPO_ROOT), want],
                cwd=str(REPO_ROOT),
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            if r.returncode != 0:
                print("[run] WARN: Background model download subprocess failed.")
        except Exception as e:
            print(f"[run] WARN: Background model download error: {e}")

    if enabled:
        threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Layla server")
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip scripts/setup_layla.py (venv must already exist).",
    )
    parser.add_argument(
        "--background-model",
        action="store_true",
        help="After the server is up, download the catalog model named in agent/.layla_pending_model.json "
        "(also enable with env LAYLA_BACKGROUND_MODEL=1).",
    )
    parser.add_argument(
        "--strict-health",
        action="store_true",
        help="Exit with code 1 if /health?deep=true reports tools_registered==0.",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)

    if args.background_model:
        os.environ["LAYLA_BACKGROUND_MODEL"] = "1"

    if not args.skip_setup:
        print("[run] Running setup / validation …")
        r = subprocess.run([sys.executable, str(SETUP_SCRIPT)], cwd=str(REPO_ROOT))
        if r.returncode != 0:
            return int(r.returncode)

    py = _venv_python(REPO_ROOT)
    if not py.is_file():
        print("[run] Missing .venv Python.")
        return 1

    cfg = _load_cfg()
    port = int(cfg.get("port", 8000) or 8000)

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    if cfg.get("use_chroma", True):
        env.pop("LAYLA_CHROMA_DISABLED", None)
    else:
        env["LAYLA_CHROMA_DISABLED"] = "1"

    print(f"[run] Starting server on 127.0.0.1:{port} …")
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", f"--port={port}"],
        cwd=str(AGENT_DIR),
        env=env,
    )

    try:
        hp = _wait_health(port)
        tools = int(hp.get("tools_registered") or 0)
        chroma_ok = bool(hp.get("chroma_ok"))
        print("[run] /health (deep): ok")
        print(f"      tools_registered={tools} chroma_ok={chroma_ok}")
        if tools <= 0:
            print(
                "\n  *** [run] WARNING: tools_registered is 0 — tool routing may be broken or still initializing. ***\n"
            )
            if args.strict_health:
                proc.terminate()
                return 1
        if not chroma_ok:
            print("[run] WARN: chroma_ok is false — check use_chroma and embedding/Chroma logs.")
        mwarn = (hp.get("model_health_warning") or hp.get("model_error") or "").strip()
        if mwarn:
            print(f"\n  *** [run] WARNING (model): {mwarn} ***\n")

        _maybe_background_model_download()

        print(f"[run] UI: http://127.0.0.1:{port}/ui")
        webbrowser.open(f"http://127.0.0.1:{port}/ui")
        print("[run] Server running — Ctrl+C to stop.")
        return int(proc.wait())
    except KeyboardInterrupt:
        proc.terminate()
        return 0
    except Exception as e:
        proc.terminate()
        print(f"[run] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

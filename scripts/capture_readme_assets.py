#!/usr/bin/env python3
"""
Capture real readme-asset PNGs + demo.gif from a local uvicorn instance (headless Chromium).

Requires (from repo root):
  pip install -r agent/requirements.txt -r agent/requirements-e2e.txt
  python -m playwright install chromium

Usage:
  python scripts/capture_readme_assets.py

Writes:
  readme-assets/hero-layla-ui.png
  readme-assets/screenshot-web-ui.png  (alias-quality full page)
  readme-assets/approvals-panel.png    (pending approvals region)
  readme-assets/demo.gif               (short loop; needs Pillow)

Override port with env CAPTURE_PORT=8765 if needed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
OUT_DIR = REPO_ROOT / "readme-assets"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(port: int, deadline_s: float = 90.0) -> str:
    base = f"http://127.0.0.1:{port}"
    end = time.time() + deadline_s
    last = ""
    while time.time() < end:
        try:
            urllib.request.urlopen(base + "/health", timeout=3)
            return base
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = str(e)
            time.sleep(0.35)
    raise RuntimeError(f"server did not become ready: {last}")


def _write_ci_config(sandbox: Path) -> None:
    cfg = {
        "model_filename": "ci-stub.gguf",
        "use_chroma": False,
        "sandbox_root": str(sandbox).replace("\\", "/"),
        "max_tool_calls": 2,
        "max_runtime_seconds": 30,
        "n_ctx": 2048,
        "n_gpu_layers": 0,
        "scheduler_study_enabled": False,
    }
    import json

    dst = AGENT_DIR / "runtime_config.json"
    dst.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _touch_stub_model() -> None:
    md = AGENT_DIR / "models"
    md.mkdir(parents=True, exist_ok=True)
    stub = md / "ci-stub.gguf"
    if not stub.exists():
        stub.write_bytes(b"LAYLA_CI_STUB_GGUF")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture readme media via Playwright")
    parser.add_argument("--gif-frames", type=int, default=24, help="Frames for demo.gif")
    parser.add_argument("--gif-delay-ms", type=int, default=120, help="GIF frame duration (ms) for Pillow")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install playwright: pip install -r agent/requirements-e2e.txt && python -m playwright install chromium")
        return 1

    os.chdir(REPO_ROOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cfg_path = AGENT_DIR / "runtime_config.json"
    cfg_backup: Path | None = None
    if cfg_path.is_file():
        fd, tmp_cfg = tempfile.mkstemp(prefix="layla_runtime_", suffix=".json")
        os.close(fd)
        cfg_backup = Path(tmp_cfg)
        shutil.copy2(cfg_path, cfg_backup)

    with tempfile.TemporaryDirectory() as td:
        sand = Path(td) / "layla-cap"
        sand.mkdir(parents=True, exist_ok=True)
        _write_ci_config(sand)
        _touch_stub_model()

        port = int(os.environ.get("CAPTURE_PORT") or _free_port())
        env = os.environ.copy()
        sep = os.pathsep
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(AGENT_DIR) + (sep + prev if prev else "")

        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(AGENT_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            base = _wait_health(port)
            init_js = (
                "localStorage.setItem('layla_wizard_v2_done','1'); "
                "localStorage.setItem('layla_wizard_done','1');"
            )

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    viewport={"width": 1400, "height": 860},
                    device_scale_factor=1,
                )
                page = ctx.new_page()
                page.add_init_script(init_js)

                page.goto(f"{base}/ui", wait_until="networkidle", timeout=120000)
                page.wait_for_selector("#msg-input", timeout=90000)

                hero = OUT_DIR / "hero-layla-ui.png"
                page.screenshot(path=str(hero), full_page=False)

                fullp = OUT_DIR / "screenshot-web-ui.png"
                page.screenshot(path=str(fullp), full_page=True)

                apr = OUT_DIR / "approvals-panel.png"
                al = page.locator("#approvals-list")
                try:
                    al.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                try:
                    page.evaluate(
                        "() => { const e = document.querySelector('#approvals-list'); "
                        "if (e) e.scrollIntoView({block:'center'}); }"
                    )
                except Exception:
                    pass
                try:
                    al.screenshot(path=str(apr), timeout=15000)
                except Exception:
                    page.screenshot(path=str(apr), full_page=True)

                # GIF: subtle scroll frames (real Chromium pixels)
                frames: list[Path] = []
                gif_path = OUT_DIR / "demo.gif"
                try:
                    from PIL import Image  # type: ignore[import-untyped]
                except ImportError:
                    Image = None  # type: ignore[misc, assignment]

                if Image is not None:
                    tmpd = Path(td) / "gif_frames"
                    tmpd.mkdir(parents=True, exist_ok=True)
                    for i in range(args.gif_frames):
                        page.evaluate(
                            "n => { const el = document.querySelector('#chat-log')||document.scrollingElement; "
                            "if(el) el.scrollTop = Math.min((el.scrollHeight||800)*n/20, (el.scrollHeight||800)); }",
                            i,
                        )
                        fp = tmpd / f"f{i:03d}.png"
                        page.screenshot(path=str(fp), full_page=False)
                        frames.append(fp)
                        time.sleep(0.06)

                    imgs = [Image.open(f).convert("RGB").quantize(colors=128) for f in frames]
                    duration = max(20, min(250, args.gif_delay_ms))
                    imgs[0].save(
                        gif_path,
                        save_all=True,
                        append_images=imgs[1:],
                        duration=duration,
                        loop=0,
                        optimize=True,
                    )
                    print(f"Wrote {gif_path} ({len(imgs)} frames)")
                else:
                    print("Pillow not installed — skipped demo.gif (pip install Pillow)")

                browser.close()

            print(f"Wrote {hero.name}, {fullp.name}, {apr.name} under {OUT_DIR}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()

    if cfg_backup is not None:
        shutil.copy2(cfg_backup, cfg_path)
        cfg_backup.unlink(missing_ok=True)
        print("Restored previous agent/runtime_config.json.")
    else:
        try:
            cfg_path.unlink(missing_ok=True)
        except Exception:
            pass
        print("Removed temporary runtime_config.json (none existed before capture).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

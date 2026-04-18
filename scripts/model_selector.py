#!/usr/bin/env python3
"""
Interactive model download for Layla setup.

Uses agent/models/model_catalog.json (no dynamic URLs). See install/model_downloader.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "agent"
RUNTIME_CFG = AGENT_DIR / "runtime_config.json"


def _summarize_hardware() -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (public_summary, detect_hardware dict for recommend_model)."""
    path = REPO_ROOT / "scripts" / "hardware_detect.py"
    spec = importlib.util.spec_from_file_location("layla_hardware_detect", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load hardware_detect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    summary = mod.summarize_hardware()
    full = summary.pop("_detect_hardware", None)
    if full is None:
        if str(AGENT_DIR) not in sys.path:
            sys.path.insert(0, str(AGENT_DIR))
        from services.hardware_detect import detect_hardware

        full = detect_hardware()
    public = {k: v for k, v in summary.items() if not str(k).startswith("_")}
    return public, full


def _load_cfg() -> dict[str, Any]:
    if not RUNTIME_CFG.is_file():
        return {}
    try:
        return json.loads(RUNTIME_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cfg(cfg: dict[str, Any]) -> None:
    RUNTIME_CFG.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CFG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _warn_absolute_model_filename(cfg: dict[str, Any]) -> None:
    raw = cfg.get("model_filename")
    if not raw or not isinstance(raw, str):
        return
    if Path(raw).is_absolute() or "/" in raw or "\\" in raw:
        print(
            f"[model_selector] WARNING: model_filename should be a basename only; "
            f"got path-like value — using {Path(raw).name!r}"
        )


def _ensure_agent_path() -> None:
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))


def _download_one(entry: dict[str, Any], models_dir: Path) -> dict[str, Any]:
    _ensure_agent_path()
    from install.model_downloader import download_model

    return download_model(entry, models_dir=models_dir, progress=True)


def _models_dir_from_cfg(cfg: dict[str, Any]) -> Path:
    _ensure_agent_path()
    from install.model_downloader import get_canonical_models_dir

    raw = (cfg.get("models_dir") or "").strip()
    if raw:
        try:
            return Path(raw).expanduser().resolve()
        except Exception:
            pass
    return get_canonical_models_dir()


def run_model_selection(*, interactive: bool, category: str | None = None) -> tuple[bool, str]:
    """
    Returns (success, reason) where reason is one of:
      \"\" — ok
      \"no_match\" — no catalog row fits hardware (caller may raise in non-interactive mode)
      \"download_failed\" — HTTP / integrity failure
      \"aborted\" — user cancelled interactive flow
    """
    _ensure_agent_path()
    from install.model_selector import load_catalog, recommend_model, validate_catalog_entries

    _, hw = _summarize_hardware()
    cfg0 = _load_cfg()
    _warn_absolute_model_filename(cfg0)
    models_dir = _models_dir_from_cfg(cfg0)
    models_dir.mkdir(parents=True, exist_ok=True)

    noninteractive = (
        not interactive
        or (os.environ.get("LAYLA_SETUP_NONINTERACTIVE") or "").strip().lower() in ("1", "true", "yes")
    )

    chosen: list[dict[str, Any]] = []

    catalog = validate_catalog_entries(load_catalog())

    if noninteractive:
        entry = recommend_model(hw, category_preference=category, interactive=False)
        if not entry:
            raise RuntimeError("No compatible model found for this hardware")
        chosen = [entry]
    else:
        print()
        print("  Model setup — choose how to pick your GGUF (from bundled catalog).")
        print("  ----------------------------------------------------------------")
        print("  1) Auto-select best match for this PC")
        print("  2) Choose category (general / coding / fast / reasoning / …)")
        print("  3) Download multiple models (same directory; first = default chat model)")
        print()
        try:
            choice = input("  Enter 1, 2, or 3 [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            return False, "aborted"

        if choice == "2":
            cats = sorted({(m.get("category") or "unknown").lower() for m in catalog if m.get("category")})
            print(f"  Categories in catalog: {', '.join(cats) or 'unknown'}")
            try:
                cat_in = input("  Category name [general]: ").strip().lower() or "general"
            except (EOFError, KeyboardInterrupt):
                return False, "aborted"
            pool = [m for m in catalog if (m.get("category") or "").strip().lower() == cat_in]
            if not pool:
                print(f"  No entries for '{cat_in}', falling back to auto.")
                entry = recommend_model(hw, category_preference=None, interactive=True)
            else:
                entry = recommend_model(hw, category_preference=cat_in, interactive=True)
            if not entry:
                print("[model_selector] ERROR: No compatible model.")
                return False, "no_match"
            chosen = [entry]
        elif choice == "3":
            print("  Pick models by number (empty line to finish).")
            raw_list = load_catalog()
            for i, m in enumerate(raw_list):
                desc = (m.get("desc") or "")[:72]
                print(f"    [{i}] {m.get('name', '?')} — {desc}")
            while True:
                try:
                    line = input("  Index (or blank to stop) []: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    break
                try:
                    idx = int(line)
                    if 0 <= idx < len(raw_list):
                        chosen.append(raw_list[idx])
                except ValueError:
                    print("  Invalid index.")
            if not chosen:
                print("  No models selected.")
                return False, "aborted"
        else:
            entry = recommend_model(hw, category_preference=category, interactive=True)
            if not entry:
                print("[model_selector] ERROR: No compatible model.")
                return False, "no_match"
            chosen = [entry]

    downloaded: list[str] = []
    for ent in chosen:
        print(f"\n  Downloading: {ent.get('name', '?')} …")
        res = _download_one(ent, models_dir)
        if not res.get("ok"):
            err = res.get("error", "download failed")
            print(f"  [!] {err}")
            return False, "download_failed"
        fn = res.get("filename") or ent.get("filename")
        if fn:
            downloaded.append(Path(str(fn)).name)

    if not downloaded:
        return False, "download_failed"

    cfg = _load_cfg()
    _warn_absolute_model_filename(cfg)
    cfg["model_filename"] = downloaded[0]
    existing = cfg.get("available_models")
    if not isinstance(existing, list):
        existing = []
    existing_names = [Path(str(x)).name for x in existing if x]
    merged = list(dict.fromkeys([*existing_names, *downloaded]))
    cfg["available_models"] = merged
    if (cfg.get("models_dir") or "").strip() == "":
        cfg["models_dir"] = str(models_dir)
    _save_cfg(cfg)
    print(f"\n  Config updated: model_filename={downloaded[0]!r}")
    print(f"  available_models: {merged}")
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Layla model download / selection")
    parser.add_argument("--yes", action="store_true", help="Non-interactive auto-select")
    parser.add_argument("--category", type=str, default=None, help="Prefer catalog category (with --yes)")
    args = parser.parse_args()

    interactive = not args.yes
    try:
        ok, _ = run_model_selection(interactive=interactive, category=args.category)
        return 0 if ok else 1
    except RuntimeError as e:
        print(f"[model_selector] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

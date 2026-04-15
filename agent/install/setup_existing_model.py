"""
Non-interactive setup when models exist in the canonical models dir.
Updates runtime_config.json with model_filename and models_dir.
Run from repo root: python agent/install/setup_existing_model.py
Returns 0 if configured, 1 if no model found or config already valid.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = AGENT_DIR / "runtime_config.example.json"


def run() -> int:
    try:
        from runtime_safety import CONFIG_FILE, default_models_dir
    except ImportError as e:
        raise ImportError(f"Could not import runtime_safety: {e}") from e

    canonical_dir = default_models_dir()
    if not canonical_dir.exists():
        return 1
    models = list(canonical_dir.glob("*.gguf"))
    if not models:
        return 1

    # Prefer: jinx-20b > any jinx* > any dolphin* > first (alphabetically)
    def _pick_best(models_list: list) -> Path:
        names = [p.name.lower() for p in models_list]
        if "jinx-20b.gguf" in names:
            return canonical_dir / "jinx-20b.gguf"
        jinx = [p for p in models_list if "jinx" in p.name.lower()]
        if jinx:
            return sorted(jinx)[0]
        dolphin = [p for p in models_list if "dolphin" in p.name.lower()]
        if dolphin:
            return sorted(dolphin)[0]
        return sorted(models_list)[0]

    chosen = _pick_best(models)

    # Load existing config
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
    else:
        try:
            cfg = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"Could not load example config: {e}") from e

    # Check if already correctly configured
    current = cfg.get("model_filename", "")
    current_dir = cfg.get("models_dir", "")
    resolved = Path(current_dir).expanduser().resolve() / current if current_dir and current else None
    if resolved and resolved.exists():
        return 0  # Already valid

    cfg["model_filename"] = chosen.name
    cfg["models_dir"] = str(canonical_dir.resolve())
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"Could not write {CONFIG_FILE}: {e}") from e
    print(f"  Configured model: {chosen.name} ({canonical_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(run())

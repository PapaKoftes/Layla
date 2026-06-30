#!/usr/bin/env python3
"""Detect hardware -> pick the optimal kit -> download the model -> write config.

The Python heart of the fresh-laptop installer (REQ-72/73/75). It reuses the SAME
`recommend_kit()` the app uses, so what gets installed is exactly what Layla would
recommend for this machine. Idempotent: re-running re-resolves and skips an
already-downloaded model.

Usage:
    python install/provision_model.py                 # balanced coding kit
    python install/provision_model.py --prefer quality
    python install/provision_model.py --dry-run       # recommend only, no download
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# install/ -> agent/  (so `import runtime_safety`, `install.*` resolve)
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefer", default="balanced", choices=["quality", "balanced", "lite", "speed"])
    ap.add_argument("--domain", default="coding")
    ap.add_argument("--spanish", action="store_true", help="Castilla: respond in Spanish (bilingual ES/EN)")
    ap.add_argument("--dry-run", action="store_true", help="recommend only; do not download")
    args = ap.parse_args(argv)

    import runtime_safety as rs
    from install.hardware_probe import probe_hardware
    from install.model_selector import recommend_kit

    hw = probe_hardware()
    hw_info = {
        "ram_gb": hw.get("ram_gb", 0),
        "vram_gb": hw.get("vram_gb", 0),
        "acceleration_backend": hw.get("acceleration_backend", "none"),
        "gpu_name": hw.get("gpu_name", "none"),
        "physical_cores": hw.get("cpu_physical") or hw.get("cpu_cores") or 4,
    }
    print(f"[hardware] {hw.get('cpu_model', '?')} | {hw_info['physical_cores']} cores | "
          f"{hw_info['ram_gb']}GB RAM | GPU {hw_info['gpu_name']} "
          f"({hw_info['acceleration_backend']}) | tier {hw.get('machine_tier', '?')}")

    import shutil
    try:
        _probe = rs.default_models_dir()
        _probe = _probe if _probe.exists() else _probe.parent
        free_gb = shutil.disk_usage(str(_probe)).free / 1e9
    except Exception:
        free_gb = 0.0
    print(f"[disk] ~{free_gb:.0f} GB free")
    if free_gb and free_gb < 12 and args.prefer in ("balanced", "quality"):
        print(f"[disk] only ~{free_gb:.0f} GB free -> switching to a lighter model (--prefer lite)")
        args.prefer = "lite"

    kit = recommend_kit(hw_info, domain=args.domain, prefer=args.prefer)
    if not kit or not kit.get("primary"):
        print("[error] no compatible model for this hardware", file=sys.stderr)
        return 1
    primary = kit["primary"]
    print(f"[kit] {kit['rationale']}")
    print(f"[kit] primary={primary['name']}  aspect={kit['aspect']}  draft={(kit.get('draft') or {}).get('name', '-')}")

    if args.dry_run:
        print(json.dumps({"primary": primary.get("name"), "aspect": kit["aspect"],
                          "settings": kit["settings"]}, indent=2))
        return 0

    dest = Path(rs.default_models_dir())
    dest.mkdir(parents=True, exist_ok=True)
    fn = primary.get("filename")
    if fn and (dest / fn).exists():
        print(f"[model] already present: {dest / fn}")
        res = {"ok": True, "filename": fn}
    else:
        from install.model_downloader import download_model
        print(f"[model] downloading {fn} -> {dest} ...")
        res = download_model(primary, models_dir=dest, progress=True)
    if not res.get("ok"):
        print(f"[error] model download failed: {res.get('error')}", file=sys.stderr)
        return 1

    cfg_path = Path(rs.CONFIG_FILE)
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    s = kit["settings"]
    cfg.update({
        "model_filename": fn,
        "models_dir": str(dest),
        "n_ctx": s.get("n_ctx", 4096),
        "n_gpu_layers": s.get("n_gpu_layers", 0),
        "n_threads": s.get("n_threads", hw_info["physical_cores"]),
    })
    if kit.get("aspect"):
        cfg.setdefault("default_aspect", kit["aspect"])
    if getattr(args, "spanish", False):
        cfg["custom_system_prefix"] = (
            "Eres Layla. Responde SIEMPRE en espanol (castellano) de forma clara y concisa. "
            "Manten el codigo, los nombres de funciones/variables y los terminos tecnicos "
            "estandar en ingles cuando sea la convencion. Si el usuario escribe en ingles, "
            "puedes responder en ingles."
        )
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[config] wrote {cfg_path}  (model={fn}, n_ctx={cfg['n_ctx']}, n_gpu_layers={cfg['n_gpu_layers']})")
    print("\n[done] Layla provisioned for this machine. Start it per install/INSTALL.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

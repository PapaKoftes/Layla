"""Find Layla's model wherever it landed, put it in a writable folder, and wire the config correctly.

All the fragile bits (JSON edit, ~ expansion, path moves) done in Python where they actually work.
  argv[1] = agent dir
  argv[2] = data dir (writable; e.g. %LOCALAPPDATA%\\Layla)
  argv[3] = optional catalog model name to DOWNLOAD if none found
Prints a clear report + 'RESULT ok|no_model_found'. Exit 0 on success, 3 if no model."""
import json
import sys
from pathlib import Path

agent = Path(sys.argv[1]).expanduser()
data = Path(sys.argv[2]).expanduser()
want = sys.argv[3] if len(sys.argv) > 3 else ""
sys.path.insert(0, str(agent))

models_dir = data / "models"
models_dir.mkdir(parents=True, exist_ok=True)
home = Path.home()

# 1) Find every .gguf that might already be on disk, including the literal-"~" folders a prior buggy run
#    could have created (Python does not expand ~, PowerShell does).
search = [
    models_dir,
    home / ".layla" / "models",
    home / "~" / ".layla" / "models",
    Path.cwd() / "~" / ".layla" / "models",
    agent.parent / "models",
    home / ".layla" / "models",
]
found = {}
for d in search:
    try:
        for g in Path(d).glob("*.gguf"):
            if g.is_file():
                found[g.resolve()] = g
    except Exception:
        pass
ggufs = list(found.values())
print("GGUF files found:")
for g in ggufs:
    print(f"   {g}  ({g.stat().st_size // 1024 // 1024} MB)")
if not ggufs:
    print("   (none)")

# 2) If none and a name was given, download it into the writable models dir.
if not ggufs and want:
    try:
        from install.model_downloader import download_model
        cat = json.loads((agent / "models" / "model_catalog.json").read_text(encoding="utf-8"))
        ms = cat if isinstance(cat, list) else cat.get("models", [])
        m = next((x for x in ms if x.get("name") == want), None)
        if not m:
            print(f"unknown model '{want}'")
        else:
            print(f"Downloading {want} ...")
            r = download_model(m, models_dir=models_dir, progress=True)
            if r.get("ok"):
                ggufs = [models_dir / (r.get("filename") or m["filename"])]
            else:
                print("download failed:", r.get("error"))
    except Exception as e:
        print("download error:", e)

if not ggufs:
    print("RESULT no_model_found")
    sys.exit(3)

# 3) Pick the largest (the real model, not a stub). Point the config at wherever it ALREADY is — no move,
#    no redownload.
best = max(ggufs, key=lambda g: g.stat().st_size)
dest = best

# 4) Write the config with an ABSOLUTE models_dir + model_filename, preserving existing settings.
#    CRITICAL: read with utf-8-SIG (strips a UTF-8 BOM that a prior PowerShell `Set-Content -Encoding UTF8`
#    may have written) and write plain utf-8 (NO BOM). The app's json loader rejects a BOM and silently
#    falls back to defaults ("your-model.gguf"), which is exactly why the model was ignored.
cfgp = data / "runtime_config.json"
cfg = {}
if cfgp.exists():
    try:
        cfg = json.loads(cfgp.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print("existing config unreadable, writing a fresh one:", e)
        cfg = {}
if not isinstance(cfg, dict):
    cfg = {}
cfg["models_dir"] = str(dest.parent)
cfg["model_filename"] = dest.name
cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
print(f"RESULT ok model_filename={dest.name} models_dir={dest.parent}")

# 5) Confirm the app itself now resolves the file.
try:
    import runtime_safety as rs
    try:
        rs.invalidate_config_cache()
    except Exception:
        pass
    p = rs.resolve_model_path(rs.load_config())
    print(f"app resolves model -> {p}  EXISTS={Path(p).exists() if p else False}")
except Exception as e:
    print("resolve check:", e)

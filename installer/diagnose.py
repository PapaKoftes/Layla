"""Layla diagnostic — prints exactly what the app sees, so a model/chat failure is unambiguous.
Run by Diagnose-Layla.ps1. argv[1] = agent dir."""
import json
import sys
from pathlib import Path

agent = Path(sys.argv[1]).expanduser()
sys.path.insert(0, str(agent))


def line(k, v):
    print(f"{k:22}: {v}")


print("==== LAYLA DIAGNOSTIC ====")
try:
    import runtime_safety as rs
    cfg = rs.load_config()
except Exception as e:
    print("FATAL: could not load config:", e)
    sys.exit(1)

line("models_dir (config)", repr(cfg.get("models_dir")))
line("model_filename", repr(cfg.get("model_filename")))
line("remote_enabled", cfg.get("remote_enabled"))
line("LAYLA_DATA_DIR", __import__("os").environ.get("LAYLA_DATA_DIR"))

try:
    line("default_models_dir", rs.default_models_dir())
except Exception as e:
    line("default_models_dir", f"ERROR {e}")
try:
    roots = rs.model_search_roots(cfg)
    line("search roots", [str(r) for r in roots])
except Exception as e:
    line("search roots", f"ERROR {e}")
try:
    p = rs.resolve_model_path(cfg)
    line("RESOLVED model path", f"{p}  EXISTS={Path(p).exists() if p else False}")
except Exception as e:
    line("RESOLVED model path", f"ERROR {e}")

print("---- .gguf files actually on disk (targeted) ----")
home = Path.home()
candidates = {
    rs.default_models_dir() if hasattr(rs, "default_models_dir") else None,
    Path(str(cfg.get("models_dir") or "")).expanduser() if cfg.get("models_dir") else None,
    home / ".layla" / "models",
    home / "~" / ".layla" / "models",          # the literal-tilde mistake
    Path.cwd() / "~" / ".layla" / "models",
    agent.parent / "models",                    # <install>/models
}
found = False
for c in candidates:
    if not c:
        continue
    try:
        for g in Path(c).glob("*.gguf*"):
            print(f"   {g}  ({g.stat().st_size // 1024 // 1024} MB)")
            found = True
    except Exception:
        pass
if not found:
    print("   (no .gguf files found in any expected location)")

print("---- model load status (why chat fails) ----")
try:
    from services.llm.llm_gateway import model_loaded_status
    print(json.dumps(model_loaded_status(), default=str, indent=2))
except Exception as e:
    import traceback
    print("model_loaded_status ERROR:", e)
    traceback.print_exc()
print("==== END DIAGNOSTIC ====")

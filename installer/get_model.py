"""Download a model by catalog name into a target dir, with a console progress bar.

Run by Fix-Layla.ps1 (and standalone). Avoids any embedding of Python in PowerShell.
  argv[1] = agent dir (put on sys.path + holds models/model_catalog.json)
  argv[2] = model name from the catalog (e.g. dolphin-3.0-llama3.1-8b-Q4_K_M)
  argv[3] = target models dir (writable, e.g. ~/.layla/models)
Prints 'DOWNLOADED <filename>' on success (exit 0) or 'FAILED <reason>' (exit 4)."""
import json
import sys
from pathlib import Path

agent = Path(sys.argv[1]).expanduser()
name = sys.argv[2]
models_dir = Path(sys.argv[3]).expanduser()  # ~ must expand here too (Python does not do it implicitly)
sys.path.insert(0, str(agent))

from install.model_downloader import download_model  # noqa: E402

catalog = json.loads((agent / "models" / "model_catalog.json").read_text(encoding="utf-8"))
models = catalog if isinstance(catalog, list) else catalog.get("models", [])
m = next((x for x in models if x.get("name") == name), None)
if not m:
    names = ", ".join(x.get("name", "?") for x in models[:12])
    print(f"FAILED unknown model '{name}'. Some options: {names}")
    sys.exit(4)

models_dir.mkdir(parents=True, exist_ok=True)
r = download_model(m, models_dir=models_dir, progress=True)
if r.get("ok"):
    print("DOWNLOADED " + str(r.get("filename") or m.get("filename")))
    sys.exit(0)
print("FAILED " + str(r.get("error") or "download error"))
sys.exit(4)

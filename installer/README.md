# Windows installer (Inno Setup)

This folder contains the **Windows payload + installer** pipeline:

- `build_installer.ps1` — sync `agent/` into `installer/payload/Layla`, build `layla.exe` (PyInstaller), optionally bundle **embeddable CPython**, then compile `layla.iss` if `iscc.exe` is on PATH.
- `bundle_embedded_python.ps1` — download **embeddable CPython**, bootstrap `pip`, install `agent/requirements.txt` into the payload python (minus `llama-cpp-python`, installed separately).
- `layla.iss` — Inno Setup script.

## Operator experience (packaged install)

The shipped layout is:

- `layla.exe` (launcher)
- `python/python.exe` (embedded runtime, when bundling is enabled)
- `agent/` (FastAPI app tree)

`launcher/layla_launcher.py` prefers `python/python.exe` when present, so **end users do not need Python installed**.

## Build prerequisites (maintainer machine)

- **Python 3.11 or 3.12** available as `py -3.12` / `py -3.11` (recommended) or as the `python` on PATH.
  - If your default `python` is **3.13+**, `build_installer.ps1` will refuse unless you set `LAYLA_ALLOW_PACKAGING_ON_UNSUPPORTED_PYTHON=1` (not recommended).
- `pip install pyinstaller`
- **Inno Setup 6+** (`iscc.exe` on PATH) to produce the final `Layla-Setup-*.exe`

## Build

From repo root (PowerShell):

```powershell
.\installer\build_installer.ps1
```

### Embedded Python bundling

Default: **ON**. To skip (payload without embedded python):

```powershell
$env:LAYLA_BUNDLE_EMBEDDED_PYTHON = "0"
.\installer\build_installer.ps1
```

### `llama-cpp-python` wheels (important)

PyPI ships `llama-cpp-python` as **sdist-only**; Windows wheels are published via the maintainer index:

`https://abetlen.github.io/llama-cpp-python/whl/cpu`

`bundle_embedded_python.ps1` installs **`llama-cpp-python==0.3.19`** from that index with `--only-binary=:all:` so the bundle does not require MSVC/CMake on the build machine.

## Clean-machine verification (release gate)

On a VM or fresh Windows profile:

1. Install the produced `installer/output/Layla-Setup-*.exe`.
2. Launch **Layla** from Start Menu / desktop shortcut.
3. Confirm:
   - `http://127.0.0.1:8000/health` returns HTTP 200
   - `http://127.0.0.1:8000/ui` loads
4. Walk first-run / model selection; download a small GGUF; send one chat turn.

If anything fails, capture `%LOCALAPPDATA%\Layla\logs` (if present) and the console output from `layla.exe`.

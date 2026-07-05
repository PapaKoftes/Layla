# Layla desktop shell (Tauri)

A tiny native window around Layla's local web UI — no Electron, ~small binary, fully
local. The window loads `http://127.0.0.1:8000/ui`; `dist/index.html` is a waiting-room
fallback that jumps into the UI as soon as the server answers `/health`.

## Prerequisites
- Rust toolchain (`rustup`) and the [Tauri v2 prerequisites](https://tauri.app/start/prerequisites/)
- Tauri CLI: `cargo install tauri-cli --version "^2"`

## Run / build
```bash
cd desktop
# Start Layla first (or set LAYLA_AUTOSTART=1 + LAYLA_DIR=<repo> to let the shell spawn it)
python -m uvicorn main:app --app-dir ../agent --host 127.0.0.1 --port 8000 &

cargo tauri dev      # develop
cargo tauri build    # produce a native installer under src-tauri/target/release/bundle/
```

## Auto-starting the server
Set `LAYLA_AUTOSTART=1` and `LAYLA_DIR=/path/to/Layla` before launching the built app;
`main.rs` will spawn `uvicorn` for you. Otherwise start Layla yourself — the window waits.

## Icons
Drop a 512×512 `icons/icon.png` (and platform icons via `cargo tauri icon icons/icon.png`)
before `cargo tauri build`.

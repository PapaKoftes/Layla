# Media for docs and README

## Automated capture (recommended)

From the **repository root**, with Playwright + Chromium installed:

```bash
pip install -r agent/requirements.txt -r agent/requirements-e2e.txt Pillow
python -m playwright install chromium
python scripts/capture_readme_assets.py
```

This overwrites **`readme-assets/`** with real pixels from your tree:

| Output | Description |
|--------|-------------|
| `hero-layla-ui.png` | Viewport capture of `/ui` |
| `screenshot-web-ui.png` | Full-page `/ui` |
| `approvals-panel.png` | Pending approvals region (`#approvals-list`) |
| `demo.gif` | Short animated loop (requires **Pillow**) |

The script temporarily swaps `agent/runtime_config.json` for a CI-style stub (and restores your file afterward). It also drops a tiny `agent/models/ci-stub.gguf` placeholder if missing so the UI loads without a real GGUF.

## Manual recording

If you prefer ScreenToGif, ShareX, or OBS:

1. Start Layla (`START.bat` / `install.sh` / `uvicorn` from `agent/`).
2. Open `http://127.0.0.1:<port>/ui`.
3. Export into `readme-assets/` using the filenames above so GitHub-relative links keep working.

### Platform notes

- **Windows:** [ScreenToGif](https://www.screentogif.com/), ShareX.
- **macOS:** QuickTime → convert with `ffmpeg` / gifski.
- **Linux:** Peek, Kooha, OBS.

Keep GIFs reasonably small (~5–8 MB) so the repo stays clone-friendly.

## License note

Only commit media you own or have rights to use. UI captures of Layla running locally are appropriate for this repository’s documentation.

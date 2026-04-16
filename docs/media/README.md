# Media for docs and README

Use this folder for **real** screenshots and demo loops that show Layla as shipped on your machine.

## Recommended files

| File | Suggested use |
|------|----------------|
| `../readme-assets/demo.gif` | Short loop: open `/ui`, send a message, show streaming reply (optional tool + approval). |
| `../readme-assets/chat-light.png` | Light theme or mobile layout, if you support it. |
| `screenshot-web-ui.png` | Full-window capture at 1280×720 or 1920×1080. |

Paths are relative to the repo root so GitHub renders them in Markdown.

## Recording a demo GIF (Windows)

1. Start Layla: `START.bat` or `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`.
2. Open `http://127.0.0.1:8000/ui`.
3. Use [ScreenToGif](https://www.screentogif.com/), ShareX, or OBS → export as GIF (keep under ~5–8 MB for GitHub).
4. Save to `readme-assets/demo.gif` and add to the root README:

   ```markdown
   ![Demo](readme-assets/demo.gif)
   ```

## Recording (macOS / Linux)

- **macOS:** QuickTime screen recording → convert to GIF with `ffmpeg` or gifski.
- **Linux:** Peek, Kooha, or OBS.

## License note

Only commit media that you own or have rights to use. UI captures of Layla running locally are fine for this repo’s documentation.

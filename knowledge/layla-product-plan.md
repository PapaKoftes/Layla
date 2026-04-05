# Layla — Product Finalization Plan
*Goal: Local AI assistant that non-technical users can install and use daily to replace ChatGPT/Claude.*
*Generated: 2026-02-22*

---

## What We Have (Strengths)

- **Beautiful, functional UI** — dark occult aesthetic, aspect color theming, markdown/code rendering, voice I/O, streaming, SSE
- **Rich agent loop** — 179 registered tools (see `agent/tests/test_registered_tools_count.py`), tool-dispatch loop, approval flow, audit log, sandbox enforcement
- **6 personality aspects** — rich character definitions, auto-routing, deliberation, earned titles
- **Solid memory system** — SQLite + ChromaDB RAG, learnings, study plans, capabilities/evolution, memory graph
- **Voice I/O** — faster-whisper STT, kokoro-onnx TTS, both wired into the UI
- **Multiple access methods** — Web UI, TUI, CLI, MCP bridge (Cursor), OpenAI-compatible API
- **Research mission system** — autonomous multi-stage repo + web research
- **Setup scripts** — INSTALL.bat, START.bat, first_run.py, Docker
- **MCP bridge** — Cursor integration for coding workflows

---

## Critical Gaps (Blockers)

### 🔴 P0 — System won't work without fixing these

| Gap | Impact | Fix |
|---|---|---|
| **No model in `models/`** — `runtime_config.json` has placeholder `"your-model.gguf"` | Every LLM call fails silently | In-UI setup overlay + `/setup_status` endpoint |
| **No setup detection** — UI shows "she is waiting" with zero indication the model is missing | First-time users think it's broken | Detect on load, show guided setup modal |
| **`first_run.py` not auto-triggered** — excellent wizard exists but only runs if you call it manually | Users never set up their config | Auto-trigger if `runtime_config.json` is missing or has placeholder model |

---

## Full Gap Analysis by Category

### UX / Onboarding (non-technical users)

| Gap | Priority | Fix |
|---|---|---|
| Empty state shows only `∴` + "she is waiting" — no guidance | P0 | Add 6-8 example prompt tiles + "what can I do?" intro |
| No clear install documentation for non-technical users | P0 | One-page quick start guide + in-UI setup walkthrough |
| No model download UI | P0 | In-browser model picker + download progress bar |
| Settings require editing JSON manually | P1 | Settings panel in UI (model, voice, sandbox, temperature) |
| Approval flow is in sidebar, invisible to new users | P1 | Inline approvals in chat (approval button appears in the message that triggered it) |
| No "what Layla can do" documentation surfaced in UI | P1 | Help panel / capabilities overview accessible from header |
| Error messages are raw tracebacks | P1 | Friendly error handling + recovery suggestions |
| Aspect switching is in sidebar — unclear to new users | P2 | Tooltip on first visit, aspect descriptions on hover |
| No onboarding tour / first-run walkthrough | P2 | 5-step guided tour on first visit (localStorage flag) |

### Chat / Conversation

| Gap | Priority | Fix |
|---|---|---|
| **Chat disappears on page refresh** — no persistence | P0 | localStorage conversation storage + session list panel |
| No conversation sessions / history | P1 | Session sidebar: list past conversations, click to restore |
| No message search | P2 | Ctrl+F search within current session |
| No conversation export (user-facing) | P2 | Export button → downloads markdown/JSON |
| No message editing / retry | P2 | Edit last message, or click to retry |
| No conversation sharing | P3 | Generate shareable HTML snapshot |

### File & Context

| Gap | Priority | Fix |
|---|---|---|
| **No file upload** — can't attach a document to ask about | P1 | Drag-and-drop file into chat → sends text content as context |
| No image paste / upload | P2 | Paste image → vision-capable models can describe/analyze |
| Workspace path must be typed manually | P1 | File browser dialog via `/list_dir` API |
| No clipboard paste of code snippets with detection | P2 | Auto-detect pasted code, offer to wrap in code context |
| No URL-to-context (paste a link, auto-fetches) | P2 | Detect URL in input, auto-run `fetch_article` on send |

### Coding Companion

| Gap | Priority | Fix |
|---|---|---|
| Code blocks only have "copy" button | P1 | Add "apply to file" button (approval-gated write) |
| No diff viewer for proposed code changes | P1 | Unified diff display in chat for file modifications |
| Workspace context requires manual path entry | P1 | Auto-detect active workspace from URL param or config |
| No "insert at cursor" for code (Cursor/editor integration) | P2 | MCP tool `insert_at_cursor` via cursor-layla-mcp |
| Approval dance for every file write is friction | P1 | "Pre-approve workspace" toggle for trusted paths |
| No multi-file context | P2 | "Add files to context" chip list in input area |
| No terminal output capture | P3 | Shell output streaming into chat |

### Performance / Streaming

| Gap | Priority | Fix |
|---|---|---|
| Tool execution loop is silent — UI shows "Thinking…" for entire tool chain | P1 | Stream tool name + status during execution via SSE |
| Long generation blocks browser for ~3s before first token | P1 | Already has streaming; ensure it's used for all reply types |
| No token/speed indicator | P3 | Token/s display in header during generation |
| Cold start is slow (model load ~10-30s) | P2 | Model load progress bar + status in UI |

### Setup & Portability

| Gap | Priority | Fix |
|---|---|---|
| No cross-platform model downloader | P1 | Python script `download_model.py` + in-UI model picker |
| `INSTALL.bat` installs everything but no validation | P1 | Post-install health check + `python verify_install.py` |
| Docker image exists but untested | P2 | Test and document Docker path |
| No Windows service / autostart UI | P2 | `install-autostart.ps1` already exists, surface in UI |
| No macOS `.app` wrapper | P3 | PyInstaller bundle |
| No Android/tablet UI | P3 | Responsive breakpoints in CSS |

### Memory / Intelligence

| Gap | Priority | Fix |
|---|---|---|
| `memory_graph.py` is written to but never read back in the agent loop | P2 | Wire graph recall into system head as `memory_associations` |
| Study plans UI doesn't show progress or last-studied | P2 | Study plan cards with progress bar, last studied date |
| No "forget this" UI | P2 | Delete learning from learnings panel |
| Capabilities evolution layer not exposed to user | P3 | Skills visualization panel (radar chart) |
| No memory search in UI | P2 | Search bar in memory/learnings panel |

---

## Implementation Roadmap

### Sprint 1 — "Make It Work" (P0 + P1)

1. **`/setup_status` endpoint** — returns `{ready: bool, model_found: bool, model_path: str, config_exists: bool}`
2. **Setup overlay in UI** — on page load, fetch `/setup_status`; if not ready, show full-screen modal with:
   - Detected hardware summary
   - Model download picker (re-uses `first_run.py`'s `_MODELS_CATALOG`)
   - Progress bar via SSE stream
   - "Retry" button after download
3. **Example prompts in empty state** — 6 tiles: "Explain how...", "Write code for...", "Research...", "Help me debug...", "Summarize this...", "What should I..."
4. **Conversation persistence** — localStorage sessions: auto-save on every message, session list in sidebar, restore on load
5. **Streaming tool progress** — emit `{type: "tool_start", tool: "web_search"}` SSE events during agent loop; UI shows "🔧 Running web_search…" above typing indicator
6. **Settings panel** — gear icon in header → modal with: model filename, sandbox path, TTS voice, temperature, completion tokens, "save & reload"
7. **Inline approval UX** — when a message triggers an approval, render the approve button directly below that message bubble, not just in sidebar
8. **File drag-and-drop** — drop a file onto the chat → reads text content → injects as `[context from filename.txt]:\n...` prefix

### Sprint 2 — "Polish" (P2)

1. **Session history panel** — collapsible left sidebar expansion: "Conversations" with timestamps
2. **Diff viewer** — when a file write is proposed, render it as a side-by-side diff
3. **Auto-detect URLs in input** — if message contains a URL, auto-append `[fetching url...]` and fetch article
4. **Model load progress bar** — `/health` now returns `model_loaded: bool`; show loading bar until model is warm
5. **"Apply to file" code button** — approval-gated patch apply from code block
6. **Workspace pre-approval** — checkbox to pre-authorize writes to the current workspace path
7. **Memory graph recall wired into agent loop**
8. **Study plan progress cards**

### Sprint 3 — "Mature Product" (P3)

1. **Multi-file context chips** — add files to context from file browser
2. **Image upload + vision**
3. **Conversation search**
4. **Skills visualization**
5. **Mobile responsive CSS**
6. **Docker tested + documented**
7. **macOS/Linux packaging**

---

## Quick Win: Minimum Viable Non-Technical User Setup

For a non-technical user to go from zero to talking to Layla:

```
1. Download repo zip from GitHub
2. Run INSTALL.bat (Windows) or bash install.sh (macOS/Linux)
3. Open browser to http://localhost:8000
4. Setup overlay appears → pick model → download → done
5. Type something
```

**Everything else is polish around this core flow.**

---

## What Can Be Tested Right Now

| Feature | Test Method | Expected |
|---|---|---|
| Web UI loads | `GET http://localhost:8000` | 200, renders HTML |
| API health | `GET http://localhost:8000/health` | `{"ok": true}` |
| Agent responds | POST `/agent` `{"message":"hello"}` | JSON response with text |
| Voice transcribe | POST `/voice/transcribe` with WAV bytes | `{"text":"..."}` |
| TTS speak | POST `/voice/speak` `{"text":"hello"}` | WAV bytes |
| Tools execute | POST `/agent` `{"message":"search for python", "allow_run": true}` | Tool call + response |
| Approvals | POST `/agent` `{"message":"write a file", "allow_write": true}` | Approval flow |
| MCP bridge | Call `chat_with_jinx` from Cursor | Response from Layla |
| Memory persist | `POST /learn/` then restart + ask | Fact recalled |
| Wakeup | `GET /wakeup` | Echo aspect greeting |

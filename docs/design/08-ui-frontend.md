# 08 -- UI & Frontend

> Design document for the Layla AI client-side user interface.
> Covers architecture, component map, state management, API integration,
> styling, PWA support, security, performance, known issues, and stability.

---

## 1. Architecture Overview

### 1.1 Technology Stack

Layla's UI is a **vanilla-JavaScript single-page application** (SPA) with no
framework dependency.  Every module is loaded via `<script>` tags in a
carefully ordered sequence defined in `agent/ui/index.html` (lines 977-1015).
The application relies on a small set of vendored libraries:

| Library | Purpose | Integration |
|---------|---------|-------------|
| `marked` | Markdown-to-HTML rendering | Global `marked.parse()` |
| `DOMPurify` | HTML sanitization / XSS prevention | Vendored locally, wrapped in `sanitizeHtml()` |
| `highlight.js` | Syntax highlighting for code blocks | `hljs.highlightElement()` after markdown render |
| `SpeechSynthesis` | Browser-native TTS fallback | `window.speechSynthesis` API |

### 1.2 Module System

Modules use the **IIFE (Immediately Invoked Function Expression)** pattern,
exposing public functions via `window.*` assignments.  There is no ES module
import/export system.  Inter-module communication happens exclusively through
the global `window` namespace:

```
(function () {
  'use strict';
  // private state...
  window.publicFunction = function () { ... };
})();
```

A notable inconsistency exists: some modules (`layla-conversations.js`,
`layla-memory.js`, `layla-artifacts.js`, `layla-autonomous.js`,
`layla-search.js`, `layla-plan-viz.js`, `layla-perf.js`) use ES6
`const`/`let`/arrow functions, while core modules (`layla-bootstrap.js`,
`layla-settings-full.js`, `layla-pairing.js`, `layla-setup.js`) use ES5
`var`/`function` syntax for maximum compatibility.

### 1.3 Script Load Order

The HTML declares scripts in a precise dependency chain.  Each subsequent
module may call globals established by earlier modules:

```
layla-ui-phases.js       Phase/UX state mapping
layla-sprites.js         SVG aspect sprite backgrounds
layla-bootstrap.js       Fetch interceptor, triggerSend fallback, panel switching, keyboard shortcuts
state.js                 Chat FSM (IDLE/SENDING/STREAMING/DONE/ERROR)
api.js                   Minimal fetch wrapper (laylaApiJson)
layla-utils.js           escapeHtml, sanitizeHtml, showToast, laylaConfirm, laylaPrompt, fetchWithTimeout
layla-aspect.js          Aspect colors/registry, setAspect, maturity rank card
layla-voice.js           Mic recording, TTS playback
sidebar.js               Scroll active conversation into view
panels.js                Right panel execution trace + task list
layla-wizard.js          6-step first-run wizard
layla-setup.js           Model download, hardware detection, onboarding
layla-settings-full.js   Settings overlay, workspace presets, content policy, deliberation mode
layla-chat-render.js     Message rendering, markdown, typing indicator, deliberation transcripts
layla-input.js           @mention dropdown, URL chips, file attach, keyboard shortcuts
layla-app.js             Core orchestrator: send(), SSE streaming, health polling
layla-conversations.js   Session list, search, CRUD, context menus
layla-artifacts.js       Code block extraction and editing
layla-search.js          Global search overlay
layla-memory.js          Memory browser / edit / delete
layla-plan-viz.js        Canvas Gantt chart
layla-autonomous.js      Autonomous task monitoring
layla-research.js        Research missions, approvals, investigation templates
layla-workspace.js       Platform panels (models, knowledge, plugins, projects, study plans)
layla-pairing.js         mDNS discovery, PIN pairing, paired device management
layla-character-creator.js  Character Lab (personality sliders, voice tuning, titles, lore)
layla-perf.js            IndexedDB caching, lazy init, requestIdleCallback, focus traps
```

### 1.4 HTML Structure

`index.html` (~1091 lines) contains the entire SPA structure:

- **Header** -- Title, aspect badge, aspect lock, session timer, connection status, global search, theme toggle, keyboard help
- **Three-column layout**:
  - *Left sidebar* -- Conversation rail (search, new-chat, pinned/recent sessions, project filter) + aspect buttons (6 aspects + maturity card)
  - *Main chat area* -- Message list (`#chat`), compose panel, input bar (`#msg-input`), send/mic/attach buttons, typing indicator
  - *Right panel* -- Tabbed interface (Status / Settings / Library / Artifacts / Research) with nested sub-tabs
- **Overlays** -- Wizard, setup, settings, onboarding, diff viewer, character lab, plan viz, tutorial, keyboard shortcuts, rank-up ceremony, confirm/prompt dialogs, chat search

### 1.5 Bootstrap & Initialization Sequence

`layla-bootstrap.js` runs first among the logic modules and performs critical
early-stage wiring:

1. **Fetch interceptor** -- Wraps native `fetch()` to inject `Authorization: Bearer <key>` header on non-localhost origins when `layla_remote_api_key` is present in localStorage
2. **Fallback `triggerSend()`** -- A bare-bones send implementation that works even if `layla-app.js` fails to load, rendering raw user/assistant messages with basic XSS escaping
3. **Input binding** -- Enter-to-send on `#msg-input`, click-to-send on `#send-btn`, with mention dropdown guard
4. **Right panel tab switching** -- Capture-phase click delegation for `.rcp-tab` and `.rcp-subtab` elements, with `aria-selected`/`aria-hidden` attribute management
5. **Aspect button delegation** -- Bubble-phase click handler for `.aspect-btn` elements
6. **Keyboard shortcuts** -- Ctrl+/ (help sheet), Ctrl+K (conversation spotlight search), Escape (close overlays)

---

## 2. Component Map

### 2.1 Chat System

| Component | File | Purpose |
|-----------|------|---------|
| Chat FSM | `state.js` | Finite state machine: IDLE -> SENDING -> STREAMING -> DONE -> ERROR. Guards concurrent sends via `canSend()`. Sets `data-chat-fsm` attribute on `<body>` for CSS hooks. |
| Message Renderer | `layla-chat-render.js` | `addMsg()` renders messages with markdown (marked + DOMPurify + hljs), code blocks with copy/apply buttons, deliberation transcripts, UX state labels, stream stats dock. |
| Input System | `layla-input.js` | @mention autocomplete, URL detection chips, file drag-and-drop (120KB text limit), prompt history (ArrowUp/Down), chat search (Ctrl+F). |
| Core Send | `layla-app.js` | `send()` builds payload from UI state, supports stream (SSE via ReadableStream) and non-stream modes. Handles token/thinking/tool_step/deliberation/ux_state/error/done events. Stall detection and first-token timers. |

### 2.2 Conversation Management

| Component | File | Purpose |
|-----------|------|---------|
| Session List | `layla-conversations.js` | Fetches/renders conversations with search (tag:/after:/before: filters), pinning (localStorage), right-click context menus (rename, delete, pin, tags, export). |
| Sidebar Helper | `sidebar.js` | `laylaScrollActiveConversationIntoView()` -- scrolls active item into viewport when rail updates. |
| New Conversation | `layla-conversations.js` | `startNewConversation()` via POST /conversations; `loadConversationIntoChat()` via GET /conversations/:id/messages. |
| Project Grouping | `layla-conversations.js` | `loadProjectsIntoSelect()`, `createProjectQuick()` for project-scoped conversations. |

### 2.3 Aspect System

| Component | File | Purpose |
|-----------|------|---------|
| Aspect Registry | `layla-aspect.js` | ASPECT_COLORS and ASPECTS array for 6 aspects (Morrigan, Nyx, Echo, Eris, Cassandra, Lilith), each with symbol, name, description, and color triplet (asp/glow/mid). |
| Aspect Switcher | `layla-aspect.js` | `setAspect()` updates CSS custom properties (--asp, --asp-glow, --asp-mid), body `data-aspect` attribute, doodle overlay content, sidebar active state, and sprite field. |
| Aspect Lock | `layla-aspect.js` | `toggleAspectLock()` prevents auto-routing; stores lock state. |
| Maturity Card | `layla-aspect.js` | `refreshMaturityCard()` fetches GET /operator/profile, renders rank/phase/XP/milestones, triggers rank-up ceremony overlay on rank change. |
| Character Lab | `layla-character-creator.js` | Full RPG-style customization: personality sliders (aggression, humor, verbosity, curiosity, bluntness, empathy), voice profile tuning (pitch, speed, warmth, formality), color customization, title selection, lore display. |

### 2.4 Voice System

| Component | File | Purpose |
|-----------|------|---------|
| Mic Recording | `layla-voice.js` | MediaRecorder (audio/webm), `toggleMic()`/`startMic()`/`stopMic()`. |
| Transcription | `layla-voice.js` | `transcribeAndSend()` POSTs raw audio to /voice/transcribe, auto-sends result. |
| TTS Playback | `layla-voice.js` | `speakText()` tries server Kokoro TTS (POST /voice/speak) first, falls back to browser SpeechSynthesis with per-aspect voice styles (rate, pitch). |

### 2.5 Research & Autonomous

| Component | File | Purpose |
|-----------|------|---------|
| Research | `layla-research.js` | Stream/non-stream modes via POST /research. Research missions with depth/next_stage via POST /research_mission. Mission status polling (5s interval). Approval cards with grant_pattern/grant_for_session. Investigation templates. |
| Autonomous Mode | `layla-autonomous.js` | `laylaAutoMonitorStart()` polls progress every 1.5s. Score/steps/summary/issues display. |

### 2.6 Workspace & Platform

| Component | File | Purpose |
|-----------|------|---------|
| Platform Panels | `layla-workspace.js` | Models list, knowledge base, plugins, projects, timeline, study plans (CRUD, presets, suggestions), skills list, plans (approve/execute/expand/Gantt), workspace awareness, project memory, symbol search, memory search (semantic + Elasticsearch), file checkpoints, debug state, coordinator tasks, background task cancellation. |
| Execution Panels | `panels.js` | `laylaRefreshExecutionPanels()` fetches /debug/state and /debug/tasks, renders JSON into status tab. Hooks into showMainPanel('status'). |

### 2.7 Settings & Configuration

| Component | File | Purpose |
|-----------|------|---------|
| Settings Overlay | `layla-settings-full.js` | Dynamic form generation from /settings/schema, saves via POST /settings. |
| Workspace Presets | `layla-settings-full.js` | localStorage per-host storage of saved workspace paths with add/remove/select. |
| Content Policy | `layla-settings-full.js` | uncensored + nsfw_allowed toggles via POST /settings. |
| Deliberation Mode | `layla-settings-full.js` | solo/auto/debate/council/tribunal selector, fetches current from /health on init. |
| Optional Features | `layla-settings-full.js` | GET /settings/optional_features, POST /settings/install_feature for pip-based installs. |
| Appearance | `layla-settings-full.js` | Font size, animation level via POST /settings. |

### 2.8 Networking & Pairing

| Component | File | Purpose |
|-----------|------|---------|
| mDNS Discovery | `layla-pairing.js` | POST /pairing/start and /pairing/stop. Peer polling every 10s. Peer cards with tier display (cpu/gpu_low/gpu_mid/gpu_high). |
| PIN Pairing | `layla-pairing.js` | `initiatePairing()` generates PIN, `showPinDialog()` with countdown, `confirmPairing()` on receiving side. |
| Paired Devices | `layla-pairing.js` | List/manage paired devices with permission toggles, health ping, unpair. |

### 2.9 Onboarding & Setup

| Component | File | Purpose |
|-----------|------|---------|
| First-Run Wizard | `layla-wizard.js` | 6-step wizard (welcome, setup check, workspace, personality quiz, aspect selection, ready). 9-question quiz submitted to /operator/quiz/submit. Escape blocked until final step. |
| Setup Overlay | `layla-setup.js` | Hardware detection (/setup_status), model catalog (/setup/models), model download via SSE (/setup/download), existing model selection, workspace path pre-fill. |
| Onboarding | `layla-setup.js` | 3-step post-setup tour (sandbox explanation, aspect selection hint, lock/ethics tip). Stores completion in localStorage. |

### 2.10 Utilities & Support

| Component | File | Purpose |
|-----------|------|---------|
| Search | `layla-search.js` | Global search overlay with debounced input (320ms), AbortController cancellation, results grouped by Conversations/Learnings/Workspace/Knowledge. |
| Artifacts | `layla-artifacts.js` | Extracts code blocks from messages via regex, max 40 artifacts with FIFO eviction, tab badge notifications. |
| Memory Browser | `layla-memory.js` | Paginated (20/page) browse with type/keyword filter, sort (recent/confidence), inline edit (PATCH /memory/:id), delete (DELETE /memory/:id). |
| Plan Visualizer | `layla-plan-viz.js` | Canvas-based Gantt chart with dependency arrows (Bezier curves), status coloring (done/in_progress/failed), similar plans comparison. |
| UX Phases | `layla-ui-phases.js` | Maps server UX state keys to display phases (connecting/thinking/streaming/tool/typing/stalled). Sets `data-layla-phase` on bubbles and `data-layla-chat-phase` on body. |
| Sprites | `layla-sprites.js` | Per-aspect SVG sprite backgrounds loaded into `#layla-sprite-field` with transition animation on aspect switch. |

---

## 3. State Management

### 3.1 Chat FSM

The chat finite state machine (`state.js`) enforces single-flight message
sending:

```
States:  IDLE  ->  SENDING  ->  STREAMING  ->  DONE
                       |                         |
                       v                         v
                     ERROR  <───────────────── ERROR
```

- `canSend()` returns `true` only in IDLE, DONE, or ERROR states
- Transitions set `data-chat-fsm` on `<body>` for CSS-driven UI state changes
- Callback `window.laylaOnChatState(newState)` fires on every transition

### 3.2 Global Window State

The application maintains a large surface of global state via `window.*`:

| Key | Source | Purpose |
|-----|--------|---------|
| `window.currentAspect` | bootstrap/aspect | Active aspect ID (e.g., 'morrigan') |
| `window.currentConversationId` | conversations | Active conversation UUID |
| `window.laylaChatFSM` | state.js | FSM instance with `canSend()`, `transition()` |
| `window.send` | layla-app.js | Primary send function |
| `window.triggerSend` | bootstrap | Fallback send (used if layla-app.js not loaded) |
| `window.setAspect` | layla-aspect.js | Aspect switching function |
| `window.showMainPanel` | bootstrap | Right panel tab switcher |
| `window.showWorkspaceSubtab` | bootstrap | Right panel sub-tab switcher |
| `window.showToast` | layla-utils.js | Ephemeral notification |
| `window.laylaConfirm` | layla-utils.js | Styled modal confirm |
| `window.escapeHtml` | layla-utils.js | XSS-safe string escaping |

### 3.3 localStorage Keys

The UI persists approximately 25+ keys in localStorage:

| Key Pattern | Purpose |
|-------------|---------|
| `layla_current_conversation_id` | Active conversation |
| `layla_default_aspect` | Preferred aspect |
| `layla_wizard_v2_done` / `layla_wizard_done` | Wizard completion flags |
| `layla_onboarding_v1_done` | Onboarding completion |
| `layla_remote_api_key` | Bearer token for remote access |
| `layla_workspace_presets_<host>` | Per-host saved workspace paths |
| `layla_voice_speed` / `layla_voice_volume` | Voice settings |
| `layla_pinned_<id>` | Pinned conversations |
| `layla_show_sidebar` / `layla_show_rightpanel` | Panel visibility |
| `layla_theme` | Light/dark theme preference |
| `layla_aspect_lock` | Aspect routing lock state |

### 3.4 IndexedDB

`layla-perf.js` sets up an IndexedDB database (`layla-ui`, version 1) with a
`conversations` object store indexed by `updated_at`.  Used for client-side
conversation caching.

### 3.5 Body Data Attributes (CSS State Hooks)

Multiple `data-*` attributes on `<body>` drive CSS state:

| Attribute | Values | Set By |
|-----------|--------|--------|
| `data-chat-fsm` | idle, sending, streaming, done, error | state.js |
| `data-aspect` | morrigan, nyx, echo, eris, cassandra, lilith | layla-aspect.js |
| `data-layla-chat-phase` | connecting, thinking, streaming, tool, typing, stalled | layla-ui-phases.js |

Individual message bubbles carry `data-layla-phase` for per-message state.

---

## 4. API Integration

### 4.1 Core Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/agent` | POST | layla-app.js | Primary chat (stream + non-stream) |
| `/health` | GET | layla-app.js | Deep health check (20s poll) |
| `/conversations` | GET/POST | layla-conversations.js | List/create conversations |
| `/conversations/:id` | GET/DELETE/PATCH | layla-conversations.js | Read/delete/update conversation |
| `/conversations/:id/messages` | GET | layla-conversations.js | Load conversation messages |
| `/conversations/search` | GET | layla-conversations.js | Search conversations |
| `/conversations/prompt_history` | GET | layla-input.js | Prompt history for ArrowUp/Down |
| `/compact` | POST | layla-app.js | Compact conversation |
| `/execute_plan` | POST | layla-app.js | Execute approved plan |

### 4.2 Memory & Knowledge Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/memory/browse` | GET | layla-memory.js | Paginated memory listing |
| `/memory/:id` | PATCH/DELETE | layla-memory.js | Edit/delete learning |
| `/learn/` | POST | layla-chat-render.js | Save response as learning |
| `/search` | GET | layla-search.js | Global search |
| `/memories` | GET | layla-workspace.js | Semantic memory search |
| `/elasticsearch/search` | GET | layla-workspace.js | Elasticsearch memory search |
| `/knowledge/import_chat` | POST | layla-settings-full.js | WhatsApp chat import |
| `/intelligence/kb/build/directory` | POST | layla-settings-full.js | Knowledge ingest |

### 4.3 Settings & Configuration Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/settings` | GET/POST | layla-settings-full.js | Read/write settings |
| `/settings/schema` | GET | layla-settings-full.js | Settings field definitions |
| `/settings/preset/:name` | POST | layla-settings-full.js | Apply settings preset |
| `/settings/optional_features` | GET | layla-settings-full.js | List optional features |
| `/settings/install_feature` | POST | layla-settings-full.js | Install optional feature |
| `/settings/git_undo_checkpoint` | POST | layla-settings-full.js | Revert git checkpoint |
| `/setup_status` | GET | layla-setup.js | Hardware/model readiness |
| `/setup/models` | GET | layla-setup.js | Model catalog |
| `/setup/download` | GET (SSE) | layla-setup.js | Model download stream |

### 4.4 Research & Autonomous Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/research` | POST | layla-research.js | Research query (stream/non-stream) |
| `/research_mission` | POST | layla-research.js | Start research mission |
| `/research_mission/state` | GET | layla-research.js | Mission status (polled 5s) |
| `/pending` | GET | layla-research.js | Pending approvals |
| `/autonomous/run` | POST | layla-research.js | Run autonomous research |
| `/agent/tasks/:id` | DELETE | layla-workspace.js | Cancel background task |

### 4.5 Character & Operator Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/character/summary` | GET | layla-character-creator.js | Character summary for lab |
| `/character/traits` | POST | layla-character-creator.js | Save personality traits |
| `/character/voice-params` | POST | layla-character-creator.js | Save voice profile |
| `/character/aspects/:id` | GET/PATCH | layla-character-creator.js | Aspect-specific data |
| `/operator/profile` | GET | layla-aspect.js | Maturity rank/XP/milestones |
| `/operator/quiz/stage/:n` | GET | layla-wizard.js | Personality quiz questions |
| `/operator/quiz/submit` | POST | layla-wizard.js | Submit quiz answers |
| `/codex/user` | GET/PUT | layla-settings-full.js | Relationship codex data |

### 4.6 Pairing & Networking Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/pairing/start` | POST | layla-pairing.js | Start mDNS discovery |
| `/pairing/stop` | POST | layla-pairing.js | Stop mDNS discovery |
| `/pairing/peers` | GET | layla-pairing.js | List discovered peers |
| `/pairing/pair` | POST | layla-pairing.js | Initiate pairing (get PIN) |
| `/pairing/confirm` | POST | layla-pairing.js | Confirm pairing (enter PIN) |
| `/pairing/paired-devices` | GET | layla-pairing.js | List paired devices |
| `/pairing/:id/permissions` | PATCH | layla-pairing.js | Toggle device permissions |
| `/pairing/:id` | DELETE | layla-pairing.js | Unpair device |
| `/pairing/status` | GET | layla-pairing.js | Discovery status |
| `/pairing/peer/:id/health` | GET | layla-pairing.js | Ping remote peer |

### 4.7 Miscellaneous Endpoints

| Endpoint | Method | Module | Purpose |
|----------|--------|--------|---------|
| `/voice/transcribe` | POST | layla-voice.js | Transcribe audio |
| `/voice/speak` | POST | layla-voice.js | Server-side TTS (Kokoro) |
| `/skills` | GET | layla-workspace.js | List available skills |
| `/study_plans` | GET/POST | layla-workspace.js | Study plan CRUD |
| `/plans/similar` | GET | layla-plan-viz.js | Similar plan comparison |
| `/file_checkpoints` | GET | layla-workspace.js | File checkpoint list |
| `/debug/state` | GET | panels.js | Debug execution state |
| `/debug/tasks` | GET | panels.js | Debug task list |
| `/version/check_update` | GET | layla-settings-full.js | Check for updates |

### 4.8 Streaming Protocol

The primary chat endpoint (`/agent`) supports SSE streaming via
ReadableStream.  The stream emits newline-delimited JSON events with the
following event types:

| Event Type | Payload | Handling |
|------------|---------|----------|
| `token` | `{text}` | Appended to current message bubble |
| `thinking` | `{text}` | Displayed in collapsible thinking block |
| `tool_step` | `{tool, args, result}` | Added to step counter and tool trace |
| `deliberation` | `{transcript}` | Rendered as debate/council/tribunal UI |
| `ux_state` | `{state}` | Maps to phase label and CSS state |
| `error` | `{message}` | Shows error in message, transitions FSM to ERROR |
| `done` | `{response, ...}` | Finalizes message, transitions FSM to DONE |

### 4.9 Fetch Infrastructure

- **`laylaApiJson(url, opts)`** (`api.js`) -- Minimal wrapper: calls `fetch()`, returns `{ok, status, json}`
- **`fetchWithTimeout(url, opts, ms)`** (`layla-utils.js`) -- Creates linked AbortController with timeout; merges user-supplied signal
- **Bootstrap fetch interceptor** (`layla-bootstrap.js`) -- Monkey-patches `window.fetch` to inject `Authorization` header on non-localhost requests when `layla_remote_api_key` is set in localStorage

---

## 5. Styling & Theming

### 5.1 CSS Architecture

Styling is split across two files (2,879 lines total):

- **`layla.css`** (2,293 lines) -- Base theme, layout, all component styles
- **`layla-enhanced.css`** (586 lines) -- Phase 3 refinements: enhanced Warframe chrome, Character Lab, tutorial overlay, accessibility improvements

### 5.2 Design Language: Warframe-Inspired

The UI employs a "Warframe HUD" aesthetic with these key visual elements:

- **Angular clip-path panels** -- All major containers (sidebar, main area, right panel, settings) use `clip-path: polygon()` to create beveled/cut corners (`--wf-cut: 12px`)
- **Void energy glow** -- Active elements emit `box-shadow` glow effects using aspect-derived colors, scaled by `--fx-strength` (default 1.5)
- **Scanline overlay** -- `body::after` repeating gradient creates CRT scanline effect (disabled via `prefers-reduced-motion`)
- **Holographic title** -- `.title` uses animated gradient `background-clip: text` with shimmer and breathing text-shadow
- **Neon sprite field** -- Full-viewport SVG aspect sprites behind content (`#layla-sprite-field`) with drop-shadow glow
- **Doodle overlay** -- Per-aspect ASCII texture overlay (`#doodle-overlay`)

### 5.3 CSS Custom Properties

The theme system is driven entirely by CSS custom properties on `:root`:

**Core palette:**
- `--bg` / `--bg2` -- Background colors (`#0a0008` / `#0e000e`)
- `--text` / `--text-dim` -- Text colors
- `--code-bg` -- Code block background
- `--border` -- Border color
- `--crimson` / `--violet` / `--accent` -- Brand colors

**Aspect-reactive properties (updated by JS on aspect switch):**
- `--asp` -- Active aspect primary color
- `--asp-glow` -- Aspect glow (semi-transparent)
- `--asp-mid` -- Aspect midtone (low-opacity)

**Per-aspect named properties:**
- `--asp-morrigan: #8B0000` (crimson)
- `--asp-nyx: #4B0082` (indigo)
- `--asp-echo: #00308F` (blue)
- `--asp-eris: #8B4513` (sienna)
- `--asp-cassandra: #004D4D` (teal)
- `--asp-lilith: #3D0C11` (dark burgundy)

**Warframe chrome:**
- `--wf-cut` -- Corner clip size (12px)
- `--wf-panel-bg` / `--wf-panel-bg2` -- Panel gradient backgrounds
- `--wf-line` / `--wf-line-dim` -- Border line colors (aspect-mixed)
- `--wf-glow` -- Panel glow color

**Scale/intensity:**
- `--fx-strength` -- Global visual intensity multiplier (1.5 default)
- `--text-xs` through `--heading` -- Font size scale

### 5.4 Light Theme

`body.theme-light` overrides core palette variables for a light mode.
Toggle is managed by `layla-input.js` via body class toggle, persisted in
localStorage as `layla_theme`.

### 5.5 Aspect Switching Visuals

When `setAspect()` is called:

1. CSS variables `--asp`, `--asp-glow`, `--asp-mid` are updated on `document.documentElement`
2. `data-aspect` attribute is set on `<body>`, triggering CSS rules like `body[data-aspect="morrigan"] { --asp: var(--asp-morrigan); }`
3. Background pattern changes via `--asp-bg-pattern` (per-aspect SVG tile)
4. Sprite field SVG is swapped with transition animation
5. Doodle overlay content regenerates
6. Aspect switch flash animation (`.asp-switch-flash`) triggers 0.55s glow burst

### 5.6 Accessibility

- **Skip-to-content link** -- `.skip-to-content` (WCAG 2.1 AA) visible on focus
- **Focus rings** -- `:focus-visible` with 2px solid aspect-colored outlines, 2px offset
- **High contrast** -- `@media (prefers-contrast: high)` disables glows, increases border visibility
- **Reduced motion** -- `@media (prefers-reduced-motion: reduce)` disables scanlines, title animations
- **ARIA attributes** -- `aria-selected`, `aria-hidden` on panel tabs; `aria-hidden` on wizard overlay
- **Focus traps** -- `layla-perf.js` implements focus trapping for modal overlays (plan viz, artifact edit)
- **Keyboard navigation** -- Ctrl+/ (help), Ctrl+K (search), Ctrl+F (chat search), Ctrl+R (retry), Escape (dismiss)

### 5.7 Typography

- **Primary font**: `'JetBrains Mono', monospace`
- **Title font**: `'Cinzel', serif` (for the "Layla" brand title)
- **Font scale**: `--text-xs` (0.65rem) through `--heading` (1.1rem)
- **Code blocks**: Inherit JetBrains Mono with `--code-bg` background

---

## 6. PWA Support

### 6.1 Service Worker (`sw.js`)

Strategy: **cache-first for static assets, network-only for API calls**.

- **Cache name**: `layla-ui-v1`
- **Precache list**: 14 static assets (HTML, CSS, core JS files)
- **Install**: Precaches all listed assets, calls `self.skipWaiting()`
- **Activate**: Claims all clients immediately (`self.clients.claim()`)
- **Fetch handler**: Only intercepts GET requests with paths starting with `/ui`, `/layla-ui`, or `/manifest.json`. Returns cached response if available; otherwise fetches from network and caches the result.

### 6.2 Web App Manifest (`manifest.json`)

```json
{
  "name": "Layla",
  "short_name": "Layla",
  "start_url": "/ui",
  "display": "standalone",
  "icons": [SVG inline data URIs for 192x192 and 512x512]
}
```

Icons use inline SVG data URIs with the Layla sigil (trichotomy symbol) on
dark background, avoiding external asset dependencies.

### 6.3 PWA Limitations

- No `theme_color` or `background_color` in manifest
- No offline fallback page -- if cache misses, user sees browser error
- Service worker precache list is incomplete (missing many JS modules added in later phases)
- No cache versioning strategy beyond the static `layla-ui-v1` name

---

## 7. Security

### 7.1 XSS Prevention

- **DOMPurify** -- Vendored locally, invoked by `sanitizeHtml()` in `layla-utils.js` with a restricted allowlist of tags (`b`, `i`, `em`, `strong`, `code`, `pre`, `a`, `br`, `p`, `ul`, `ol`, `li`, `span`, `div`, `blockquote`, `h1`-`h6`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `details`, `summary`, `img`) and attributes (`href`, `src`, `alt`, `class`, `style`, `target`, `rel`)
- **Regex fallback** -- If DOMPurify is not available, a basic regex-based HTML stripper serves as fallback (strips all tags except the above allowlist via regex)
- **`escapeHtml()`** -- Used extensively across all modules for user-supplied data in HTML construction
- **Bootstrap XSS guard** -- Fallback `triggerSend()` escapes `<` and `>` before DOM insertion

### 7.2 Remote Access Authentication

`layla-bootstrap.js` patches `window.fetch` to add `Authorization: Bearer <token>` when:
- The hostname is not `127.0.0.1` or `localhost`
- `layla_remote_api_key` is present in localStorage

This enables remote access without requiring per-request token management in each module.

### 7.3 Content Security Considerations

- No Content Security Policy (CSP) headers are enforced client-side
- `innerHTML` assignment is used extensively across all modules, relying on per-call escaping discipline
- Some modules construct HTML via string concatenation with `escapeHtml()` calls, creating risk if any call is missed
- DOMPurify sanitization is applied only to markdown-rendered assistant responses, not to all dynamically generated HTML
- Code blocks support "Apply" buttons that trigger workspace file writes (requires server-side approval gates)

### 7.4 Device Pairing Security

- PIN-based pairing with server-generated PIN and TTL countdown
- Paired device permission model with individual toggles
- No client-side certificate pinning or additional transport security

---

## 8. Performance

### 8.1 Polling Architecture

Multiple concurrent polling timers run when the application is active:

| Timer | Interval | Source | Cleared? |
|-------|----------|--------|----------|
| Health check | 20s | layla-app.js (DOMContentLoaded) | Paused on tab hidden |
| Connection banner | 15s | layla-app.js (DOMContentLoaded) | Paused on tab hidden |
| Context row | 12s | layla-app.js (DOMContentLoaded) | Paused on tab hidden |
| Peer discovery | 10s | layla-pairing.js | Yes (stopPeerPolling) |
| Mission status | 5s | layla-research.js | **Never cleared** (leak) |
| Autonomous progress | 1.5s | layla-autonomous.js | Yes (on completion) |

`layla-app.js` pauses health/connection/context polling on `visibilitychange`
when the tab is hidden, resuming when visible.

### 8.2 Lazy Initialization

`layla-perf.js` defers expensive initialization:

- **Memory browser** -- Not loaded until Memory tab is opened
- **Artifact scanner** -- Deferred until Artifacts tab is activated
- **Health endpoint warm-up** -- Scheduled via `requestIdleCallback`

### 8.3 IndexedDB Caching

Conversations are cached in IndexedDB (`layla-ui` database) to reduce
re-fetching on navigation.  The store uses an `updated_at` index for sorted
access.

### 8.4 Rendering Optimizations

- Messages use direct DOM manipulation (no virtual DOM diffing)
- Stream tokens are appended as text nodes to the active bubble
- Search uses 320ms debounce with AbortController to cancel stale requests
- Artifacts limited to 40 entries with FIFO eviction
- Canvas-based Gantt chart avoids DOM overhead for plan visualization

### 8.5 Resource Loading

- All JS loaded synchronously via `<script>` tags (no `defer`/`async`)
- Third-party libs (marked, DOMPurify, hljs) loaded from CDN
- CSS loaded via `<link>` in `<head>`
- SVG sprites loaded on-demand per aspect switch
- No code splitting, tree-shaking, or bundling

---

## 9. Known Issues & Bugs

### 9.1 Confirmed Bugs

**BUG: Artifact scanner uses wrong CSS selector** (`layla-artifacts.js`, line 32)
- `laylaArtifactsScan()` queries for `.msg.layla` (compound class) but the actual message class is `msg-layla` (hyphenated single class)
- Effect: Artifact scanner never finds any messages to scan
- Fix: Change selector to `.msg-layla`

**BUG: Artifact send-edit targets wrong input element** (`layla-artifacts.js`, line 141)
- `laylaArtifactSendEdit()` looks for `#input` or `#user-input` but the actual input element ID is `msg-input`
- Effect: Edited artifact content cannot be sent back to chat
- Fix: Change selector to `#msg-input`

**BUG: Mission status polling never cleared** (`layla-research.js`)
- `refreshMissionStatus()` is called via `setInterval(refreshMissionStatus, 5000)` but the interval is never stored or cleared
- Effect: Polling continues indefinitely even after mission completes, causing unnecessary network traffic
- Fix: Store interval ID and clear it on mission completion or page navigation

### 9.2 Design Concerns

**CONCERN: innerHTML usage without consistent sanitization**
- Many modules construct HTML via string concatenation and assign via `innerHTML`
- While `escapeHtml()` is used in most places, the pattern is error-prone
- Only assistant message rendering goes through DOMPurify; all other dynamic HTML relies on manual escaping discipline

**CONCERN: ES5/ES6 inconsistency**
- Core modules use ES5 for compatibility; newer modules use ES6 features (const, let, arrow functions, optional chaining)
- This creates confusion about the target environment and could break in older browsers

**CONCERN: Service worker precache list is incomplete**
- `sw.js` precaches only 14 files but the app loads 28+ JS modules
- Later-added modules (research, autonomous, pairing, character-creator, perf) are not precached
- The cache name (`layla-ui-v1`) is static with no invalidation strategy

**CONCERN: Global namespace pollution**
- All modules expose functions via `window.*`, creating a flat namespace with potential collision risks
- No namespacing convention (e.g., `window.layla.module.fn`)

**CONCERN: No error boundary or graceful degradation**
- If any script in the load chain throws, subsequent scripts may fail silently
- `layla-bootstrap.js` provides a fallback `triggerSend()` for basic chat functionality, but most features have no fallback

**CONCERN: Excessive localStorage usage**
- 25+ keys with no cleanup strategy
- No versioning or migration logic for key format changes
- Per-host workspace preset keys could accumulate indefinitely

---

## 10. Stability Assessment

### 10.1 Overall Maturity: BETA

The UI is functional and feature-rich but exhibits characteristics of rapid
organic growth without refactoring passes:

| Aspect | Rating | Notes |
|--------|--------|-------|
| Core chat flow | **Stable** | FSM guards concurrent sends; stream + non-stream paths well-tested |
| Message rendering | **Stable** | Markdown/DOMPurify/hljs pipeline is solid |
| Conversation management | **Stable** | Full CRUD with search, tags, pinning |
| Aspect switching | **Stable** | CSS variable approach is clean and reliable |
| Settings/Config | **Stable** | Dynamic schema-driven form works well |
| Voice system | **Moderate** | Depends on browser MediaRecorder support; server TTS fallback adds resilience |
| Research/Autonomous | **Moderate** | Mission status polling leak; approval flow functional |
| Pairing/Networking | **Moderate** | PIN flow is sound; mDNS dependent on network environment |
| Character Lab | **Moderate** | Feature-complete but complex; 664-line module |
| Artifacts | **Broken** | Two confirmed bugs prevent core scanning and editing functionality |
| PWA | **Incomplete** | Service worker caches only a subset of assets; no offline fallback |
| Performance | **Moderate** | Polling architecture creates baseline network load; no bundling; lazy init helps |
| Security | **Moderate** | DOMPurify for rendered content; global innerHTML pattern is risk-prone; no CSP |

### 10.2 Strengths

1. **Resilient bootstrap** -- `layla-bootstrap.js` provides fallback chat functionality even if later scripts fail
2. **Aspect theming** -- CSS custom property architecture enables seamless visual switching across the entire UI with minimal JS
3. **Progressive onboarding** -- Three-layer onboarding (setup overlay -> wizard -> onboarding tour) guides new users without blocking power users
4. **Accessibility foundations** -- Skip-to-content, focus rings, ARIA attributes, reduced-motion support, high-contrast mode, focus traps
5. **Stream rendering** -- SSE + ReadableStream with stall detection, first-token timers, and graceful error recovery
6. **Deep configurability** -- Settings schema, content policy, deliberation modes, character customization all surfaced in UI

### 10.3 Risks

1. **No build pipeline** -- No minification, bundling, or tree-shaking; 28+ script tags load synchronously
2. **Global namespace** -- All inter-module communication via `window.*` with no collision protection
3. **Polling accumulation** -- Up to 6 concurrent polling timers in active use, one with a confirmed leak
4. **innerHTML everywhere** -- Security depends on per-call escaping discipline rather than structural enforcement
5. **No automated UI tests** -- No test files observed for any frontend modules

### 10.4 Recommendations

1. **Fix the three confirmed bugs** -- Artifact selector, artifact input ID, mission status polling leak
2. **Complete the service worker precache list** -- Add all JS modules and implement cache versioning
3. **Add CSP headers** -- Server-side Content-Security-Policy to mitigate XSS risk
4. **Namespace globals** -- Group window exports under `window.layla.*` to prevent collisions
5. **Introduce a build step** -- Even a simple concatenation + minification would reduce load time and enable source maps
6. **Add UI smoke tests** -- Browser-based tests for core flows (send message, switch aspect, create conversation)

---

*Document generated from source analysis of `agent/ui/` (index.html + 28 JS modules + 2 CSS files + sw.js + manifest.json).*

# GUI Audit 01 — The Core Chat Loop + Conversations

**Scope:** Composer, send-time toggles, the send pipeline (`POST /agent`), streaming/trace/deliberation rendering, per-message actions, compaction/context, and the conversations rail.
**Method:** Read-only, evidence-based. Every claim cites `file:line`. Nothing modified.
**Date:** 2026-07-02

> **Orientation correction (important):** `.planning/GUI-FEATURE-MAP.md` describes a *proposed* rebuild (a chat-options popover, 8 grouped settings, rail destinations). **That rebuild is NOT built.** The live UI is the ES-module system under `agent/ui/` — `index.html` loads a single `<script type="module" src="/layla-ui/main.js">` (`index.html:1273`) and the comment at `index.html:1275` states "Phase 3 complete: All 28 IIFE scripts removed." So `conversations.js`, `chat-render.js`, `input.js`, `app.js` etc. are the **current, live** UI, not legacy. This audit describes what actually ships today. Where the map's "popover" is claimed, reality is: **the send-time toggles live in the right-panel "Settings" (prefs) tab**, not next to the composer.

---

## 0. Architecture of the send path (how the pieces connect)

- **Entry point:** `agent/ui/main.js` is the module entry. It imports all component modules, calls each `init*()`, wires a document-level event-delegation router (`core/actions.js`), and registers action names → handlers (`main.js:265-470`).
- **Event delegation:** DOM elements use `data-action` / `data-on-input` / `data-on-change` / `data-on-keydown` / `data-on-drop` attributes; `core/actions.js:74-162` routes them to registered handlers, falling back to `window[name]` for compat.
- **State:** `core/state.js` is an observable store with a chat FSM (`idle → sending → streaming → done/error`, `state.js:28-34`, `state.js:210-242`). `window.laylaChatFSM` is the FSM the send loop guards against.
- **Compat bridge:** `core/compat.js` re-exports module functions to `window.*` (`compat.js:478 window.send = send`) so `data-action="triggerSend"` and legacy references resolve.
- **The Send button** (`index.html:417`, `data-action="triggerSend"`) → `bootstrap.triggerSend()` (`bootstrap.js:56`) → prefers `window.send()` (`bootstrap.js:58`), i.e. `app.send()` (`app.js:234`). `triggerSend` only falls back to its own minimal fetch if `window.send` is missing (it never is in practice) — that fallback (`bootstrap.js:83-122`) is effectively dead but harmless.
- **Enter-to-send:** `input.onInputKeydown` (`input.js:109`) does NOT itself send; a separate keydown binding (`bootstrap.js:127+`, `bindChatInputNow`) handles Enter → `triggerSend`.

---

## 1. Composer

### 1.1 `msg-input` (the textarea)
**WHAT:** The message box (`index.html:409`). `rows="1"`, grows via CSS; `data-on-keydown="onInputKeydown"` and `data-on-input="onInputChange"`.
**WHY:** Primary user input.
**HOW/OPTIONS:** Type; Enter sends, Shift+Enter newlines; Ctrl+K clears (`input.js:111`); Ctrl+R retries (`input.js:112`); Ctrl+F opens chat-search (`input.js:114`); Ctrl+/ opens Help (`input.js:113`); ↑/↓ cycle prompt history when caret at start/end (`input.js:116-144`).
**TRACE:** keystroke → `onInputChange` (`input.js:93`) → `toggleSendButton()` (empties/enables Send, `chat-render.js:892`) + `_checkUrlInInput` (URL chip) + `_getMentionQuery` (mention dropdown). Enter → `bootstrap` keydown → `triggerSend` → `app.send()`.
**STATUS:** **working**.

### 1.2 Send / Cancel / Retry buttons
- **Send** (`send-btn`, `index.html:417`) → `triggerSend` → `app.send()` (`app.js:234`). **working**.
- **Cancel/Stop** (`cancel-send-btn`, `index.html:416`, `display:none`) → `cancelActiveSend()` (`app.js:66`) aborts the active `AbortController` (`_activeAgentAbort.abort()`). Shown/hidden by the FSM chrome sync (`chat-render.js:870-873` toggles it on `sending`/`streaming`). **working**.
- **Retry / "↻ Regenerate"** (`retry-btn`, `index.html:415`, `display:none`) → `retryLastMessage()` (`chat-render.js:841`) which removes the last you/sep/layla triple and re-sends `window._lastDisplayMsg`.
  **STATUS: partial (button never appears).** Grep shows **no code ever un-hides `#retry-btn`** — the FSM sync only toggles `#cancel-send-btn` (`chat-render.js:871`), never `#retry-btn`; the only `retryBtn` writers in JS are for the *unrelated* `setup-retry-btn` (`setup.js:229,276`). So the inline Regenerate button is dead chrome. Retry IS reachable via **Ctrl+R** and the overflow menu ("↻ Retry last", `index.html:221`), so the *feature* works; only the composer button is orphaned.

### 1.3 Mic (voice input)
**WHAT:** `mic-btn` (`index.html:414`) → `toggleMic()` (`voice.js:68`). Records via `MediaRecorder` (`voice.js:76-101`), on stop POSTs webm bytes to `/voice/transcribe` (`voice.js:122`), then puts the transcript into `msg-input` and **auto-calls `send()`** (`voice.js:133`).
**WHY:** Hands-free input.
**TRACE:** click → `getUserMedia` → record → `/voice/transcribe` (router `voice.py:14`) → `{ok,text}` → fill input → `window.send()`.
**STATUS:** **working** (backend endpoint exists, `voice.py:14`). UX caveat: it auto-sends immediately with no confirm step, and shows a generic "Could not transcribe" on empty.

### 1.4 File attach + drop
**WHAT:** 📎 label wraps a hidden `<input type=file>` (`index.html:411-413`, `data-on-change="attachFileChange"` → `input.attachFile`, `main.js:467`). Drop zone is the whole input area (`index.html:388-391`, `data-on-drop="handleFileDrop"`).
**Behavior:** Reads file **as text** (`FileReader.readAsText`), truncates to 120 000 chars, and **appends the raw text into `msg-input`** as `--- file: NAME ---\n<text>` (`input.js:203-238`).
**WHY:** Quick "paste a file into the prompt."
**STATUS:** **working**, but **text-only**: binaries/images become garbage. Images are NOT routed to the `/agent` `image_base64`/`image_url` path (that path exists server-side, `agent.py:349`, `_get_image_context`) — so the composer cannot attach an image for vision even though the backend supports it → **backend-without-ui** for image attach specifically. The `#file-context-chips` element (`index.html:392`) is defined but never populated (no writer) → dead chrome.

### 1.5 `@mention` aspect-switch
**WHAT:** Typing `@` opens a dropdown of the 6 aspects (`input.js:40-59`); Tab/Enter/click picks one and rewrites the token to `@id ` (`_pickMention`, `input.js:80`). At send, `send()` re-parses `^@([a-z]+)` (`app.js:258-271`) and, if it matches a known aspect (and not aspect-locked), overrides `msgAspect` for that one message and strips the prefix from the sent text (keeping it in the *displayed* line, `app.js:276`).
**WHY:** One-shot voice switch without changing the sticky sidebar aspect.
**STATUS:** **working**. Minor: only a leading `@aspect` is honored at send (mid-text mentions render in the dropdown but only the first token drives routing).

### 1.6 URL-detect chip ("Fetch content")
**WHAT:** On input, a regex finds the first `https?://…` (`input.js:165-182`) and shows `#url-detect-chip` (`index.html:393-398`) with the hostname. "Fetch content" (`acceptUrlFetch`, `input.js:190`) **rewrites the message** to `Fetch and summarize this URL:\n<url>` and toasts "press Send."
**WHY:** Nudge toward web-fetch behavior.
**STATUS:** **partial / cosmetic.** It does **not** fetch anything — it only edits the prompt text and relies on the agent choosing a fetch tool. There is no dedicated fetch call, no content preview, and success depends entirely on the model/tools. The label "Fetch content" over-promises. Functionally it's a prompt-template button.

### 1.7 Working-notes / compose panel
**WHAT:** `#compose-panel` (`index.html:365-371`) with `#compose-draft` textarea. Toggled by "📝 Working notes" (overflow, `index.html:223`) → `toggleComposePanel` (`chat-render.js:179`); open state persisted to `localStorage.layla_compose_open`. Draft text persisted on input to `localStorage.layla_compose_draft` (`data-on-input="saveComposeDraft"`, `main.js:464`).
**Send integration:** `send()` reads `#compose-draft` and puts it into the request as **`context`** (`app.js:293-298, 302`), i.e. merged into the model's context but not shown as a chat line (matches the panel's own label, `index.html:367`).
**STATUS:** **working**. Caveat: the draft is **never cleared** after send — it silently rides along on *every* subsequent message until the user deletes it. That is a real footgun (stale specs/errors leak into later turns).

### 1.8 Pipeline-clarify panel
**WHAT:** `#pipeline-clarify-panel` (`index.html:399-405`) with a `pipeline-clarify-questions` `<pre>` and a `#pipeline-clarify-answers` textarea. At send, if the answers box has text, `send()` attaches it as **`clarification_reply`** and hides the panel (`app.js:311-317`).
**WHY:** Answer the engineering-pipeline's clarifying questions on the next send.
**STATUS: broken (UI half-missing).** The panel is **only ever hidden and read** — grep shows **no code path that shows the panel or writes the questions** (`app.js:315` hides; `main.js:461` dismisses; the `.pipeline-clarify-questions` node is never assigned). Meanwhile the server genuinely returns `status:"pipeline_needs_input"` + `questions` in both plan-light (`agent.py:436-452`) and stream/JSON done frames (`agent.py:731-736`), but `app.js`'s stream/JSON handlers **never inspect `pipeline_needs_input`/`questions`** (grep of `app.js` for `questions`/`needs_input` = 0 hits). Net: the clarify round-trip cannot complete through this UI — the questions are dropped, the panel never opens, and the answers box (if a user finds it) is the only wired half.

### 1.9 Context-usage bar + token-pressure hint
**WHAT:** `#ctx-usage-row` (`index.html:419-425`): a `#ctx-bar-fill` progress bar, a `#ctx-usage-label` ("Ctx: —"), and a hidden `#token-pressure-hint` ("⚡ chunking").
**STATUS: dead / placeholder.** Grep for any writer to `ctx-bar-fill`, `ctx-usage-label`, or `token-pressure-hint` across `agent/ui/` returns **nothing** (only the HTML definition, an app.js *doc comment*, and a compat re-export of the unrelated `updateContextChip`). The bar is hard-coded `width:0%` and the label永 reads "Ctx: —"; the pressure hint is never un-hidden. The backend *does* emit context pressure via SSE `ctx_warn` frames with `ctx_pct` (`agent.py:701-702`) and there are UX labels for it (`chat-render.js:31-32`), but the SSE consumer in `app.js` never handles `ctx_warn`/`ctx_pct` (the stream loop handles `token`, `done`, `error`, `ux_state`, `thinking`, `tool_step`, `model_selection`, `deliberation`, `pulse` — not `ctx_pct`). So token-pressure is computed server-side and thrown away client-side. **ui-without-backend-hookup** (both ends exist, the wire is missing).

### 1.10 Context chip (thread info)
**WHAT:** `#context-chip` (`index.html:364`) shows `Thread: <cid> · Project: <p> · Facet: <aspect> · WS: <path>` via `updateContextChip()` (`conversations.js:50-63`). Refreshed on conv load/new/delete, aspect change, project change, and after each send (`app.js:573`).
**STATUS:** **working**. (Distinct from the context-*usage* bar above; don't conflate them.)

---

## 2. Send-time toggles (what flipping each actually does)

All of these live in the **right panel → "Settings" (prefs) tab**, group "Chat & Streaming" / "Permissions & Safety" (`index.html:572-653`) — NOT in a composer popover. `send()` reads a subset of them at send time (`app.js:284-317`).

| Toggle | Element | Read by `send()`? | What flipping it changes |
|---|---|---|---|
| **Stream** | `#stream-toggle` (`index.html:579`) | **Yes** (`app.js:285-286, 306`) | Chooses SSE (`stream:true`, `app.js:326`) vs JSON (`app.js:518`). SSE renders live tokens + trace; JSON renders one final bubble. Also persisted to `localStorage.layla_stream` (`voice.js:53-56`). **working.** |
| **Show thoughts** | `#show-thinking` (`index.html:582`) | **Yes** (`app.js:303`) | Sends `show_thinking:true`; server passes to the run (`agent.py:272, 651, 924`) so thinking tokens stream (rendered in the live "Thinking" box, `app.js:354-380, 442-445`). **working.** |
| **Speak replies (TTS)** | `#tts-toggle` (`index.html:585`, `data-on-change="toggleTts"`) | n/a (client-side) | Sets `window._ttsEnabled` + `localStorage.layla_tts` (`main.js:435-442`). After a reply, `speakText()` is called if enabled (`app.js:506, 542`). **working.** |
| **Plan first** | `#plan-mode-toggle` (`index.html:588`) | **NO** | **DEAD CONTROL.** `send()` never reads `#plan-mode-toggle`; grep of all `agent/ui/**` for `plan_mode` = 0 payload hits. The server fully supports `plan_mode` (`requests.py:28`, `agent.py:273, 420-533` — returns a plan for review), but no UI path sets it. So ticking "Plan first" does nothing. **broken / ui-without-backend-wire.** |
| **Think harder** | `#reasoning-effort` (`index.html:591`) | **NO** | **DEAD CONTROL.** Its enabled-state is managed (disabled unless Show-thoughts is on, `aspect.js:223-233`), but `send()` never reads it; grep for `reasoning_effort` in `agent/ui/**` = 0. Server supports it (`requests.py:32`, `agent.py:277` maps `"high"`→extra budget). Ticking it does nothing. **broken.** |
| **Pipeline** | `#engineering-pipeline-mode` (`index.html:596`) | **Yes** (`app.js:309-310`) | If value ≠ `chat`, sends `engineering_pipeline_mode` (`plan`/`execute`). Server gates on `engineering_pipeline_enabled` config (`agent.py:296-303, 421, 663, 934`). Also persisted to `localStorage.layla_engineering_pipeline_mode` (`main.js:443-445`). **working** *if* the pipeline is enabled in config; **partial** otherwise (selecting `plan`/`execute` is silently ignored when `engineering_pipeline_enabled` is false — no user feedback). Note the panel select `plan` overlaps the dead "Plan first" checkbox — two controls for adjacent intents, one dead. |
| **Deliberation** | `#deliberation-mode-select` (`index.html:604`) | **NO (per-request)** | Writing this **POSTs `/settings` `{deliberation_mode}`** immediately (`settings-full.js:347-361`), persisting to server config. The agent reads `cfg["deliberation_mode"]` server-side (`reasoning_handler.py:164`, `stream_handler.py:181-185`, `debate_engine.py:107,265`). So it's a *global config toggle*, not a per-send flag — changing it affects all conversations until changed again. Loaded on init from `/health` config (`settings-full.js:407-416`). **working** (but semantics differ from the other "per-send" toggles — it's sticky/global). |
| **Model override** | `#model-override-visible` (`index.html:614`, → mirrors to hidden `#model-override`) | **Yes** (`app.js:287-288, 308`) | `data-on-change="syncModelOverride"` copies value into the hidden `#model-override` (`main.js:446-449`); `send()` reads the hidden one and sends `model_override` (`coding`/`reasoning`/`chat`). Server routes accordingly (`agent.py:276, 654, 926`). **working.** |
| **Allow Write** | `#allow-write` (`index.html:630`) | **Yes** (`app.js:304`) | Sends `allow_write`. **Server fail-closes for non-local callers** (`agent.py:262-269`): a remote client cannot self-grant write. Local caller honored → tools may modify files. **working.** |
| **Allow Run** | `#allow-run` (`index.html:633`) | **Yes** (`app.js:305`) | Sends `allow_run`; same local-only guard. Enables command-execution tools. **working.** |
| **Bypass All Approvals** | `#tool-approval-bypass` (`index.html:637`) | n/a (persisted to config) | On change, force-checks Allow Write+Run, shows the warning banner, and POSTs `/settings {tool_approval_bypass}` (`app.js:700-732`). On load, reads it back from `/health effective_config` (`app.js:706-715`). Skips the approval queue for every tool. **working** (correctly gated + warned). |

**Toggles named in the brief that DON'T exist as distinct controls here:** `reasoning-effort` slider (it's a checkbox), `plan-first`/`plan-mode` (checkbox exists but dead), `deliberation solo/auto/debate` (exists, sticky), `bypass-approvals` (exists). There is **no** composer "chat-options popover" — the map's Tier-1 concept is unbuilt.

---

## 3. The send pipeline

### 3.1 `send()` request assembly — `app.js:234-576`
1. Guard: hide mention dropdown; read+trim `#msg-input`; bail if empty or `_laylaSendBusy`; FSM `beginSend()` (`app.js:236-246`).
2. New `AbortController` → `_activeAgentAbort` (`app.js:248-249`); start header progress, clear operator trace, start stream stats (`app.js:253-255`).
3. Resolve aspect from leading `@mention` unless locked (`app.js:257-272`).
4. Clear input, render the user bubble + separator, remember `_lastDisplayMsg` (`app.js:274-280`).
5. `ensureLaylaConversationId()` — generates a UUID if none, persists to `localStorage.layla_current_conversation_id` (`app.js:103-120, 282`).
6. Build payload (`app.js:296-317`): `message`, `context`(=compose draft), `workspace_root`, `project_id`(from localStorage), `aspect_id`, `conversation_id`, `show_thinking`, `allow_write`, `allow_run`, `stream`; conditionally `model_override`, `engineering_pipeline_mode`, `clarification_reply` (clearing the answers box + hiding clarify panel).
7. Branch on `streamMode`.

### 3.2 Streaming branch (SSE) — `app.js:326-517`
- `POST /agent` with `signal: ac.signal`, timeout `max(streamTimeout, 300000)` (`app.js:327-331`).
- Builds a live Layla bubble with a typing placeholder + a `Thinking (live)` `<details>` + a `memory-attribution` meta line (`app.js:346-387`).
- Timers: `metaTimer` (updates "Status · Ns · N chars" every 500ms, `app.js:388-391`), `firstTokenTimer` (1.8s → "Waiting for first token", `app.js:393-399`), `stalledTimer` (silence → "Stalled — Retry suggested", `app.js:400-408`; reset by `pulse` frames, `app.js:422-425`).
- Reads `data: {…}` SSE frames (`app.js:409-421`) and handles: `error` (replace bubble with error, `app.js:426-435`), `ux_state` (status label, `app.js:436-441`), `thinking`/`think` (append to Thinking box, `app.js:442-445`), `tool_step`/`tool_start` (append `▸ tool [phase] ok — summary`, bump stream stats step counter, `app.js:446-453`), `model_selection` (set `#stream-model-badge`, `app.js:454-458`), `deliberation` (badge + store meta, `app.js:459-471`), `token` (accumulate, live-render markdown via `marked` + `sanitizeHtml`, `app.js:472-493`), `done` (final render, close thinking, TTS, refresh maturity, ingest artifacts, render deliberation transcript, `app.js:494-515`).
- **Not handled:** `ctx_warn`/`ctx_pct` (see §1.9), `pipeline_needs_input`/`questions` (see §1.8). These frames arrive and are ignored.

### 3.3 JSON branch — `app.js:518-546`
- `POST /agent` (no stream), timeout `max(jsonTimeout,120000)`; on non-ok/`ok:false` renders `formatAgentError`; else renders `addMsg('layla', resp, aspect, deliberated, steps, uxStates, memInf)` from `data.state` (`app.js:535-541`), TTS + maturity + artifact ingest.

### 3.4 Server: `POST /agent` — `agent/routers/agent.py:248-1075`
- Validates via `AgentRequest` (`requests.py:14-47`).
- Remote write/run fail-close (`agent.py:262-269`).
- Special early paths: empty message (`agent.py:355-368`), `understand_mode` (repo map, `agent.py:371-418`), plan-light / plan_mode (returns plan or `pipeline_needs_input`, `agent.py:420-533`), fast-path trivial greetings (`agent.py:542-591`), response cache (`agent.py:593-618`), model-not-ready 503 (`agent.py:620-623`).
- **Streaming** (`agent.py:625-912`): spawns a worker thread running `autonomous_run` via `coordinator.run` (`agent.py:37-42, 641-671`), drains a `ux_state_queue` into SSE frames (`agent.py:673-704`), then either streams tokens (`stream_pending` → `stream_reason`, `agent.py:737-848`) or emits a single `done` frame with the final text, steps, `reasoning_tree_summary`, `deliberation`, optional `decision_trace` (`agent.py:849-892`). Client-disconnect is watched via `_watch_client_disconnect` (`agent.py:45-54, 674`).
- **JSON** (`agent.py:914-1075`): runs the loop in a thread, strips/polishes output, persists to both in-memory history and the SQLite conversation (`append_conversation_message`/`create_conversation`, `agent.py:992-1006`), and returns a rich payload incl. `model_selection` (`agent.py:1030-1034`), `artifacts` (`agent.py:1054-1058`), `confidence`, `run_budget_summary`.
- **Persistence model:** every turn writes to `conversations`/`messages` tables server-side (`agent.py:812-819, 862-871, 994-1001`) — this is why the rail can reload messages (`/conversations/{id}/messages`). Client localStorage is a secondary cache.
**STATUS (pipeline):** **working** — this is the mature, load-bearing core.

### 3.5 Streaming render chrome
- **Operator trace dock** `#operator-trace-dock` (`index.html:1077-1088`): `stream-step-badge`, `stream-model-badge`, `stream-step-counter`, `stream-token-counter`, `stream-elapsed-counter`, `operator-trace-log`. Driven by `chat-render.js:119-176` (`laylaStreamStatsStart/Step/Chars/Stop`) + `operatorTraceLine` (`chat-render.js:107-117`). **working.**
- **Header progress bar** `#header-progress-row` (`index.html:203`) via `laylaHeaderProgressStart/Stop` (`chat-render.js:82-99`). **working.**
- **Tool-trace ("What she did")**: rendered from `data.state.steps` in `addMsg` (`chat-render.js:577-602`). **working** (JSON path). In streaming, tool steps go to the live "Thinking" box instead.
- **Reasoning chain / reasoning-tree summary**: `laylaEnsureReasoningChain`/`laylaAppendReasoningStep` (`chat-render.js:809-838`) and `_renderReasoningTreeSummary` (`chat-render.js:360-377`). The tree summary IS produced by the server (`agent.py:809, 861, 990`) and passed as the 8th arg to `addMsg` — **but `app.js` never passes `reasoningTreeSummary`** when calling `addMsg` (`app.js:541` passes only 7 args), so the reasoning-tree summary block never renders in normal chat. **partial** (renderer exists, not fed). `laylaAppendReasoningStep` has no caller in the send loop either → **dead** in practice.
- **Deliberation transcript**: `_renderDeliberationTranscript` (`chat-render.js:634-694`) renders per-aspect responses, critiques, synthesis. Fed from SSE `deliberation` frames (`app.js:460-471, 511-514`) or JSON `deliberated` flag (`chat-render.js:605-615`). **working** when deliberation mode ≠ solo.

### 3.6 Per-message actions (on each Layla bubble)
- **copy** (`chat-render.js:509-525`) → clipboard. **working.**
- **remember** (`chat-render.js:527-537`) → `rememberLaylaBubble` → `POST /learn/` `{content, type:'fact', tags:'ui:remember'}` (`chat-render.js:380-412`; router `learn.py:72-104`). **working.**
- **correct** (`chat-render.js:539-549`) → `openFactCorrectionForm` (inline form, `chat-render.js:904-936`) → `submitFactCorrection` → `POST /learn/correct` `{query, correction, aspect_id}` (`chat-render.js:938-966`; router `learn.py:117-200` finds closest learning, updates, re-embeds). **working.**
- **apply pending file op** ("apply" on a code block): `_addApplyBtnToCodeBlock` (`chat-render.js:275-291`) → `_laylaApprovePendingForCodeBlock` fetches `/pending`, heuristically matches the code block's guessed path to a pending approval, then `POST /approve {id}` (`chat-render.js:234-273`). **working but fragile** — path-guess heuristic (`chat-render.js:224-232`) can approve the wrong pending op when multiple are queued (falls back to `todo[0]`, `chat-render.js:262`). Also the standalone diff-viewer applies (`input.js:407-437`, `confirmApplyFile`/`confirmApplyBatch`) are mostly **stubs** — `confirmApplyBatch` just toasts "batch id wiring is server-side" (`input.js:434-437`) and `confirmApplyFile` no-ops if no `_laylaDiffApprovalId` is bound (`input.js:407-411`), and nothing binds it in this flow → **stub/partial**.

---

## 4. Compaction & context

### 4.1 `/compact` (⊙ Compact)
**WHAT:** Header + topbar "⊙ Compact" (`index.html:183, 358`) → `compactConversation()` (`app.js:211-231`) → `POST /compact {conversation_id}` → toast "Compacted · messages in buffer: ~N" → `updateContextChip()`.
**Server:** `session.py:32-35` → `sync_compact_history()` (`route_helpers.py:159`).
**STATUS: partial.** The UI sends `{conversation_id}` (`app.js:219`) but **the server endpoint takes no body** and compacts the **global in-memory `_history`**, not the specific conversation (`session.py:33-35`). So Compact is conversation-agnostic — it trims the shared in-memory buffer regardless of which chat is open. It "works" (reduces context) but not per-conversation as the UI implies.

### 4.2 `/ctx_viz` (Context visualizer)
**WHAT:** Overflow menu "📊 Context visualizer" (`index.html:228`) opens `/ctx_viz` in a new tab. Server returns JSON `{n_ctx, budgets, sections:{conversation_history}}` (`session.py:38-50`).
**STATUS: partial (raw JSON, no visualizer).** The link opens the endpoint directly; there is no HTML view — the user sees raw JSON, not a "visualizer." Functional data, missing presentation. **ui-without-backend** for the *visual* part.

### 4.3 `/usage`
**WHAT:** `GET /usage` (`system.py:71-80`) returns per-session token usage.
**STATUS: backend-without-ui.** No composer/rail element calls `/usage` (the header token line uses `/session/stats` instead, `app.js:88-99`). The endpoint is orphaned from this cluster.

---

## 5. Conversations rail

### 5.1 New chat
**WHAT:** "+ New chat" (`index.html:237`) → `startNewConversation()` (`conversations.js:109-140`) → `POST /conversations {aspect_id}` (router `conversations.py:14-27`) → clears chat to empty state, sets `currentConversationId`, persists, re-renders rail. **working.**

### 5.2 List + render
**WHAT:** `_renderSessionList()` (`conversations.js:174-405`) fetches `/conversations?limit=30&offset=N` (or `/conversations/search?q=…` when a query is present, `conversations.js:209-211`), sorts pinned-first (`conversations.js:234-239`), renders each item with aspect dot, pin glyph, project, tags, title, date, and per-item rename/delete/pin buttons (`conversations.js:245-356`).
**STATUS: partial — pagination is broken.** The UI requests `&offset=` and shows a "Load more…" button (`conversations.js:358-366`), but **the server ignores offset**: `list_conversations_api(limit, tag)` (`conversations.py:30-37`) and `search_conversations_api(q, limit, tag)` (`conversations.py:40-47`) have **no `offset` parameter**. So "Load more" re-requests page 0 and appends duplicates (or no-ops). Rail effectively caps at the first `limit` results. The `_railHasMore` logic (`conversations.js:216`) can never advance meaningfully.

### 5.3 Search (`tag:` / `after:` / `before:`)
**WHAT:** Rail search box (`index.html:238`) debounced (`conversations.js:510-528`). Query is parsed for `tag:` (sent to server), `after:`/`before:` (client-side date filter, `conversations.js:181-228`), rest → server `q`. Global header search (`#global-search-input`, `index.html:208`) is a separate feature (search.js).
**STATUS: working** for `q`, `tag:`, and client-side `after:`/`before:`. (Server tag filter is honored, `conversations.py:31,41`.)

### 5.4 Rename / delete / pin / tags / export
- **Rename** ✎ (`conversations.js:267-285`) → `POST /conversations/{id}/rename {title}` (`conversations.py:97-110`). **working.**
- **Delete** ✕ (`conversations.js:286-297, 422-451`) → `DELETE /conversations/{id}` (`conversations.py:113-123`); clears view if current. **working.**
- **Pin** ⟐/⟡ (`conversations.js:298-308`) → `_togglePinned` — **localStorage only** (`conversations.js:153-171`); no server endpoint (none exists — correct). **working** (client-local, not synced across devices).
- **Tags** (right-click menu, `conversations.js:339-353`) → `POST /conversations/{id}/tags {tags}` (`conversations.py:50-61`). **working.**
- **Export** (right-click menu, `conversations.js:321-338`) → fetches `/conversations/{id}/messages?limit=2000`, downloads a JSON blob. **working.**
- **Context menu** (`conversations.js:312-354`) uses `laylaPrompt('rename|delete|pin|tags|export')` — a text prompt, not a real menu → clumsy UX but functional.

### 5.5 Persistence
- **Primary:** server SQLite (conversations/messages), written every turn (`agent.py:994-1001`) and read on load (`loadConversationIntoChat`, `conversations.js:81-106` → `/conversations/{id}/messages?limit=500`). **working.**
- **Boot restore:** `tryLoadActiveConversationOnBoot` reloads `localStorage.layla_current_conversation_id` (`conversations.js:143-150`). **working.**
- **Legacy localStorage sessions** (`SESSIONS_KEY='layla_sessions'`, `_saveCurrentSession`, `conversations.js:14, 27-47`): **dead code** — `_saveCurrentSession` has **no live caller** (only defined + re-exported, `conversations.js:532`). The `_renderSessionList` fallback to local sessions (`conversations.js:372-405`) only triggers if the server list fetch fails. Vestigial. **dead.**

### 5.6 Prompt history (↑ recall in composer)
**WHAT:** ↑ at caret-start pulls recent prompts (`input.js:116-127`) via `_ensurePromptHistory()` → `fetch('/conversations/prompt_history')` expecting `{history:[…]}` (`input.js:17-29`).
**STATUS: broken.** **The endpoint `/conversations/prompt_history` does not exist** (grep: no such route). The real endpoint is **`/history`** (`system.py:83-91`) returning `{prompts:[…]}` (different path AND different field name). `_ensurePromptHistory` catches the failure and sets `_promptHistoryList=[]` (`input.js:25-28`), so ↑ silently does nothing. The composer hint even advertises "↑ cycles recent prompts" (`index.html:426`) — a promise the wiring can't keep.

---

## STATUS TABLE

| Feature | Status | Evidence (file:line) |
|---|---|---|
| msg-input textarea + shortcuts | working | `index.html:409`; `input.js:93,109-160` |
| Send button → send() | working | `index.html:417`; `bootstrap.js:56-58`; `app.js:234` |
| Cancel/Stop (abort) | working | `index.html:416`; `app.js:66-71`; `chat-render.js:871` |
| Retry inline "↻ Regenerate" button | partial (never shown) | `index.html:415`; no un-hider (grep); `chat-render.js:871` toggles only cancel |
| Retry via Ctrl+R / overflow | working | `input.js:112`; `index.html:221`; `chat-render.js:841` |
| Mic → transcribe → auto-send | working | `voice.js:68-144`; `voice.py:14` |
| File attach/drop (text) | working | `index.html:411-413`; `input.js:203-238` |
| Image attach → vision | backend-without-ui | `agent.py:349,74-166`; no composer image path |
| `#file-context-chips` | dead | `index.html:392`; no writer (grep) |
| @mention aspect-switch | working | `input.js:40-90`; `app.js:258-272` |
| URL-detect chip "Fetch content" | partial (rewrites prompt only) | `input.js:165-200`; no fetch call |
| Working-notes/compose panel | working (never auto-clears) | `index.html:365-371`; `app.js:293-298`; `chat-render.js:179-188` |
| Pipeline-clarify panel | broken (questions never shown) | `index.html:399-405`; `app.js:311-317`; no writer to questions; server `agent.py:436-452,731-736` |
| Context-usage bar + token-pressure | dead / unhooked | `index.html:419-425`; no writer (grep); SSE `ctx_pct` ignored `agent.py:701-702` |
| Context chip (thread info) | working | `index.html:364`; `conversations.js:50-63` |
| Toggle: Stream | working | `index.html:579`; `app.js:285-286,306` |
| Toggle: Show thoughts | working | `index.html:582`; `app.js:303`; `agent.py:272,651` |
| Toggle: Speak replies (TTS) | working | `index.html:585`; `main.js:435-442`; `app.js:506,542` |
| Toggle: Plan first | broken (dead control) | `index.html:588`; not read in `app.js`; grep `plan_mode` in ui = 0 |
| Toggle: Think harder (reasoning-effort) | broken (dead control) | `index.html:591`; `aspect.js:223-233`; not read in `app.js` |
| Toggle: Pipeline mode | working if enabled / else silent | `index.html:596`; `app.js:309-310`; `agent.py:296-303,663` |
| Toggle: Deliberation mode | working (global config, sticky) | `index.html:604`; `settings-full.js:347-361`; `stream_handler.py:181-185` |
| Toggle: Model override | working | `index.html:614`; `main.js:446-449`; `app.js:287-288,308` |
| Toggle: Allow Write | working (local-only) | `index.html:630`; `app.js:304`; `agent.py:262-269` |
| Toggle: Allow Run | working (local-only) | `index.html:633`; `app.js:305` |
| Toggle: Bypass approvals | working (gated+warned) | `index.html:637`; `app.js:700-732` |
| POST /agent (SSE + JSON) | working | `agent.py:248-1075`; `app.js:326-546` |
| Stream stats / operator trace dock | working | `index.html:1077-1088`; `chat-render.js:119-176` |
| Tool-trace "What she did" | working (JSON path) | `chat-render.js:577-602` |
| Reasoning-tree summary render | partial (renderer not fed) | `chat-render.js:360-377`; `app.js:541` passes 7 args (no tree) |
| Reasoning-chain append | dead (no caller) | `chat-render.js:825-838`; no send-loop caller |
| Deliberation transcript | working (mode≠solo) | `chat-render.js:634-694`; `app.js:460-471,511-514` |
| Per-msg copy | working | `chat-render.js:509-525` |
| Per-msg remember → /learn | working | `chat-render.js:380-412`; `learn.py:72-104` |
| Per-msg correct → /learn/correct | working | `chat-render.js:938-966`; `learn.py:117-200` |
| Apply pending file op (code block) | working but fragile | `chat-render.js:234-291` (heuristic path-match) |
| Diff-viewer apply / batch apply | stub | `input.js:407-437` (no binding; toasts only) |
| /compact | partial (ignores conversation_id) | `app.js:219`; `session.py:32-35` (global buffer) |
| /ctx_viz | partial (raw JSON, no view) | `index.html:228`; `session.py:38-50` |
| /usage | backend-without-ui | `system.py:71-80`; no caller in cluster |
| New chat | working | `conversations.js:109-140`; `conversations.py:14-27` |
| Rail list render | partial (offset ignored) | `conversations.js:209`; `conversations.py:30-37` (no offset) |
| Rail "Load more" pagination | broken | `conversations.js:358-366`; server has no offset |
| Rail search q/tag/after/before | working | `conversations.js:181-228`; `conversations.py:40-47` |
| Rename | working | `conversations.js:267-285`; `conversations.py:97-110` |
| Delete | working | `conversations.js:422-451`; `conversations.py:113-123` |
| Pin | working (localStorage only) | `conversations.js:153-171` |
| Tags | working | `conversations.js:339-353`; `conversations.py:50-61` |
| Export (JSON) | working | `conversations.js:321-338` |
| Persistence (server SQLite) | working | `agent.py:994-1001`; `conversations.js:81-106` |
| Legacy localStorage sessions | dead | `conversations.js:27-47,532` (no live caller) |
| Prompt-history ↑ recall | broken (wrong endpoint+field) | `input.js:19` `/conversations/prompt_history` (404); real `/history` `{prompts}` `system.py:83-91` |

---

## TOP UX PROBLEMS (ranked)

1. **Two "power" toggles are dead controls — "Plan first" and "Think harder" do nothing.**
   *Why/impact:* They sit prominently in the Settings panel with confident tooltips, but `send()` never reads them (`index.html:588,591`; grep of `agent/ui/**` for `plan_mode`/`reasoning_effort` = 0 payload hits) even though the server fully supports both (`agent.py:273,277,420-533`). Users toggle them expecting different behavior and get identical output — an erosion of trust that's invisible (no error, no feedback). Highest-severity because it's a *silent lie* about capability, and the backend is right there.

2. **The pipeline-clarify loop is unusable — questions are dropped, the panel never opens.**
   *Why/impact:* Engineering-pipeline "plan" mode is a headline feature, but when the server asks clarifying questions (`agent.py:436-452,731-736`), `app.js` never reads `pipeline_needs_input`/`questions` and never shows/populates `#pipeline-clarify-panel`. The answers half is wired to send `clarification_reply`, but there's no way to *see* what to answer. The pipeline appears to stall or reply generically. A whole interaction mode is functionally broken end-to-end in the UI.

3. **The context-usage bar is a permanent placeholder ("Ctx: —"), and token-pressure is thrown away.**
   *Why/impact:* Users on low-end machines (the product's stated audience) need to see context pressure to know when to Compact. The bar (`index.html:419-425`) has zero writers, and the server's `ctx_pct`/`ctx_warn` SSE frames (`agent.py:701-702`) are never consumed by `app.js`. So the one affordance that would tell a user "compact now" is decorative. Compaction itself is thus flown blind.

4. **Rail pagination is broken — "Load more" can't load more.**
   *Why/impact:* The UI paginates by `offset` (`conversations.js:209,358-366`) but the server ignores it (`conversations.py:30-47` accept only `limit`/`tag`). Any user with >30 conversations cannot reach older ones from the rail (only via search). For a "persistent memory / it grows with you" product, silently hiding history after 30 chats is a serious retention/navigation failure.

5. **Prompt-history recall (↑) is wired to a non-existent endpoint.**
   *Why/impact:* The composer hint explicitly promises "↑ cycles recent prompts" (`index.html:426`), but `input.js:19` hits `/conversations/prompt_history` (404) with the wrong response field; the real endpoint is `/history`→`{prompts}` (`system.py:83-91`). Pressing ↑ does nothing, silently. A basic, discoverable affordance that's advertised and dead.

6. **Working-notes draft never clears — stale context leaks into every later turn.**
   *Why/impact:* `#compose-draft` is merged into `context` on *every* send (`app.js:293-298`) and is never reset. A spec or pasted error left in the notes panel silently contaminates all subsequent, unrelated messages. Users won't connect degraded answers three turns later to a forgotten notes box.

7. **"Compact" implies per-conversation but acts globally.**
   *Why/impact:* The button lives in the per-chat topbar and the UI sends a `conversation_id` (`app.js:219`), but the server compacts a shared in-memory buffer (`session.py:32-35`). Behavior is inconsistent with the mental model — compacting from one chat affects the shared buffer, and per-conversation context isn't actually trimmed as implied.

8. **"Fetch content" URL chip over-promises — it only rewrites the prompt.**
   *Why/impact:* The chip labels the action "Fetch content" (`index.html:396`) implying retrieval/preview, but `acceptUrlFetch` merely templates the message text (`input.js:190-200`); success depends entirely on the model picking a fetch tool. No preview, no guarantee. Mismatched affordance language.

9. **Composer "↻ Regenerate" button is permanently invisible; retry only via Ctrl+R/menu.**
   *Why/impact:* `#retry-btn` (`index.html:415`) is `display:none` and nothing un-hides it (the FSM only manages the Stop button). Discoverability of retry is poor — power users find Ctrl+R, everyone else won't. Dead chrome next to the input.

10. **Send-time toggles are buried in a Settings panel, and their semantics are inconsistent.**
    *Why/impact:* The controls a user touches most (stream/thinking/model/deliberation) require opening the right panel → Settings tab (`index.html:572-621`). Worse, they mix models: Stream/Show-thoughts/Model are per-send; Deliberation and Bypass are *sticky global config* written immediately to `/settings`. Nothing signals "this one is global." Users will expect deliberation to be per-message and be surprised it persists. (This is exactly what the unbuilt "chat-options popover" in `GUI-FEATURE-MAP.md` was meant to fix.)

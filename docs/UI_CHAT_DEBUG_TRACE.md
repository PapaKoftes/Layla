# UI Chat / Enter / Buttons — Debug Trace

This document traces the full path from page load to sending a message and lists **where** each step lives and **what** can break. Updated for the refactored single-entry-point flow (triggerSend, document keydown only for Enter, inline Send).

---

## 1. Page load and script order

**Flow:** Browser requests `/ui` → server returns `agent/ui/index.html` (or fallback `_INLINE_UI` from `main.py` if file read fails). Parser runs; when it hits the single `<script>` block (line ~1271), that script runs **synchronously** to the end (~3940). Only then does the rest of the document parse (e.g. chat-search-overlay, setup-overlay).

**Relevant code:**
- `agent/main.py`: `ui_rich()` / `ui_root()` — serve HTML with `Cache-Control: no-store`.
- `agent/ui/index.html`: one `<script>` block; no `defer`/`async`.

**Can break here:**
- **Wrong UI:** If `agent/ui/index.html` is missing or unreadable, `main.py` serves `_INLINE_UI`, which has different markup. Then the rest of this trace does not apply.
- **Cached HTML:** Old cached page can run old JS. Mitigation: `Cache-Control: no-store` on `/ui` and `/`.

---

## 2. Bootstrap: single send entry point and Enter (top of script)

**Location:** `index.html` — right after `LAYLA_DEBUG` / `_dbg`.

**What it does:**
- **`window.triggerSend`** — Single entry point for “user requested send”. If `window.send` is a function, calls it (full behavior + file-context wrapper). Else runs the **only** minimal path: read `#msg-input`, POST `/agent`, append user + assistant bubbles to `#chat`. No other code duplicates this minimal path.
- **Document keydown (capture)** — The **only** place that turns “Enter in input” into send. Condition: Enter (no Shift), `document.activeElement.id === 'msg-input'`, mention dropdown not active. Action: `preventDefault()`, `stopPropagation()`, then `window.triggerSend()`.

**Can break here:**
- **Script throw before this block:** Then `triggerSend` is never defined and the document keydown listener is never registered. Enter and the Send button (which calls `triggerSend` inline) would no-op.
- This block is **self-contained**: it does not reference `send`, `onInputKeydown`, `toggleSendButton`, or `showPanelTab`. A throw later in the script cannot prevent Enter or the minimal send from working.

---

## 3. Send button: inline only

**Location:** `index.html` — `#send-btn` has `onclick="typeof window.triggerSend==='function'&&window.triggerSend();"`.

**What it does:** Single binding for Send. No `addEventListener('click')` for the Send button; it relies only on this inline handler. So Send always uses the same path as Enter (triggerSend), and works even if the rest of the script never runs or throws.

---

## 4. Panel tabs: inline only

**Location:** `index.html` — each `.panel-tab` has inline `onclick` (e.g. `showPanelTab('health'); refreshPlatformHealth()`).

**What it does:** No delegated click on `.panels` in `bindChatInputNow`. Panel tabs work via inline handlers only, so they work even if `bindChatInputNow` never runs or throws.

---

## 5. Input keydown: non-Enter only (`onInputKeydown`)

**Location:** `index.html` — `onInputKeydown` and textarea `onkeydown="onInputKeydown(event)"`.

**What it does:** Handles **only** non-Enter: Ctrl+K (clear), Ctrl+R (retry), Ctrl+/ (help), Ctrl+F (search), mention dropdown (ArrowUp/Down, Tab/Enter to pick, Escape to close). Enter-to-send is **not** handled here; it is handled solely by the document keydown listener (bootstrap). This avoids duplicate Enter paths.

**Binding:** `bindChatInputNow` attaches `input.addEventListener('keydown', onInputKeydown)` so that when the input is focused, Ctrl+K and mention navigation work. If `bindChatInputNow` throws or never runs, Enter and Send still work (bootstrap + inline); only these shortcuts would be missing.

---

## 6. bindChatInputNow (finally block)

**Location:** `index.html` — inside `} finally { ... }` at end of main script.

**What it does:**
- Gets `#msg-input` and `#send-btn`; no longer attaches any Enter or Send click listener (those use bootstrap + inline).
- If input exists: attaches `keydown` → `onInputKeydown`, `input` → `onInputChange`, `focus` → `toggleSendButton`; calls `toggleSendButton()` once.
- If btn exists: removes `disabled`, sets `disabled = false`, calls `toggleSendButton()` once.
- All optional functions are guarded with `typeof fn === 'function'` so a missing dependency does not throw.

**Can break here:**
- If this block throws, Enter and Send still work (bootstrap + inline). Only input shortcuts (Ctrl+K, mentions) and Send button enabled state might be affected until next reload.

---

## 7. send() and the file-context wrapper

**Real `send()`:** Later in the script. Reads `#msg-input`, returns if missing or empty; builds payload, then `fetch('/agent', ...)` (stream or non-stream).

**Wrapper:** IIFE that replaces `window.send` with a function that prepends file context when `_attachedFiles.length > 0`, then calls the original `send`. When the user presses Enter or clicks Send, they call `window.triggerSend()` → `triggerSend` calls `window.send()` → wrapper runs → original `send()` runs.

**Can break here:**
- If the wrapper IIFE never runs (script threw before it), `window.send` is never set; `triggerSend` then uses the minimal path (POST + append) so the user can still send and see a reply.
- Payload build in full `send()`: null checks and optional chaining avoid throws.

---

## 8. Overlays blocking interaction

**Setup overlay** (`#setup-overlay`): Visible when `checkSetupStatus()` resolves with `ready === false`. When visible, it covers the viewport; focus and clicks go to the overlay, not the chat input or Send button.

**Onboarding overlay** (`#onboarding-overlay`): Shown when onboarding not done and setup not visible. Same effect: Enter and Send appear broken until the user dismisses.

If either overlay is visible, that alone can explain “Enter and buttons broken”. Check in DevTools: overlay visibility and `document.activeElement`.

---

## 9. Summary: refactored flow

| User action        | Handler / path                                                                 |
|-------------------|---------------------------------------------------------------------------------|
| Enter in input    | Document keydown (capture) → `window.triggerSend()`                             |
| Send button click | Inline `onclick` → `window.triggerSend()`                                       |
| Panel tab click   | Inline `onclick` on each `.panel-tab`                                           |
| Ctrl+K, mentions  | `onInputKeydown` (bound in `bindChatInputNow` when input exists)               |

**Single entry point:** `window.triggerSend` — either calls `window.send()` (full + wrapper) or runs the only minimal send path. No duplicate minimal-POST logic elsewhere.

**Enable debug:**  
`localStorage.setItem('layla_debug','1'); location.reload();`  
or open `/ui?layla_debug=1`, or in console `window.LAYLA_DEBUG = true`. All `[Layla]` logs show the exact step that ran or failed.

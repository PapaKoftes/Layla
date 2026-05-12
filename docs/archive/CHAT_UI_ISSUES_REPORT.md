# Chat & Chat UI — Issues Report

**Date:** 2026-03-17  
**Scope:** `agent/ui/index.html` — chat flow, send, display, TTS, history, layout.

**Status:** All reported issues have been fixed (2026-03-17).

---

## 1. TTS / Speech

### 1.1 Double speech (bug) — FIXED

**Location:** `addMsg()` (line ~1437) and `send()` (lines ~2157, ~2191)

**Issue:** Two separate TTS paths can both run for the same Layla response:

- **addMsg** always calls `speakText(text.slice(0, 500))` for Layla messages when `_ttsEnabled` is true (default: `localStorage.getItem('layla_tts') !== 'false'`).
- **send()** calls `speakReply()` when the "Speak replies" checkbox (`tts-toggle`) is checked.

When both are enabled, the response can be spoken twice (server TTS + browser fallback, or browser twice).

**Recommendation:** Use a single source of truth. Either:
- Remove the `speakText` call from `addMsg` and let `send()` (and other entry points) handle TTS via `tts-toggle`, or
- Make `addMsg` respect `tts-toggle` instead of `_ttsEnabled` and remove the duplicate `speakReply` call in `send()`.

---

### 1.2 TTS toggle mismatch — FIXED

**Issue:** Two different settings control speech:

- `_ttsEnabled` — `localStorage.getItem('layla_tts') !== 'false'` (default true)
- `tts-toggle` — "Speak replies" checkbox

Unchecking "Speak replies" does not stop `addMsg` from calling `speakText` because it uses `_ttsEnabled`, not the checkbox.

---

## 2. Stream mode

### 2.1 Research stream missing scroll (fixed in main chat)

**Location:** `sendResearch()` stream loop (~line 1944)

**Issue:** The research stream path does not call `chatEl.scrollTop = chatEl.scrollHeight` on each token update. Long research responses can grow below the fold while streaming.

**Status:** Main chat stream has scroll-on-token; research stream does not.

---

### 2.2 Stream mode: typing + empty bubble overlap

**Location:** `send()` stream path (~lines 2085–2097)

**Issue:** On first token, both the typing indicator and an empty Layla bubble are visible briefly. Minor visual glitch.

---

## 3. Input & keyboard

### 3.1 Enter key without preventDefault

**Location:** `onInputKeydown()` line ~1651

**Issue:** `if (e.key === 'Enter') send()` does not call `e.preventDefault()`. For a single-line `<input>`, Enter usually has no default, but `preventDefault` would avoid unexpected behavior in some browsers or if the input is ever wrapped in a form.

---

### 3.2 No Shift+Enter for newline

**Issue:** Input is `<input type="text">`, so multiline input is not supported. Enter always sends. Users cannot insert newlines in a message. Common pattern is Shift+Enter for newline, Enter to send (requires `<textarea>`).

---

## 4. Attached images

### 4.1 No visual indicator for attached images

**Location:** `send()` (~lines 2056–2064)

**Issue:** When an image is attached via `_attachedImages`, it is sent in the payload but the user bubble does not show that an image was attached. The message looks like plain text only. Attached files (non-image) are prepended to the message text, so they appear in the bubble.

**Recommendation:** Add a small indicator (e.g. `[📎 image attached]`) to the user message when an image was sent.

---

## 5. Markdown & rendering

### 5.1 marked.parse can throw

**Location:** `addMsg()`, stream token handler, etc.

**Issue:** `marked.parse()` can throw on malformed or unusual input. There is no try/catch, so a bad response could break rendering.

**Recommendation:** Wrap in try/catch and fall back to plain text on error.

---

### 5.2 Tool trace JSON.stringify can throw

**Location:** `addMsg()` line ~1483

**Issue:** `steps.map(s => s.action + ': ' + JSON.stringify(s.result).slice(0, 200))` — `JSON.stringify` can throw on circular references or non-serializable values.

**Recommendation:** Wrap in try/catch or use a safe stringifier.

---

## 6. History & persistence

### 6.1 MutationObserver saves on every change

**Location:** `saveChatHistory()` + MutationObserver (~line 2591)

**Issue:** Every DOM change to `#chat` triggers a full save. With many messages, this can cause frequent localStorage writes.

**Recommendation:** Debounce saves (e.g. 300–500 ms) to reduce write frequency.

---

### 6.2 Loaded history order

**Location:** `loadChatHistory()` (~line 2584)

**Issue:** Uses `chat.insertBefore(frag, chat.firstChild)`, so loaded messages are prepended. If `chat-empty` is the first child, loaded history appears above it. After `hideEmpty()`, order is correct. No bug found, but the flow is subtle.

---

## 7. UX / display

### 7.1 showTyping uxLabel ignored

**Location:** `showTyping(uxLabel)` (~line 2067)

**Issue:** When the typing indicator already exists, `showTyping` returns early and never updates the label. UX states like "Searching the web…" or "Verifying…" are not shown in the typing indicator.

---

### 7.2 Refusal appended to last child

**Location:** `send()` non-stream path (~line 2188)

**Issue:** `document.getElementById('chat').lastElementChild?.appendChild(refDiv)` appends the refusal to the last chat child. If the last child is not the Layla message (e.g. separator or another element), the refusal can be attached to the wrong node. In normal flow the last child is the Layla message, so this is an edge case.

---

### 7.3 Copy-on-click vs copy button

**Location:** Chat click handler (~line 2674)

**Issue:** Clicking anywhere on a message bubble copies its text. This can conflict with other interactions (e.g. selecting text, clicking links). No visual cue that a click will copy.

---

## 8. Layout (previously addressed)

- Input area visibility: fixed with `flex-shrink: 0` and `min-height: 0`.
- Mobile layout: fixed with `min-height: 0` in the 768px media query.

---

## 9. Summary table

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1.1 | TTS double speech | Medium | Bug |
| 1.2 | TTS toggle mismatch | Medium | Bug |
| 2.1 | Research stream no scroll | Low | Bug |
| 2.2 | Typing + empty bubble overlap | Low | UX |
| 3.1 | Enter without preventDefault | Low | Robustness |
| 3.2 | No multiline input | Low | Feature |
| 4.1 | No image-attached indicator | Low | UX |
| 5.1 | marked.parse can throw | Low | Robustness |
| 5.2 | JSON.stringify in tool trace can throw | Low | Robustness |
| 6.1 | Save on every mutation | Low | Performance |
| 7.1 | UX state label not shown in typing | Low | UX |
| 7.2 | Refusal append target | Low | Edge case |
| 7.3 | Copy-on-click affordance | Low | UX |

---

## 10. Recommended fixes (priority)

1. **TTS:** Remove `speakText` from `addMsg` and rely on `send()` (and other entry points) using `tts-toggle` for `speakReply`.
2. **Research stream:** Add `chatEl.scrollTop = chatEl.scrollHeight` in the research stream token loop.
3. **marked.parse:** Wrap in try/catch with plain-text fallback.
4. **Image indicator:** Add `[📎 image attached]` to the user message when `_attachedImages.length > 0` before clearing.

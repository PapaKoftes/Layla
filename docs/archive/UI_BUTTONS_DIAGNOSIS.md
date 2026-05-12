# UI Buttons Diagnosis — Personality & Right-Side Panels Not Working

## What works vs what doesn’t

- **Works:** Typing in chat, Send/Enter (bootstrap), header buttons (Export, theme, etc.).
- **Doesn’t work:** Sidebar personality buttons (Morrigan, Nyx, Echo, …), right-side panel tabs (Approvals, Health, Models, …).

## Cause

1. **Personality buttons** use inline `onclick="setAspect('morrigan')"` etc.  
   **Panel tabs** use inline `onclick="showPanelTab('approvals')"` etc.

2. **`setAspect`** and **`showPanelTab`** (and the refresh helpers) are defined only in the **main script** (around lines 1360 and 1563). They are **not** in the bootstrap script.

3. Inline handlers run in the global scope and expect `setAspect` / `showPanelTab` to be on `window`. In this file they are never assigned to `window`; they exist only as top-level function declarations in the main script.

4. If the **main script fails** (parse error or throw before those lines), those functions are never defined and clicking the buttons does nothing or throws `ReferenceError` (often silent in inline handlers).

5. Even when the main script runs, some environments can make inline handlers resolve names in a way that doesn’t see script-level declarations. Explicitly assigning `window.setAspect` and `window.showPanelTab` guarantees the buttons can call them.

6. **No overlay is blocking:** Setup and onboarding are disabled; `#chat-empty` has `pointer-events: none` and only covers the chat area; `body::after` has `pointer-events: none`. So the problem is **handler availability**, not click blocking.

## Conclusion

- Personality and panel buttons depend on **main-script-only** functions that are **not** exposed on `window`.
- Any main-script failure before those definitions leaves the buttons with no working handler.
- **The same issue applies to all other UI elements** that use inline `onclick` / `onchange` / `oninput`: exportChat, toggleTheme, clearChat, openSettings, fillPrompt, toggleMic, attachFile, saveSettings, closeDiffViewer, etc. If the handler is only defined in the main script and not on `window`, inline handlers can fail to resolve it in some environments or when the script throws early.

## Fix applied

1. **setAspect** and **showPanelTab** are assigned to `window` right after their definitions.
2. **Bootstrap delegated click** for `.aspect-btn` and `.panel-tab` so they work even if the main script never runs.
3. **Single “expose UI handlers” block** at the end of the main script’s `try` block: every other handler used by inline `onclick` / `onchange` / `oninput` is attached to `window` there (exportChat, toggleTheme, openSettings, clearChat, fillPrompt, toggleMic, attachFile, saveSettings, closeDiffViewer, refreshPlatform*, etc.). That way all buttons and inputs use the same pattern and are resilient to scope/order issues.

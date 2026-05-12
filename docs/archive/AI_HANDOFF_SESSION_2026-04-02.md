# AI session handoff — 2026-04-02  
**Web UI hardening, `/health` race fix, chat reactivity, integrations drop-ins, workflow rules**

**Use this in a fresh chat:** paste a short instruction such as:  
*“Read `docs/AI_HANDOFF_SESSION_2026-04-02.md` first, then `AGENTS.md` and `ARCHITECTURE.md` for the area you touch.”*

**Canonical repo rules (unchanged):** `.cursor/rules/north-star.mdc`, `.cursor/rules/layla-assistant.mdc`, **`AGENTS.md`**, **`LAYLA_NORTH_STAR.md`** (do not edit unless operator asks), **`docs/IMPLEMENTATION_STATUS.md`**, **`ARCHITECTURE.md`**, **`CHANGELOG.md`** for user-visible changes.

---

## 1. Conversation summary (what happened)

### 1.1 Web UI: “unclickable” / tabs vs inner panel dead

**Symptoms:** Right-panel **tabs** could work while **buttons and content inside** did nothing; duplicate DOM confused `getElementById`; initial panel hook used wrong global.

**Fixes (in `agent/ui/index.html` and docs):**

| Issue | Fix |
|--------|-----|
| **Duplicate overlay/modal blocks** after `</script>` (same `id`s twice) | Removed the second copy; **single** set of overlays **before** the main script (see `ARCHITECTURE.md`). |
| **`showMainPanel('status')` on load** used `typeof showMainPanel` | Bootstrap only defines **`window.showMainPanel`** → switched to **`window.showMainPanel`**. |
| **Inline `onclick` / `oninput` handlers** | Main script is wrapped in **`try { … } finally { … }`**. In modern engines, **`function foo()` inside `try` is block-scoped**, not a true `window` global. Inline handlers resolve names on **`window`** → **explicit exports** added at end of try (before `finally`), e.g. `checkForUpdates`, `runKnowledgeIngest`, `refreshMissionStatus`, `applySettingsPreset`, `retryModelDownload`, `cancelActiveSend`, `onInputKeydown`, `onInputChange`, `refreshStudyPlans`, `loadStudyPresetsAndSuggestions`, `_pickMention`, etc. |
| **Workspace “Models” stuck on “Loading…”** | **`__laylaRefreshAfterShowMainPanel`** had no branch for **`main === 'workspace'`**; only subtabs refreshed. Added: on Workspace open, refresh **active** subtab via **`__laylaRefreshAfterWorkspaceSubtab`**. |
| **`.rcp-tabs` HTML** | Ensure **`</div>` closes `.rcp-tabs`** before **`.rcp-body`** (sibling structure). *If mis-nested, flex lays out tabs and body in one row — layout breaks.* (Verified correct in tree at handoff time.) |

**Docs touched:** `CHANGELOG.md` (Unreleased), `ARCHITECTURE.md` (Web UI paragraph).

### 1.2 “Always loading” / Status & platform panels

**Symptoms:** Skeletons / “Loading…” never replaced.

**Root cause:** **`fetchHealthPayloadOnce()`** did `if (h.inFlight) return h.payload` — concurrent callers got **`null`** while the first fetch was in flight, so **`refreshPlatformHealth`** / **`refreshRuntimeOptions`** failed or never painted.

**Fixes:**

- **`fetchHealthPayloadOnce`:** **Single in-flight promise** (`_inFlightPromise`); all callers **await the same** request. On **`!r.ok`**, prefer returning last good **`h.payload`** when present; apply header from cache when possible. Successful fetch updates payload + **`laylaApplyHeaderStatusFromHealth`**. Removed redundant header call from **`pollWarmup`** where duplicate.
- **`fetchWithTimeout`:** If caller passes **`options.signal`**, the **timeout must still abort** the `fetch` — **linked `AbortController`** pattern (timeout + user abort both abort a shared linked controller).

**Chat UX deduplication (same file):**

- **Shared helpers** after **`formatLaylaLabelHtml`**: **`laylaShowTypingIndicator`**, **`laylaUpdateTypingUx`**, **`laylaRemoveTypingIndicator`**, **`laylaStartNonStreamTypingPhases`**, **`laylaClearTypingPhases`**.
- **Non-stream** waits: phased labels (**connecting → thinking @ 1.2s → still_working @ 8s → preparing_reply @ 25s**) + elapsed ticker.
- **`send()`:** removed inner duplicate `showTyping`/`removeTyping`; uses shared helpers; stream meta line uses **`UX_STATE_LABELS[liveStatus]`** for readable status.
- **`sendResearch`:** stream path aligned with main chat (meta, first-token + stalled hints, **`fetchWithTimeout`**, error event cleanup); non-stream uses shared typing + phases; **`studyNow`** same pattern + **`fetchWithTimeout`** + **`!res.ok`** handling.

**New `UX_STATE_LABELS` keys:** `preparing_reply`, `still_working`.

**Docs:** `CHANGELOG.md`, `ARCHITECTURE.md` bullets on health coalescing and chat UX.

### 1.3 Integrations: Claude ecosystem zips

**Operator added at repo root:**

- `claude-code-sourcemap-main.zip` (~16 MB)  
- `claw-code-main.zip` (~5 MB)  
- `openclaude-main.zip` (~10 MB)  

**Extracted to** (GitHub zip = nested folder name):

- `integrations/claude-code-sourcemap-main/claude-code-sourcemap-main/`  
- `integrations/claw-code-main/claw-code-main/`  
- `integrations/openclaude-main/openclaude-main/`  

**Map + rules:** **`integrations/README.md`** — do **not** blindly merge into `agent/`; need facade, config, tests; respect Layla approval + local GGUF defaults.

### 1.4 Meta: managing huge merges + AI cost (agreed practice)

- **Scope per session:** one surface area + `@` files; use **`PROJECT_BRAIN.md`**, **`AGENTS.md`**, **`docs/MODULE_SWEEP_STATUS.md`** / linked sweeps to avoid full-tree rescans.  
- **Zip workflow:** code must live **in workspace** (extracted paths); don’t rely on pasting huge zips into chat.  
- **Handoff doc** (this file) + **smoke tests** between sessions reduces token burn.  
- **Phased integration** cheaper/safer than “merge everything in one chat.”

---

## 2. Ruleset / invariants established this session

### 2.1 Web UI (`agent/ui/index.html`)

1. **Overlays/modals:** **One** DOM instance each; **before** bootstrap/main scripts; **no duplicate `id`s** after `</script>`.  
2. **Bootstrap** owns **`window.showMainPanel`**, **`window.showWorkspaceSubtab`**, **`triggerSend`** (tabs/send survive main script errors).  
3. **Any name used from HTML** `onclick` / `oninput` / `onmousedown` **must exist on `window`** if defined only inside the big `try` — assign in the **export block** (pattern: `if (typeof fn === 'function') window.fn = fn`).  
4. **Opening Workspace** must refresh the **currently active** subtab, not only on subtab click.  
5. **`fetchHealthPayloadOnce`:** concurrent calls share **one** promise; never return stale **`null`** while a fetch is in flight.  
6. **`fetchWithTimeout`:** timeout + optional user **`signal`** both abort the same logical request.  
7. **Typing / “working” UI:** prefer **shared** `layla*` helpers; non-stream uses **phased** client labels until JSON returns; stream uses SSE **`ux_state`** / **`tool_start`** where the backend sends them.

### 2.2 Integrations

1. **`integrations/README.md`** is the index for dropped zips and inner paths.  
2. No automatic wiring into Layla core until **explicit design** (facade, config, tests, operator choice).

### 2.3 Repo hygiene (from `AGENTS.md` / rules — still mandatory)

- Never commit **`agent/runtime_config.json`**, **`layla.db`**, personal **`knowledge/`** (unless `!` exception).  
- Approval gate for writes/runs; config via **`runtime_safety.load_config()`**.  
- Update **`ARCHITECTURE.md`** / **`docs/IMPLEMENTATION_STATUS.md`** / **`CHANGELOG.md`** when behavior or flow changes (per existing project rules).

---

## 3. Files likely touched this session (verify with `git status`)

| Area | Files |
|------|--------|
| Web UI | `agent/ui/index.html` |
| Docs | `ARCHITECTURE.md`, `CHANGELOG.md`, `integrations/README.md`, **`docs/AI_HANDOFF_SESSION_2026-04-02.md`** (this file) |
| Zips | Repo root `*.zip` (local; may be gitignored or untracked — check `.gitignore`) |
| Extracted trees | `integrations/**` (large — decide commit vs local-only) |

**Older cumulative handoff (may be stale):** `docs/AI_HANDOFF_REPORT.md` (dated 2025-03-14).

---

## 4. Verification checklist (human or AI)

```powershell
cd agent
python -m pytest tests/ -m "not slow and not e2e_ui" -q
```

**Browser (Layla running):**

1. Hard refresh **`/ui`** (`Ctrl+Shift+R`).  
2. **Status:** health + runtime panels fill (not perpetual skeletons).  
3. **Workspace → Models** (and other subtabs): content loads on first open.  
4. **Inline actions:** Check for updates, Ingest, Research refresh, Study buttons, **Stop** while streaming.  
5. **Console:** no first-load **`ReferenceError`** on handler names.  
6. **Network:** `/health` and `/platform/*` return **200** (or consistent error UI, not infinite loading).

---

## 5. Known gaps / follow-ups

- **`updateToolStatus`** in `index.html` appears **uncalled** — dead or future hook; stream path uses SSE **`tool_start`**.  
- **`main.py` embedded `_INLINE_UI`** can diverge from **`agent/ui/index.html`** if file read fails — keep file-based UI as source of truth.  
- **Integration code** under `integrations/` is **reference only** until ported with tests and docs.  
- If UI still misbehaves: confirm **no stale service worker**, correct **origin** (UI talking to same host as API), and **first red error** in console.

---

## 6. Fresh-chat bootstrap (copy-paste)

```
You are working on Layla (local-jinx-agent). Read in order:
1) docs/AI_HANDOFF_SESSION_2026-04-02.md
2) AGENTS.md
3) ARCHITECTURE.md (Web UI + health paragraphs)

Hard rules: .cursor/rules/north-star.mdc + layla-assistant.mdc; never commit runtime_config.json or layla.db.

Current priority: [state yours — e.g. verify UI checklist / integrate OpenClaude behind flag / …]
```

---

*End of session handoff — 2026-04-02.*

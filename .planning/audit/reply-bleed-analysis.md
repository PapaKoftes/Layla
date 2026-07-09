# Reply "Bleeds Over" — Root-Cause Analysis & Ranked Fix List

**Status:** All 12 verified findings re-checked against live code (`ui/`, `routers/agent.py`, `services/agent/response_builder.py`). Every load-bearing citation confirmed. Line numbers drift by a few lines in one CSS spot (`.msg-bubble .md-content pre` is at `layla.css:2103`, audit said ~2086) but the rule is present and correct as described.

---

## 1. What "bleeds over" actually means — two distinct failure modes

The single reported symptom ("reply bleeds over") is really **two unrelated defects** wearing the same complaint. Separating them is the whole point of this analysis, because they have different fixes in different files.

### Mode A — Horizontal layout bleed (the reply escapes its bubble and scrolls the page sideways)
The message content is wider than the chat column, so the bubble/box is breached and the **page** gains a horizontal scrollbar. This is a CSS containment failure. There is exactly **one live trigger** today:

- **A markdown table.** There is no `.md-content table` rule anywhere in either stylesheet. `marked.parse()` runs with GFM tables on, `sanitizeHtml` explicitly allowlists `table/thead/tbody/tr/th/td`, and `enhanceCodeBlocks` only ever wraps `<pre>` — never `<table>`. So a real `<table>` (display:table, sizes to content, `max-width:none`) reaches the DOM with zero width constraint. Several columns or one long unbreakable cell token and it blows past the bubble and scrolls the page. **This is the only currently-reachable cause of horizontal bleed.**

Code blocks do **not** bleed today: `.msg-bubble .md-content pre { overflow-x:auto }` (specificity 0,3,0) wins over the incomplete `.md-content pre` in the last-loaded rebuild sheet (0,2,0), and every render site is inside a `.msg-bubble`. That containment is real but **cross-sheet-specificity-dependent and brittle** (Findings #2, #3, #4) — it is not a live bug, only a latent one.

### Mode B — Formatting/content bleed (styling or scaffolding spills *within* the reply, mid-stream)
The reply stays in its box, but its **content or formatting spills across regions of the reply** during streaming, or the finished reply visibly swaps to different text. All of these are streaming-path defects:

- **B1 — Unclosed ```` ``` ```` fence (Finding #9):** while a code block is mid-generation, the opening fence has streamed but the closing one hasn't. `marked` treats a lone opening fence as "code to end of input," so **every subsequent token — prose, headers, everything — renders as monospace code** until the closing fence lands. On a slow local model emitting a long block this is a multi-second window where the entire reply looks like code. This is the most literal "formatting bleeds across the reply."
- **B2 — Done-frame swap/flicker (Finding #10):** the live token stream is filtered only by `stream_safe_prefix` (holds an unclosed `[`, strips complete `[MARKER]`). The done frame is computed by a far heavier pipeline (`strip_junk_from_reply` → collapse-repetition/duplicate-blocks → `truncate_at_next_user_turn` → `polish_output`). The UI **unconditionally overwrites** the streamed `full` with `obj.content` at `app.js:594` and re-renders — so any divergence is a hard, visible snap to different (usually shorter) text after the reply "finished."
- **B3 — SSE line-split truncation/duplication (Finding #5):** `app.js` does `dec.decode(...)` then `chunk.split('\n')` per read with **no carry-over buffer**. A `data:` line split across two network reads gets `JSON.parse`d as a half-line (throws, discarded); the continuation arrives headless and is skipped. Losing a **token** frame truncates the bubble; losing the **done** frame means the cleaned `content` never replaces the raw stream and leaked scaffolding (`[TOOL:…]`, repeated text) stays visible. This both truncates and *causes the raw-scaffolding-visible* symptom people describe as bleed.
- **B4 — Multi-agent `User:` tail (Finding #11):** `agen_ma` runs `strip_junk_from_reply` + `polish_output` but omits `truncate_at_next_user_turn`, so a role-played `User:`/`You:` next-turn tail in a compound reply can reach the bubble. Low-probability, strictly-weaker-than-the-other-two-paths parity gap.

---

## 2. Ranked, deduplicated fix list

Ranking key: **(a) does it stop a visible bleed the user can hit today, then (b) severity.** Findings the audit marked `causes_bleed:true` that are transient-only or low-probability are ranked below the ones that produce a persistent, easily-reproduced visible break.

### TIER 1 — These actually stop the bleed (do these first)

| # | Fix | File + change | Mode | Why it's top |
|---|-----|---------------|------|--------------|
| **1** | **Constrain markdown tables** | `ui/css/layla-rebuild.css` (add, near the `.md-content` block ~line 589–599):<br>`.md-content table { display: block; max-width: 100%; overflow-x: auto; }`<br>`.md-content th, .md-content td { overflow-wrap: anywhere; }` | A | **The only live cause of horizontal page bleed.** Persistent, trivially reproducible (any multi-column table), high severity. One CSS rule fully resolves it. `display:block` makes the table its own scroll container (standard GitHub approach). |
| **2** | **Balance the streaming ```` ``` ```` fence** | `ui/components/app.js:576` (streaming render **only**, NOT the done render at 597). Before `marked.parse(full)`:<br>`var mdSrc = ((full.match(/```/g)||[]).length % 2) ? full + '\n```' : full;`<br>`bubble.innerHTML = sanitize(marked.parse(mdSrc));` | B1 | Stops the whole-reply-turns-into-a-code-block effect — the most literal "formatting bleeds across the reply." Client-side, self-contained, no server change. **Do NOT** implement the audit's rejected server-side variant (it would suppress all live code streaming). |

Fixes 1 and 2 are **the one-or-two changes that actually stop the bleed.** If only two changes ship, ship these.

### TIER 2 — Fixes real, user-visible content defects (persistent or high-severity, but not the layout bleed)

| # | Fix | File + change | Mode | Notes |
|---|-----|---------------|------|-------|
| **3** | **SSE carry-over buffer** | `ui/components/app.js:494–495`. Hoist `var buf = '';` above the `while(true)` loop, then:<br>`buf += dec.decode(value, {stream:true});`<br>`var lines = buf.split('\n');`<br>`buf = lines.pop();` — parse only the complete lines. | B3 | High severity, real on slow/chunked connections. Fixes silent truncation *and* the "leaked scaffolding stays visible" symptom (lost done frame). No end-of-stream flush needed (frames are newline-terminated), but flushing residual `buf` after the loop is harmless belt-and-suspenders. |
| **4** | **Reduce done-frame swap divergence** | Two-part. (a) `services/agent/response_builder.py`: move the *idempotent, position-stable* cleaners into `stream_safe_prefix` — invented `[ALLCAPS:…]` strip (`:390`), `## SYSTEM`/`## TASK` mid-line strip (`:457`), bracket-marker catch-alls. (b) `ui/components/app.js:594`: only hard-replace when `obj.content` is **not** a prefix of `full` (on the common clean turn it *is* a prefix, so skip the reflow). | B2 | High severity but **cannot be fully eliminated** — `_collapse_repetition`/`_collapse_duplicate_blocks`/`truncate_at_next_user_turn` need the whole text and can only shorten, which an append-only client can't unwind. (a)+(b) remove the *bulk* of the visible swap and the common-case reflow. Residual divergence remains only on looping outputs. |
| **5** | **Multi-agent `User:` tail parity** | `routers/agent.py:854`:<br>`text = polish_output(truncate_at_next_user_turn(strip_junk_from_reply(agg.get("summary") or "")), cfg) or "…"` | B4 | Low probability, but a one-line, idempotent, null-safe change that restores parity with `agen_fast` (`:787`) and the `agen` stream path (`:1061–1064`). Cheap; ship it. |

### TIER 3 — Hardening / general correctness (no live bleed; do after Tier 1–2)

| # | Fix | File + change | Notes |
|---|-----|---------------|-------|
| **6** | Make the canonical `pre` rule self-sufficient | `ui/css/layla-rebuild.css:593`: `.md-content pre { overflow-x:auto; max-width:100%; min-width:0; border-radius:var(--radius); border:1px solid var(--border); }` | Purely defensive — removes the cross-sheet specificity dependency so any future `.md-content` outside a `.msg-bubble` (artifacts/research preview) stays contained. **Zero change to current rendered behavior.** |
| **7** | Give `.code-wrap` its own scroll container | `ui/css/layla.css:2093` (or rebuild): `.code-wrap { position: relative; overflow-x: auto; }` | Decouples code containment from the `pre` rule. The audit-suggested `min-width:0`/`max-width:100%` are no-ops in the current block-flow layout — `overflow-x:auto` is the correct hardening token. Defense-in-depth only. |
| **8** | Retry banner via DOM, not markdown | `ui/components/app.js:684–688`: build the banner with `createElement` + `textContent` + `addEventListener`; target `msg-input` (not the nonexistent `chat-input`); append directly to the bubble, bypassing `marked`+DOMPurify. | Medium correctness bug (Retry button stripped by DOMPurify allowlist *and* wrong element id). Not bleed. |
| **9** | Health-banner wrong container id | `ui/components/app.js:716`: `document.getElementById('chat-messages')` → `'chat'` (the real id, per `index.html:379`). | Low; recovery banner currently no-ops silently. Confirm `layla-model-loading` renders as a block child of the chat log. |
| **10** | Per-conversation reasoning-mode state | `services/agent/stream_handler.py` + `reasoning_state.py`: key `_rstate_get/_set` by `conversation_id` (requires threading `conversation_id` into `_stream_reason_body` and the parallel non-streaming path). | Low; mode/label/budget bleed under concurrency, **no content bleed**. Not a local edit. Acceptable to document as intentionally process-global instead. |

### No action

- **Finding #12** (live-stream re-render scoping / copy buttons bind on done): **confirmed correct, no bug.** `full`/`div`/`bubble` are per-`send()` closure locals, the busy gate + `AbortController` serialize turns, so no cross-turn write is possible. No fix required.

---

## 3. Bottom line

- **The visible horizontal "bleed past the message box + page scrolls sideways" has exactly one live cause: unconstrained markdown tables → Fix #1.**
- **The "formatting bleeds across the whole reply while streaming" has one live cause: the unclosed code fence → Fix #2.**
- Everything else is either (i) real content/truncation defects worth fixing but not the layout bleed (Fixes #3–#5), or (ii) latent/hardening/correctness items with no reproducible bleed today (Fixes #6–#10).

Ship Fix #1 and Fix #2 to stop the bleed. Ship #3–#5 in the same pass — they're cheap and fix real user-visible content defects. Treat #6–#10 as follow-up hardening.

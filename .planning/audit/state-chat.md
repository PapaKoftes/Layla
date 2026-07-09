# State Audit — Conversation / Chat System

Scope: how a conversation is created, persisted, listed, titled; whether title
generation is real and wired; the "forever loading / never titled" report; and the
sidebar feature set vs Claude/ChatGPT (rename/delete/search/pin/grouping/history reload).

Files traced:
- `agent/routers/conversations.py` — CRUD + search + tags + fork/branch HTTP API
- `agent/layla/memory/conversations.py` — SQLite CRUD, `_auto_name_conversation`, fork/compare
- `agent/routers/agent.py` — streaming/non-streaming turn, persistence, done-frame
- `agent/ui/components/conversations.js` — rail, load/new/render/delete/rename/pin/tags/export
- `agent/ui/components/app.js` — send payload, `conversation_id` lifecycle, done-frame handler (`refreshConversationList`)
- `agent/ui/components/sidebar.js` — `scrollActiveConversationIntoView` only
- `agent/layla/memory/migrations.py` — `conversations` / `conversation_messages` schema

---

## 1. How a conversation is created, persisted, listed

### Created (two independent paths)
1. **Explicit "New chat"** — `startNewConversation()` (`conversations.js:120`) POSTs `/conversations`
   with `{aspect_id}` → `create_conversation_api` (`routers/conversations.py:14`) → `create_conversation`
   (`memory/conversations.py:55`) inserts a row with `INSERT OR IGNORE`, **empty title**,
   `message_count=0`. The client adopts the returned id into `window.currentConversationId` and
   `localStorage['layla_current_conversation_id']`.
2. **Implicit on first turn** — the client generates its own id in `ensureLaylaConversationId()`
   (`app.js:103`, via `crypto.randomUUID()`), stores it in `localStorage`, and sends it as
   `payload.conversation_id` (`app.js:345`). The server, in every `/agent` branch, calls
   `create_conversation(conversation_id, …)` **then** `append_conversation_message(...)` for the
   user turn and the assistant turn (fast-path `agent.py:565-569`; fast-reason `742-745`;
   stream_pending `1015-1019`; non-stream `1070-1074`; sync `1220-1224`).

   Because the client mints the id and reuses it, the server's `INSERT OR IGNORE` is idempotent and
   the same conversation accretes messages across turns. **The client conversation_id is stable**,
   so the "new UUID every turn" failure mode does NOT occur here.

### Persisted
- Two tables (`migrations.py:492`): `conversations(id, title, aspect_id, dominant_aspect,
  created_at, updated_at, message_count, parent_id, forked_at_message_id, tags)` and
  `conversation_messages(id, conversation_id, role, content, aspect_id, created_at, token_count)`.
  FTS5 mirror `conversation_messages_fts` exists with insert/delete/update triggers.
- `append_conversation_message` (`conversations.py:115`) inserts the message, bumps
  `message_count`, sets `updated_at=now`, and (see §2) sets the title on the *first user message
  only*.

### Listed
- `GET /conversations?limit=&tag=` → `list_conversations_filtered` → `list_conversations`
  (`conversations.py:82`): `SELECT * … ORDER BY updated_at DESC LIMIT ?`. Newest-updated first.
- Rail render: `_renderSessionList` (`conversations.js:185`) fetches, sorts pinned-first then by
  `updated_at`, and renders each row as `title || 'New chat'` + a raw `updated_at` date string.

---

## 2. How the TITLE is determined today — and is generation real + wired?

### Today's title = truncated first user message (NOT timestamp, NOT LLM)
The **only** conversation-title logic is `_auto_name_conversation` (`conversations.py:46`):
```python
def _auto_name_conversation(first_user_message: str) -> str:
    t = (first_user_message or "").strip().replace("\n", " ")
    if not t: return "New chat"
    if len(t) <= 40: return t
    return t[:40].rstrip() + "..."
```
It is invoked exactly once, inside `append_conversation_message` (`conversations.py:154`):
```python
if safe_role == "user" and not title and count == 0:
    title = _auto_name_conversation(safe_content)
```
So the title is the first user utterance, truncated to 40 chars. **There is no LLM-synthesized
title anywhere.** The date the user sees in the rail is a *separate* element (`sess-date`,
`conversations.js:275-277`) rendering raw `updated_at` — it is not the title, but visually the rail
row is "first-message-text + timestamp", which reads as the timestamp-y naming the user dislikes.

### `earned_title` is a RED HERRING — it is about aspects, not conversations
Every `earned_title` / `save_earned_title` / `get_earned_title` hit
(`user_profile.py:410/421`, `routers/aspects.py`, `routers/study.py`, `orchestrator.py:86`,
`reasoning_handler.py:280`, migrations `earned_titles` table `migrations.py:223`) is the
**persona/aspect** honorific (e.g. Morrigan's earned title). It has nothing to do with naming a
chat. `tests/test_earned_title_leak.py` exists only to strip that persona marker out of replies.

### Is any title-generation "wired to run and update the sidebar"?
- **Generation:** the truncated-first-message rule IS wired and runs (inside the message insert).
- **Rename API:** `POST /conversations/{id}/rename` → `rename_conversation` (`conversations.py:92`)
  works and is used by the rail's ✎ button (`conversations.js:283-296`).
- **Sidebar update after a turn:** the done-frame handler calls
  `window.refreshConversationList()` (`app.js:607`), which is bound to `_renderSessionList`
  (`conversations.js:16`). This *does* re-fetch and re-render, so the first-turn title DOES reach
  the rail after the reply completes.

**Verdict:** there is no Claude/ChatGPT-style synthesized title. The wiring to display *a* title
is intact; the title is just a dumb 40-char prefix of message #1. Building the feature the user
wants means adding a real title-generation step (LLM summary of the first exchange) and persisting
it via the already-working `rename_conversation` path + `refreshConversationList` refresh.

---

## 3. "Forever loading, never titled" — does the refresh/title-update reach the UI?

The title-update path itself is sound (§2), but there are concrete ways the UI ends up showing a
never-updating placeholder or a spinner that never resolves:

### BREAK A — title only ever set on message #1, and only if it was empty at insert time
`append_conversation_message` sets the title **only** when `safe_role=='user' and not title and
count==0` (`conversations.py:154`). Consequences:
- If "New chat" created the row first (title empty, count 0) and then the first *user* message is
  appended, the title is set — OK.
- BUT the title is computed from the **first user message**, and if that message is empty/whitespace
  (e.g. image-only turn, or understand-mode), `_auto_name_conversation` returns `"New chat"` and the
  row is stuck at "New chat" forever. It is never revisited on later turns (guard `count==0`).
- There is **no assistant-aware or content-aware retitle** ever. A chat's name is frozen at turn 1.

### BREAK B — fast-path / early-return turns can persist but the "loading" spinner relies on the done-frame
The stream done-frame (`app.js:583-618`) is what clears the typing indicator and calls
`refreshConversationList`. If a stream branch returns **without** a `{done:true}` frame — e.g. the
worker thread throws before emitting done, or the client's stall/hard timers fire — the bubble keeps
its `stream-md-placeholder` / "Still working…" state. The server does guard most paths with a
`finally`/except that emits a done frame, but the **fast-reason path** (`agent.py:664-760`) and
**multi-agent path** (`782-814`) emit done only inside their own try; a raw generator exception
before the first yield would leave the client waiting. This is the most likely mechanism behind a
literal "forever loading" bubble on a slow local model (first token ~14s CPU floor per MEMORY).

### BREAK C — the rail row for a brand-new chat shows "New chat" until the FIRST done-frame
Between `startNewConversation()` (row created, title empty) and the first completed turn, the rail
renders `s.title || 'New chat'` (`conversations.js:274`). That is expected, but combined with BREAK A
(empty first message) and BREAK B (no done-frame) it presents as "a chat that is forever titled
'New chat' / forever loading."

### BREAK D — no live/poll refresh; the rail only updates on discrete events
`_renderSessionList` runs on: boot, new chat, load, delete, rename, pin, tags, search input, and the
done-frame. If the done-frame is missed (BREAK B) there is **no timer/poll** to eventually pick up
the server-side title. The rail is entirely event-driven, so a single missed done-frame = a
permanently stale row until the user manually interacts.

**Net:** the refresh *can* reach the UI and normally does, but the title it reveals is only ever the
truncated first message, and any dropped done-frame strands both the "loading" bubble and the rail
title with no fallback.

---

## 4. Rename / delete / search / pin / grouping — parity with Claude/ChatGPT?

| Feature | Status | Evidence |
|---|---|---|
| **Rename** | ✅ Works | ✎ button + `POST /rename` (`conversations.js:283`, `routers/conversations.py:97`) |
| **Delete** | ✅ Works | ✕ button + `DELETE /conversations/{id}` (`conversations.js:297`, cascades messages `conversations.py:103`) |
| **Search** | ⚠️ Works but shallow | `/conversations/search?q=` LIKE over title+message content (`conversations.py:281`); FTS5 table exists but search uses `LIKE`, not FTS. Supports `tag:`, `after:`, `before:` mini-syntax client-side (`conversations.js:196-214`). |
| **Pin** | ⚠️ Client-only | `_togglePinned` stores ids in `localStorage['layla_pinned_conversations']` (`conversations.js:164-182`); pinned-first sort in rail. **Not persisted server-side**, no `pinned` column — lost on another device / cache clear. |
| **Tags** | ✅ Works | `POST /tags`, `list/search_conversations_filtered`, tag suggest (`conversations.py:224-303`); context-menu "tags" action. |
| **Export** | ✅ Works | context-menu "export" dumps JSON blob (`conversations.js:332-349`). |
| **Fork / branch / compare** | ✅ Backend only | `/fork`, `/branches`, `/compare` (`routers/conversations.py:128-173`); no rail UI surface found. |
| **Grouping (Today / Yesterday / Last 7d)** | ❌ MISSING | Rail is a flat list sorted by `updated_at`; each row shows a raw `updated_at` slice (`conversations.js:275`). No date bucketing like Claude/ChatGPT. |

### BREAK E — "Load more" pagination is broken (sends offset the server ignores)
The rail sends `&offset=` on both `/conversations` and `/conversations/search`
(`conversations.js:220`) and advances `_railOffset` (`:368`). **Neither the router nor the DB layer
accepts `offset`** — `list_conversations_api`/`search_conversations_api` (`routers/conversations.py:30,40`)
have no `offset` param, and `list_conversations`/`search_conversations_filtered` only take
`limit`/`tag`. Every "Load more…" click re-fetches page 1 and **appends duplicate rows**. Effective
history is capped at the first `RAIL_PAGE_SIZE=30` unique conversations.

---

## 5. Does history reload correctly on click?

Mostly yes. Clicking a rail row → `loadConversationIntoChat(id, false)` (`conversations.js:92`):
- confirms if the current chat has content, then `GET /conversations/{id}/messages?limit=500`
  (`routers/conversations.py:87` → `get_conversation_messages`, ordered `created_at ASC`),
- clears `#chat`, re-adds each message via `window.addMsg(role→'you'/'layla', content)`,
- sets `window.currentConversationId`, persists to `localStorage`, updates chip, re-renders rail,
  closes mobile rail.

### Caveats / breaks on reload
- **BREAK F — silent failure:** the whole body is wrapped in `try { … } catch (_) {}`
  (`conversations.js:116`). If the fetch fails or returns `ok:false`, it `return`s with **no toast,
  no error** — the click appears to do nothing. Combined with a slow local server this reads as
  "clicking a chat does nothing."
- **BREAK G — role fidelity loss:** every non-`user` message is rendered as `'layla'`
  (`conversations.js:106`). Deliberation traces, tool steps, thinking, artifacts, aspect header, and
  reasoning-tree that were shown live are **not reconstructed** — reloaded history is plain
  user/assistant bubbles only. Markdown re-renders, but the rich turn UI is gone.
- **BREAK H — no scroll-to-active reliability:** `scrollActiveConversationIntoView` (`sidebar.js:9`)
  reads `appState.get('chat.conversationId')`, but the rest of the app tracks
  `window.currentConversationId`; if those two stores diverge, the active row won't scroll into view.
- **Boot reload** (`tryLoadActiveConversationOnBoot`, `conversations.js:154`) restores the last chat
  from `localStorage` — works, same caveats.

---

## Summary of every break (named)

- **BREAK A** — Title frozen at turn 1; empty first message → permanent "New chat"; no retitle ever.
- **BREAK B** — Fast-reason & multi-agent stream paths can throw before the done-frame → bubble
  stuck "loading" with no client-side recovery.
- **BREAK C** — New chat shows "New chat" until first done-frame (expected, but compounds A+B).
- **BREAK D** — Rail is event-driven only; no poll/timer, so one missed done-frame = permanently
  stale title/order.
- **BREAK E** — "Load more" sends `offset` the server ignores → duplicate rows, history capped at 30.
- **BREAK F** — `loadConversationIntoChat` swallows all errors silently (no toast on failure).
- **BREAK G** — History reload flattens all non-user roles to 'layla'; rich turn UI (thinking,
  tools, deliberation, artifacts) is lost on reload.
- **BREAK H** — Active-row scroll reads `appState` while the app tracks `window.currentConversationId`.
- **Pin is localStorage-only** (not server-persisted; no `pinned` column).
- **No LLM title synthesis** exists — the requested Claude/ChatGPT behavior is unbuilt.
- **No Today/Yesterday grouping** — flat list with raw timestamps.
- **Search uses LIKE, not the existing FTS5** mirror (works, just not using the fast index).

## Where to build the requested feature (synthesized titles)
1. Add a title-synthesis function (LLM summary of first user+assistant exchange, ~4-6 words). Natural
   home: `services/agent/response_builder.py` (already has `synthesize_direct_answer`) or a new
   `services/agent/title_synthesizer.py`.
2. Trigger it server-side right after the first assistant message is persisted in each `/agent`
   done-path (`agent.py` fast-path/stream_pending/non-stream persistence blocks), calling the
   already-working `rename_conversation`. Guard so it runs once per conversation.
3. The client already refreshes the rail on the done-frame (`app.js:607`) — no new UI wiring needed,
   but fix BREAK B/D so the refresh reliably fires, and consider emitting the new title in the
   done-frame (`conversation_id` is already there) so the rail updates without a full re-fetch.

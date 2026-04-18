# Web UI operator rubric (local ChatGPT-style habits)

Use this for **manual** or release QA. It is not a substitute for automated tests.

| # | Check | Pass |
|---|--------|------|
| 1 | Open `/ui` on a running server | Page loads; no blank screen |
| 2 | Header shows **conv** id (or new chat) and **Σ … tok** from `/session/stats` | Values update or show “new chat” / empty stats on first load |
| 3 | **ctx** link opens `/ctx_viz` | New tab or view loads without 500 |
| 4 | **Compact** runs `compactConversation` / `POST /compact` | Toast or feedback; no console throw |
| 5 | **retry** after a failed send | Last user message re-submitted per FSM |
| 6 | **Connection** banner on forced offline or bad health | Banner or header shows degraded when appropriate |
| 7 | **Model override** select (if using remote routing) | No hard error on send |
| 8 | **Settings** → workspace path + allow flags | Reflected in `POST /agent` body (DevTools or network log) |

**Non-goals for this rubric:** mobile app, cloud account sync, third-party plugin store.

See [GOLDEN_FLOW.md](GOLDEN_FLOW.md) for the end-to-end request lifecycle.

# Layla: Model input/output pipeline

This doc describes how we control what goes **into** the model and what comes **out**, so replies stay in-character, fast, streamed, and free of hallucinations (dialogue bleed, instruction echo, junk).

---

## 1. Goals

- **Input control**: One clear prompt format; correct context (identity, knowledge, memories); stop the model from continuing into the next turn.
- **Output control**: No "User: …" or "assistant: I replied." in replies; parse [REFUSED] / [EARNED_TITLE]; single reply only.
- **Fast & responsive**: Run LLM in a thread pool so the API stays reactive; stream tokens to the client as they arrive.
- **Streaming**: Server stops generation at `\nUser:` (or configurable stop sequences); client gets one clean reply.

---

## 2. Pipeline overview

```
[User message] → Input pipeline → [Prompt] → Model (local/remote) → [Raw tokens]
                                                                           ↓
[Display / history] ← Output pipeline ← [Clean reply] ← Post-process ← Stream/complete
```

- **Input pipeline**: Build prompt (head + instruction + optional convo + "User: {msg}\n{Name}:") and pass **stop sequences** so the model does not generate past the first reply.
- **Model**: Single entry point (`_completion`) with `stop`, `max_tokens`, `temperature`; supports stream and non-stream, local Llama and remote OpenAI-compatible API.
- **Output pipeline**: For stream: buffer tokens and stop emitting when a stop sequence is seen; then post-process (strip junk, truncate at next "User:", parse tags). For non-stream: same post-process on the full string.

---

## 3. Input control

### 3.1 Prompt structure (order matters)

1. **Core instruction** (short, first so it’s not pushed out): "You are Layla. Use the identity and rules below."
2. **Identity** (system_identity.txt).
3. **Content policy** (uncensored / refuse-only-for-harm) when enabled.
4. **Personality** (aspect: name, title, role; "Reply as {name} only.").
5. **Aspect memories** (recent observations for this aspect).
6. **Learnings** (recent + semantic recall for this goal).
7. **Knowledge** (semantic chunks when Chroma; else flat knowledge docs).
8. **Turn instruction**: "Reply as {name} only. [REFUSED] / [EARNED_TITLE] rules."
9. **Recent conversation** (optional, when `convo_turns` > 0; sanitized).
10. **Context** (workspace/files) when provided.
11. **Final line**: `User: {message}\n{Name}:` (model completes after the colon).

No "Do not output labels" in the turn instruction to avoid the model echoing it.

### 3.2 Token budget (soft limits)

- Head (identity + personality + memories + learnings + knowledge): keep under ~¾ of `n_ctx` so the reply and convo fit.
- Knowledge: `knowledge_max_bytes`; semantic retrieval returns top-k chunks when Chroma is on.
- Convo: last `convo_turns` turns, each turn truncated (e.g. 300 chars) so history doesn’t dominate.

### 3.3 Stop sequences

Passed to the model so it **stops generating** at the next user turn (no "User: …" in the completion):

- `\nUser:`  — next user line
- ` User:`   — same-line next turn (some models)
- Optional: `\n\n` to avoid long monologues (aggressive; can cut mid-sentence)

Config: `agent/runtime_config.json` can add `"stop_sequences": ["\nUser:", " User:"]` (defaults in code if missing). The completion layer always sends at least these two so the model never continues into dialogue.

---

## 4. Model layer (single entry point)

- **`_completion(prompt, max_tokens, temperature, stream=False, stop=None)`**
  - Local: `llm.create_completion(prompt, ..., stop=stop)` (and `Llama(..., verbose=False)`).
  - Remote: POST to `llama_server_url` with `stop` in the JSON body (OpenAI-style `stop` array).
- **Stop**: Default `["\nUser:", " User:"]` so we get one reply only; config can extend, e.g. `["\nUser:", " User:", "\n\n"]`.
- **Stream**: Same stop list; the backend stops emitting when it hits a stop string. We also run a **stream filter** (see below) so if the backend doesn’t honour stop we still cut on our side.

---

## 5. Output control

### 5.1 Stream path (e.g. /agent with Stream on)

1. **Stream filter** (server): Consume tokens from the model; accumulate into a buffer; when the buffer contains a stop sequence (e.g. `\nUser:`), trim at that point, yield the trimmed text once (or already yielded token-by-token and then send a final `done` event with the cleaned content).
2. **Post-process** (after stream ends): `strip_junk_from_reply` then `truncate_at_next_user_turn` so we never store or send repeated "User: … Eris: …".
3. **Done event**: Send `{ "done": true, "content": "<cleaned reply>" }` so the UI can replace the streamed text with the single reply.
4. **History**: Append only the cleaned reply (one turn).

### 5.2 Non-stream path (e.g. /agent without Stream, or /v1/chat/completions)

1. **Post-process**: Same as above on the full completion string.
2. **Parse**: [REFUSED: reason], [EARNED_TITLE: Title]; strip from display; persist refusal/earned title.
3. **History**: Append only the cleaned reply.

### 5.3 Validation

- If after post-process the reply is empty or junk (`_is_junk_reply`): treat as empty; optionally don’t append to history or append a placeholder ("I couldn’t reply just then." when system was busy).

---

## 6. Async and responsiveness

- **Heavy work** (LLM call, tool runs): FastAPI runs **sync** route handlers (e.g. `/agent`) in a **thread pool**, so the event loop is not blocked; other requests stay responsive.
- **Streaming**: The sync generator yields tokens from the same thread-pool thread; the first token is sent as soon as the model produces it.
- **Optional**: For even lower latency, the non-stream path could be `async def` and use `asyncio.to_thread(autonomous_run, ...)` so the handler awaits instead of blocking its thread.
- **Health**: `/health` can optionally check config loaded, DB reachable, and (if desired) model or remote URL reachable; return 503 when not ready.

---

## 7. Config keys (runtime_config.json)

| Key | Purpose |
|-----|--------|
| `stop_sequences` | Optional list of strings; default in code is `["\nUser:", " User:"]` if missing. |
| `completion_max_tokens` | Hard cap per reply. |
| `temperature` | Sampling; lower = more deterministic. |
| `convo_turns` | 0 = no history in prompt; 6 or 12 = include recent conversation. |
| `use_chroma` | If true, knowledge is semantic (top-k chunks); else flat docs. |
| `knowledge_max_bytes` | Max bytes of knowledge text when not using Chroma chunks. |
| `n_ctx` | Context window size for local model. |

---

## 8. Suggested upgrades (from previous list)

- **Stop sequences**: Implemented in `_completion` and stream filter.
- **Semantic retrieval**: Already used for learnings and (when Chroma) for knowledge; keep as default when `use_chroma` is true.
- **Async**: Run `autonomous_run` and stream generator in `asyncio.to_thread` so the server stays responsive.
- **Health**: Extend with DB/config checks and optional model/URL check.
- **Dependencies**: Pin versions in `requirements.txt`; use a venv in `start-layla.ps1`.
- **UI**: Use `done.content` for stream so the bubble shows one reply; already in place.

---

## 9. File / code map

- **Prompt build**: `agent_loop._build_system_head`, `orchestrator.build_standard_prompt`, `orchestrator.build_deliberation_prompt`.
- **Completion**: `agent_loop._completion` (add `stop`; local + remote).
- **Stream**: `agent_loop.stream_reason` → generator; in `main.py` wrap in thread and add stream filter that stops at `\nUser:`.
- **Post-process**: `agent_loop.strip_junk_from_reply`, `agent_loop.truncate_at_next_user_turn`; used in `main.py` and in agent_loop reason branch.
- **History**: `main._append_history`, `main._load_history` (with poison detection).

---

## 10. Implementation status

| Piece | Status |
|-------|--------|
| Design doc (this file) | Done |
| Stop sequences in config + `_completion` (local + remote) | Done |
| Stream filter (stop yielding when buffer contains stop) | Done |
| Post-process (strip junk, truncate at User:, done event with content) | Done |
| Sync handlers in FastAPI (thread pool) | Built-in |
| Optional async + `asyncio.to_thread` for non-stream | Not done; documented as optional |

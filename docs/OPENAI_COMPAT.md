# OpenAI-compatible `/v1` API — what it does and doesn't support

Layla exposes an OpenAI-shaped surface at `/v1` so coding clients (Cline, Continue, Aider, the
`openai` SDK) can talk to your local model. It is **chat-compatible, not a drop-in for every OpenAI
feature** — this page is the honest contract so nothing is a silent surprise.

Base URL: `http://127.0.0.1:8000/v1` · API key: any non-empty string (local, unauthenticated).

## Supported

| Endpoint / field | Behavior |
|---|---|
| `POST /v1/chat/completions` | Chat completion against the local model. |
| `GET /v1/models` | Lists `layla` and one `layla-<aspect>` per aspect (morrigan, nyx, …). |
| `model` | `"layla"` (default voice) or `"layla-<aspect_id>"` to pin an aspect. |
| `messages` | Full history; `system`/`user`/`assistant` roles. Multimodal `image_url` parts are read when the `vision` feature is enabled (local data-URIs only, no outbound fetch). |
| `stream: true` | Real server-sent-event token streaming (not post-hoc chunking of a finished string). |
| `stop` | Honored — the reply is truncated at the earliest stop sequence (max 4, per OpenAI). |
| `response_format` | `{"type": "json_object"}` is honored **best-effort** — a strict-JSON output directive is prepended to the system context. Not a hard schema guarantee (Layla runs its agent loop, not a constrained decode). |
| `usage` | **Real token counts** (resident-model tokenizer for non-ASCII, tiktoken otherwise), suitable for cost/token accounting. |

## Not supported (by design) — and what to do instead

- **OpenAI client-side function/tool calling** (`tools`, `tool_choice`, `functions`). Layla's tools
  run inside its own agent loop, not via the OpenAI tool protocol, so the response never contains
  `tool_calls`. Offering `tools` with the default `tool_choice: "auto"` (or omitting `tool_choice`)
  is accepted and returns a normal assistant message. But `tool_choice: "required"` or a named
  function — which *demand* a `tool_call` — cannot be satisfied and return a clear `400`
  (`tool_choice_unsupported`) rather than silently handing back unparseable prose. To let a `/v1`
  turn use Layla's own tools, add the non-standard body fields `allow_write`, `allow_run`, and
  `workspace_root` (Layla extension), or use the native `POST /agent` endpoint.
- **Request `temperature` / `max_tokens` / `top_p` applied to generation.** They are accepted (so
  clients that always send them don't break) but the server uses its own tuned sampling — feeding a
  client temperature into the internal tool-decision calls corrupts their JSON, so it is deliberately
  not threaded through. `stop` is the one sampling field that IS applied to the final text.
- **Logprobs, `n>1`, embeddings, the Assistants API.**

## Quick check

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"layla","messages":[{"role":"user","content":"Write a Python is_prime(n)."}]}'
```

Note: on a CPU-only box first-token latency is seconds and throughput is ~3–10 tok/s (see
[../benchmarks/README.md](../benchmarks/README.md)); size your client timeouts accordingly.

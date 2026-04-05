# Backup ingestion, chat logs, audio, and Elasticsearch

How to feed Layla **historical data** (chat exports, backups, audio) and optionally mirror memory into **Elasticsearch** for full-text search.

## Design principles

1. **Approvals** — Destructive restores use the normal approval path when `safe_mode` applies.
2. **Knowledge path** — Bulk chat text lands under `knowledge/_ingested/chats/` as Markdown so the **existing Chroma/BM25 indexer** can pick it up on refresh (same pattern as [doc_ingestion](../agent/services/doc_ingestion.py)).
3. **Audio** — Use the **`stt_file`** tool (faster-whisper) on files under the sandbox; then index transcripts via the chat export tool or `POST /learn/`.
4. **Elasticsearch** — **Optional**. When `elasticsearch_enabled` is true and `elasticsearch` Python client + server are available, learnings are mirrored to an index for keyword/BM25-style search alongside Chroma.

## Chat exports & external logs

| Source | Notes |
|--------|--------|
| **ChatGPT export** (JSON) | Heuristic parsers extract `role` / `content` (or nested message lists). Place export in **workspace** (sandbox), run `ingest_chat_export_to_knowledge`. |
| **Cursor / VS Code** | Export or copy conversation text into `.md` under `knowledge/_ingested/` manually, or normalize to JSON array of `{role, content}`. |
| **screenpipe / other recorders** | Only useful if you **export** to JSON/JSONL/Markdown Layla can read; not wired as native protocols. |
| **Generic JSONL** | One JSON object per line with `role` + `content` (or `message`, `text`). |

**Tool:** `ingest_chat_export_to_knowledge` — see tool docstring in `layla/tools/registry.py`.

## Audio backlog

1. Put audio files under **sandbox** (e.g. workspace `backups/audio/`).
2. Call **`stt_file`** per file (or batch via agent plan).
3. Save transcripts with **`ingest_chat_export_to_knowledge`** (if you build a small JSON wrapper) or append to a single `.md` in `knowledge/_ingested/` with the data-framing prefix (see `doc_ingestion`).

## File checkpoints (Cursor-like safety)

When **`file_checkpoint_enabled`** is true, Layla stores a **snapshot of the previous file contents** immediately before **`write_file`**, **`apply_patch`**, **`search_replace`**, or **`write_files_batch`** executes (including after **approval**).

- **List:** `list_file_checkpoints`  
- **Restore:** `restore_file_checkpoint` (typically **approval-gated** like other writes)

Checkpoints live under **`{workspace}/.layla/file_checkpoints/`** (workspace-relative when a sandbox path is known; otherwise agent metadata dir — see `file_checkpoints` module).

**Retention:** `file_checkpoint_max_count` (default 200) and `file_checkpoint_max_bytes` (default ~200MB) prune oldest bundles after each new snapshot. Set either to **0** for unlimited in that dimension.

## Elasticsearch

**Install (optional):**

```bash
pip install elasticsearch
```

Run an Elasticsearch **8.x** instance; set in `runtime_config.json`:

- `elasticsearch_enabled`: `true`
- `elasticsearch_url`: e.g. `http://127.0.0.1:9200`
- `elasticsearch_index_prefix`: default `layla`
- `elasticsearch_api_key`: optional

**Behavior:**

- On **`save_learning`**, a document is indexed (best-effort; failures are logged, never block SQLite).
- **API:** `GET /memory/elasticsearch/search?q=...&limit=20`
- **Tool:** `memory_elasticsearch_search` (read-only)

Layla’s **source of truth** remains SQLite + Chroma; ES is a **searchable mirror** for operators who want Kibana / ELK workflows.

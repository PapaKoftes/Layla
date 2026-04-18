# Memory system (as implemented)

Sources: [`agent/layla/memory/db_connection.py`](../../agent/layla/memory/db_connection.py), [`agent/layla/memory/migrations.py`](../../agent/layla/memory/migrations.py), [`agent/layla/memory/vector_store.py`](../../agent/layla/memory/vector_store.py), [`agent/autonomous/investigation_reuse.py`](../../agent/autonomous/investigation_reuse.py), [`agent/autonomous/wiki.py`](../../agent/autonomous/wiki.py).

## SQLite

- **Default DB path**: [`_default_db_path`](../../agent/layla/memory/db_connection.py) — `LAYLA_DATA_DIR/layla.db` if env set, else repo-parent **`layla.db`**.
- **Connection**: WAL, synchronous NORMAL, cache, mmap, busy timeout ([`_conn`](../../agent/layla/memory/db_connection.py)).
- **Schema**: created/migrated in [`migrations.py`](../../agent/layla/memory/migrations.py) — tables include **`learnings`**, **`study_plans`**, **`wakeup_log`**, **`audit`**, **`aspect_memories`**, FTS5 **`learnings_fts`**, telemetry tables, etc.

## File-backed investigation reuse

- **Path**: `<workspace_root>/.layla/investigation_reuse.jsonl`
- **Append**: [`maybe_append_investigation_reuse`](../../agent/autonomous/investigation_reuse.py) when **`investigation_reuse_store_enabled`** is true and confidence high (see CONFIG_SYSTEM).
- **Prefetch read**: [`reuse_retrieval.try_reuse_retrieval`](../../agent/autonomous/reuse_retrieval.py).

## Wiki (Tier-0)

- **Root**: [`wiki_root_for_workspace`](../../agent/autonomous/wiki.py) → **`<workspace>/.layla/wiki`**
- **Writes**: gated by **`autonomous_wiki_enabled`**, **`autonomous_wiki_export_enabled`**, **`allow_write`** on task; [`write_wiki_entry`](../../agent/autonomous/wiki.py).

## Chroma

- **Persistent directory**: **`CHROMA_PATH`** = [`agent/layla/memory/chroma_db`](../../agent/layla/memory/vector_store.py) (under `layla/memory/`).
- **Collections**: **`learnings`** (embeddings for stored learnings), **`knowledge`** (indexed knowledge chunks) — see [`_get_chroma_collection`](../../agent/layla/memory/vector_store.py) / [`_get_knowledge_collection`](../../agent/layla/memory/vector_store.py).
- **Embeddings**: [`embed`](../../agent/layla/memory/vector_store.py) uses sentence-transformers (nomic primary, MiniLM fallback per implementation).
- **Startup**: [`main.py`](../../agent/main.py) may background-index **`knowledge/`** when **`use_chroma`** is true.

## HTTP learn endpoints

- **`GET /memories`**, **`POST /learn/`** ([`routers/learn.py`](../../agent/routers/learn.py)) use vector store + SQLite **`save_learning`** as implemented.

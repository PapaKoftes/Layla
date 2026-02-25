# Knowledge folder

Add your own `.md` and `.txt` files here. With Chroma enabled, their content is indexed and used as RAG context so Layla can use them when relevant.

- **Each collaborator** should build their own knowledge for their needs; this folder is not committed with shared content.
- Keep files focused (e.g. best practices, project conventions, coding standards). A few KB per file is enough.
- Optional: add URLs to `agent/runtime_config.json` under `knowledge_sources` and run `python agent/download_docs.py` to fetch into `knowledge/fetched/`.

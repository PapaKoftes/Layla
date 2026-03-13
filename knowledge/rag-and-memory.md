---
priority: support
domain: ai-architecture
---

# RAG, Memory, and Retrieval — How Layla's Knowledge Works

## What RAG is

Retrieval-Augmented Generation (RAG) means: instead of relying only on what the model has in its weights, you retrieve relevant documents/memories at query time and inject them into the context. This gives the model up-to-date, specific, domain-relevant information it couldn't know otherwise.

## Layla's retrieval pipeline

Layla uses a multi-stage pipeline for every query:

### 1. BM25 (keyword search)
Classic bag-of-words search using BM25Okapi scoring. Fast, exact, excellent for code symbols, function names, error messages, and specific terminology. Built over the full learnings corpus.

### 2. Dense vector search (semantic)
Sentence-transformers model (`nomic-embed-text-v1.5` or `all-MiniLM-L6-v2`) embeds the query and finds semantically similar content via ChromaDB cosine similarity. Captures meaning even when exact words differ.

### 3. FTS5 (SQLite full-text search)
Porter-stemmed full-text search over learnings. Fast, handles stemming ("running" matches "run"), no model required. Runs alongside BM25.

### 4. Reciprocal Rank Fusion (RRF)
Fuses the ranked result lists from BM25, vector, and FTS5 into a single unified ranking. Each result gets a score of `1/(k + rank)` for each list it appears in, then scores are summed. This is more robust than any single method alone.

### 5. Cross-encoder reranking
A separate model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) takes the top candidates and re-scores each (query, document) pair. This is much more accurate than embedding similarity alone but slower — used on the top 20 candidates to pick the final top 5.

### 6. HyDE (Hypothetical Document Embeddings)
Generate a short hypothetical answer to the query first, then search with *that* embedding. Dramatically improves recall when the query phrasing doesn't match document language. Example: query "how do I stop the model from repeating itself" → hypothetical answer "set repeat_penalty to 1.1 in the config" → embedding of the hypothetical answer finds the config documentation.

### 7. Parent-document retrieval
When a matching chunk is found in the knowledge base, return the surrounding ±400 characters from the original document for richer context.

## Memory types in Layla

| Store | What's in it | How it's used |
|---|---|---|
| `learnings` table (SQLite) | Facts, corrections, preferences you've taught Layla | Retrieved via BM25 + vector + FTS5 |
| `aspect_memories` table | Echo's observations about patterns in your work | Injected when Echo is active |
| ChromaDB `memories` collection | Vector index over learnings for semantic search | Dense retrieval |
| ChromaDB `knowledge` collection | Indexed knowledge/ files | Injected as reference docs per turn |
| `knowledge_graph.graphml` | Relationship graph between concepts | Experimental |

## How to add knowledge

1. **Tell Layla directly**: "Remember that X" or "Learn this: Y" → stored as learning
2. **Knowledge files**: Put `.md`, `.txt`, or `.pdf` in `knowledge/` → auto-indexed
3. **MCP**: `add_learning` tool from Cursor → stored immediately
4. **API**: `POST /learn/` with `{"content": "...", "type": "fact"}`

## How much memory affects context

Layla injects retrieved memories into the system prompt on each turn. The amount is controlled by:
- `learnings_n`: max recent learnings to include (default 30)
- `semantic_k`: top-k semantically relevant memories (default 5)
- `knowledge_chunks_k`: top-k knowledge chunks from files (default 5)
- `knowledge_max_bytes`: max bytes of knowledge content (default 4000)

## Study plans

Layla studies topics autonomously via APScheduler. Add topics:
- CLI: `python layla.py study "topic"`
- UI: Study Plans panel
- API: `POST /study_plans` with `{"topic": "..."}`

The scheduler runs every 30 minutes (configurable) and skips when you're actively using her or playing games. Study results are stored as learnings.

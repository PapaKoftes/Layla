# Architecture — Platform Overview

> One-page overview. See `../ARCHITECTURE.md` for request flow and key files.

---

## Platform subsystems

| Subsystem | Module | Role |
|-----------|--------|------|
| **Task graph** | `services/task_graph.py` | TaskNode, TaskGraph, GraphExecutor — missions as dependency graphs |
| **Model router** | `services/model_router.py` | Route by task type: coding, reasoning, chat |
| **Resource manager** | `services/resource_manager.py` | CPU/RAM/GPU tracking; suggest context size, parallel tasks |
| **Workspace index** | `services/workspace_index.py` | Index projects with embeddings for semantic search |
| **Self-improvement** | `services/self_improvement.py` | Analyze codebase, propose improvements (read-only) |
| **System doctor** | `services/system_doctor.py` | Full diagnostics — `layla doctor` or GET `/doctor` |
| **Model benchmark** | `services/model_benchmark.py` | Store results in ~/.layla/benchmarks.json; `select_fastest_model()` |

---

## Memory retrieval pipeline

1. Hybrid (BM25 + vector) with RRF fusion  
2. FTS5 keyword merge  
3. Cross-encoder reranking  
4. Optional MMR diversity (`retrieval_use_mmr: true`)  
5. Confidence + recency boost  

---

## Skills

Skills live in `agent/layla/skills/registry.py`. Can call other skills via `sub_skills`. See [SKILLS.md](SKILLS.md).

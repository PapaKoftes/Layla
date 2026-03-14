# Capabilities

Layla's capability system allows multiple implementations per capability (e.g. vector_search → chromadb, faiss, qdrant). The system discovers candidates, benchmarks them, validates in sandbox, and selects the best-performing implementation automatically.

---

## Capability Registry

**Location:** `agent/capabilities/registry.py`

Each capability may have multiple implementations:

| Capability | Implementations | Default |
|------------|-----------------|---------|
| `vector_search` | chromadb, faiss, qdrant | chromadb |
| `embedding` | sentence_transformers, openai | sentence_transformers |
| `reranker` | cross_encoder, cohere | cross_encoder |
| `web_scraper` | trafilatura, beautifulsoup | trafilatura |

---

## Capability Discovery

**Module:** `agent/services/capability_discovery.py`

Scans for candidate libraries:

- **PyPI** — known packages per capability
- **GitHub** — trending repos (known list)
- **HuggingFace** — models for embedding/rerank

```python
from services.capability_discovery import discover_candidates, discover_all_capabilities

# Single capability
candidates = discover_candidates("vector_search")

# All capabilities
all_ = discover_all_capabilities()
```

Results are cached in `agent/.capability_discovery_cache/` (6h TTL).

---

## Benchmark Suite

**Module:** `agent/services/benchmark_suite.py`

Measures:

- **latency_ms** — per-operation latency
- **throughput_per_sec** — operations per second
- **memory_mb** — memory delta

Results stored in `layla.db` table `capability_implementations`.

```python
from services.benchmark_suite import run_benchmark, get_stored_benchmarks

# Run benchmark
result = run_benchmark("embedding", "sentence_transformers", "sentence-transformers")

# List stored results
stored = get_stored_benchmarks("vector_search")
```

---

## Dynamic Implementation Selection

**Selection order:**

1. Config override: `capability_impls.vector_search = "faiss"` in `runtime_config.json`
2. Best benchmarked: lowest latency, `sandbox_valid=1`, status `active` or `benchmarked`
3. Default: first implementation marked `is_default` in registry

```python
from capabilities.registry import get_active_implementation
import runtime_safety

cfg = runtime_safety.load_config()
impl = get_active_implementation("vector_search", cfg)
# impl.id → "chromadb" or "faiss" etc.
```

---

## Sandbox Validation

**Module:** `agent/services/sandbox_validator.py`

Before enabling a capability:

1. Import check — package importable in subprocess
2. Benchmark — run benchmark suite
3. Store — update `capability_implementations` with `sandbox_valid`

```python
from services.sandbox_validator import run_sandbox_benchmark

result = run_sandbox_benchmark("vector_search", "chromadb", "chromadb")
# result["ok"], result["valid"], result["latency_ms"]
```

---

## Performance Monitor

**Module:** `agent/services/performance_monitor.py`

Tracks runtime metrics:

- `tool_latency_ms` — tool execution latency
- `retrieval_latency_ms` — RAG retrieval
- `token_throughput` — LLM tokens/sec
- `memory_mb` — process memory

```python
from services.performance_monitor import (
    record_tool_latency,
    get_tool_latency_stats,
    get_summary,
)

record_tool_latency("read_file", 12.5)
stats = get_tool_latency_stats("read_file")
summary = get_summary()
```

---

## Self-Improvement Extension

**Module:** `agent/services/self_improvement.py`

Extended with:

- `evaluate_capabilities()` — current implementations and benchmark status
- `detect_missing_capabilities()` — capabilities with no valid benchmarked impl
- `propose_capability_integrations()` — candidates from discovery

`propose_improvements()` now includes capability context in its LLM prompt.

---

## Configuration

Add to `runtime_config.json`:

```json
{
  "capability_impls": {
    "vector_search": "faiss",
    "embedding": "sentence_transformers"
  }
}
```

---

## Database

Table `capability_implementations`:

| Column | Type | Description |
|--------|------|-------------|
| capability_name | TEXT | vector_search, embedding, etc. |
| implementation_id | TEXT | chromadb, faiss, etc. |
| package_name | TEXT | PyPI package |
| status | TEXT | candidate, benchmarked, active |
| latency_ms | REAL | Benchmark latency |
| throughput_per_sec | REAL | Benchmark throughput |
| memory_mb | REAL | Benchmark memory |
| sandbox_valid | INT | 1 if validated |
| last_benchmarked_at | TEXT | ISO timestamp |

---

## Adding a Capability

1. Add to `agent/capabilities/registry.py`:

```python
CAPABILITIES["my_capability"] = [
    CapabilityImpl(id="impl1", package="pkg", module_path="...", is_default=True),
]
```

2. Add search terms in `capability_discovery.py`:

```python
CAPABILITY_SEARCH_TERMS["my_capability"] = ["term1", "term2"]
```

3. Add benchmark in `benchmark_suite.py`:

```python
def benchmark_my_capability(impl_id: str) -> dict: ...
# Register in run_benchmark()
```

"""Packaged-smoke embedder probe (run by installer/packaged_smoke.ps1).

Loads the embedder in the *packaged* Python and exits non-zero if it can't — the check that would have
caught the fresh-install "EMBEDDER UNAVAILABLE: is_torch_npu_available" degradation. argv[1] is the agent
dir to put on sys.path."""
import sys

sys.path.insert(0, sys.argv[1])
from layla.memory.vector_store import prefetch_embedder  # noqa: E402

r = prefetch_embedder()
print("EMBEDDER ok=%s model=%s %s" % (r.get("ok"), r.get("model"), r.get("detail") or r.get("error") or ""))
sys.exit(0 if r.get("ok") else 3)

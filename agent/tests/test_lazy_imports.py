"""
Locks the lazy-import contract for the app startup graph.

Cold-start on a low-end machine depends on NOT eagerly importing the multi-hundred-MB
native/ML deps (torch, llama_cpp, sentence_transformers, transformers, chromadb) at
module load. They must be imported lazily inside the functions that use them, so a turn
that never touches inference/embeddings never pays for them — and so `import`ing the app
to serve a health check or a static asset stays sub-second.

This runs the imports in a clean subprocess (so earlier tests' imports can't pollute
sys.modules) and asserts none of the heavy deps were pulled in. A stray top-level
`import torch` in a hot module will fail this test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent

# The modules FastAPI loads to boot the app / serve a turn.
STARTUP_MODULES = [
    "runtime_safety",
    "services.llm.llm_gateway",
    "agent_loop",
    "orchestrator",
    "routers.agent",
    "routers.memory",
    "routers.settings",
]

# Multi-hundred-MB deps that must never load just from importing the startup graph.
HEAVY = ["torch", "sentence_transformers", "llama_cpp", "transformers", "chromadb"]


def test_startup_graph_defers_heavy_imports():
    code = (
        "import sys\n"
        f"for m in {STARTUP_MODULES!r}:\n"
        "    __import__(m)\n"
        f"heavy = {HEAVY!r}\n"
        "loaded = [m for m in heavy if any(k == m or k.startswith(m + '.') for k in sys.modules)]\n"
        "sys.stdout.write('LOADED:' + ','.join(loaded))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(AGENT_DIR),
    )
    assert proc.returncode == 0, f"startup import subprocess failed:\n{proc.stderr[-2000:]}"
    marker = "LOADED:"
    loaded = proc.stdout[proc.stdout.rindex(marker) + len(marker):].strip() if marker in proc.stdout else "<no marker>"
    assert loaded == "", (
        f"startup graph eagerly imported heavy dep(s): {loaded} — move the import inside "
        f"the function that needs it to keep cold-start fast."
    )

# Layla test suite

Run the full default suite from `agent/`:

```bash
../.venv-test/Scripts/python.exe -m pytest -q
```

The default suite is hermetic — no model, no network, no GPU. Some suites are **intentionally
gated** on an optional dependency, an environment variable, or a fixture, so they *skip* rather
than fail when their prerequisite is absent. Every skip carries an explicit `reason=` — surface
them with `pytest -rs` (nothing is silently skipped; this is the BL-145 contract).

## Gated suites — what they are and how to enable them

| Suite / file | Gate | Enable it |
| --- | --- | --- |
| `test_inference_smoke.py` | env `LAYLA_TEST_REAL_LLM` | `LAYLA_TEST_REAL_LLM=1` + a resolvable GGUF (the `inference-smoke` CI job). Real end-to-end generation. |
| `test_benchmark_coding_model.py` | env `LAYLA_BENCH_MODEL` | `LAYLA_BENCH_MODEL=/path/model.gguf` (opt: `LAYLA_BENCH_FLOOR`, default 0.5). Live pass@1 regression. |
| `test_code_intelligence.py`, `test_workspace_index.py` | `tree_sitter` + `tree_sitter_python` | `pip install tree-sitter tree-sitter-python` (kept **optional/heavy** — commented in requirements.txt). |
| `integration_smoke/test_browser_smoke.py` | `playwright` | `pip install playwright && playwright install chromium`. |
| `test_fabrication_assist_runner.py`, `test_geometry_executor.py`, `test_machining_ir.py` | `ezdxf` | `pip install ezdxf` (the `fabrication` optional feature). |
| `test_notebook_tools.py` | `nbformat` | `pip install nbformat`. |
| `test_repo_indexer.py` | `networkx` | `pip install networkx`. |
| `test_memory_encryption.py` (real-crypto cases) | `cryptography` | `pip install cryptography` (the `encryption` optional feature). Pure-logic + graceful-degradation cases run without it. |
| `test_git_worktree_tools.py` | `git` on PATH | install git (present in CI). |
| `test_sandbox.py` (one case) | **skips under `CI`** | runs locally; CI provides an explicit `runtime_config.json`. |

## Fixtures that must be present (and are, in-repo)

- **`tests/fixtures/fake_mcp_stdio.py`** — a minimal stdio MCP server (initialize / tools/call).
  Present, so `test_mcp_client_stdio.py` (12 tests) **runs by default**. (BL-140.)
- **`personalities/`** — the aspect definitions dir. Present, so `test_aspect_behavior.py`
  (40 tests) **runs by default**; the `skipif` guards only a stripped checkout. (BL-144.)

## Env vars the suite honors

- `LAYLA_TEST_REAL_LLM` — enable real-LLM smokes (off by default).
- `LAYLA_BENCH_MODEL` / `LAYLA_BENCH_FLOOR` — coding-benchmark model + pass@1 floor.
- `CI` — set in CI; toggles a couple of environment-specific expectations.

New env-gated or optional-dep tests **must** ship an explicit `reason=` and be listed here, so a
skip is always an intentional, documented choice — never a silent hole.

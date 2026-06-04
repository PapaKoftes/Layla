# Dev testing — fast path

Running the test suite does **not** require the full GPU/model stack
(`llama-cpp-python`, `torch`, `chromadb`, `sentence-transformers`). There's a
lightweight `dev` extra and a setup script for it.

## One-command setup (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_test_env.ps1
```

This finds a **Python 3.11/3.12** interpreter (via the `py` launcher, so it works
even when your default `python` is 3.13+), creates `.venv-test`, installs the
`dev` extra, and smoke-tests the dependency-free tests.

Then:

```powershell
.\.venv-test\Scripts\Activate.ps1
cd agent
pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"
```

## Manual / other platforms

```bash
python3.12 -m venv .venv-test
.venv-test/bin/pip install -e ".[dev]"
cd agent && pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"
```

If a test fails with `ModuleNotFoundError`, add the missing package to the `dev`
extra in `pyproject.toml` (it's a deliberately minimal, no-GPU set).

## The dependency-free tests run on ANY Python (incl. 3.14)

Some modules are pure stdlib and their tests need no third-party deps at all —
useful when you only have a newer Python and can't build the full stack:

```bash
cd agent
python -m pytest tests/test_port_guard.py tests/test_url_guard.py \
  tests/test_sandbox_core.py tests/test_extract_archive_safety.py \
  tests/test_council_models.py tests/test_user_identity.py -q
```

These cover the security-critical primitives (SSRF guard, port guard, sandbox
containment, archive extraction safety) and the council model routing.

## Why the split

`pyproject.toml` extras:

| Extra | Purpose |
|-------|---------|
| `dev` | minimal stack to run the test suite (no GPU/model) |
| `core` | full runtime incl. embeddings/RAG (`chromadb`, `sentence-transformers`) |
| `llm` | `llama-cpp-python`, `litellm` — local/remote inference |
| `voice`, `crawl`, `research`, `data`, … | optional feature groups |

The `dev` extra deliberately excludes the heavy, slow-to-build packages so a
clean machine can run `pytest` in seconds rather than waiting on a
`llama-cpp-python` source build.

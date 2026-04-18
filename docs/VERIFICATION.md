# Verification bundle (CI parity)

Run these from the **`agent/`** directory so imports and `runtime_config.json` match CI.

## Default automated gate (same marker set as CI)

PR CI excludes optional integration smokes so Chromium / Whisper downloads do not run on every push:

```bash
cd agent
python -m pytest tests/ -v --tb=short \
  -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke" \
  --timeout=60
```

## With coverage floor (requires `pytest-cov` from `requirements.txt`)

```bash
cd agent
python -m pytest tests/ \
  -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke" \
  --timeout=60 \
  --cov=. --cov-config=.coveragerc --cov-report=term-missing:skip-covered
```

The minimum **branch-aware** coverage is enforced in [`agent/.coveragerc`](../agent/.coveragerc) (`fail_under`, currently a conservative ratchet). Raise it gradually as tests grow.

GitHub Actions also runs a **Windows** job (`test-windows` in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)): same pytest marker set, **no** coverage floor, 120s per-test timeout.

## Daily-driver smoke (optional fast signal)

CI runs an additional **narrow** pytest step after **`check_ui_symbols.py`**: `tests/test_edit_loop_tools.py` and `tests/test_autonomous_v2.py`. This is **not** a substitute for the full marker-gated suite above; it catches regressions in edit-loop tooling and tier-0 autonomous guards without importing the entire tree’s slow paths.

Broader `-k "autonomous or …"` style filters were considered but are **not** wired as the default CI gate because marker + file picks are **stable** and faster to diagnose when red.

## Deep verification (nightly / manual)

Workflow [`.github/workflows/verify-deep.yml`](../.github/workflows/verify-deep.yml) (`schedule` + `workflow_dispatch`):

- **E2E UI** — same as CI `e2e-ui` job (`pytest tests/e2e_ui/ -m e2e_ui`).
- **Browser smoke** — `pytest tests/integration_smoke/test_browser_smoke.py -m browser_smoke` after `playwright install chromium`.
- **Voice smoke** — `pytest tests/integration_smoke/test_voice_smoke.py -m voice_smoke` (uses `whisper_model: tiny` in the workflow stub config; may download models).
- **Doctor artifact** — uploads `doctor-report.json` (base diagnostics + cheap `capability_probe`).

### Optional GPU smoke (local / self-hosted)

Not run in default GitHub-hosted workflows. On a machine with a real GGUF and GPU:

```bash
set LAYLA_GPU_SMOKE=1
set LAYLA_GPU_SMOKE_GGUF=C:\path\to\small.gguf
cd agent
python -m pytest tests/integration_smoke/test_gpu_smoke.py -m gpu_smoke -v
```

Optional: `LAYLA_GPU_SMOKE_N_GPU_LAYERS`, `LAYLA_GPU_SMOKE_N_CTX`.

## Runtime capability probe (operator)

With the server up:

- **`GET /doctor`** — fast diagnostics (dependencies, model dir, hardware summary, tool count).
- **`GET /doctor/capabilities`** — adds `capability_probe` (inference backend, GPU vs `n_gpu_layers` hints, `llama_cpp`, Playwright).
- **`GET /doctor/capabilities?browser_launch=true`** — also tries to launch Chromium (requires `playwright install chromium`).
- **`GET /doctor/capabilities?voice_micro=true`** — may run tiny STT/TTS (slow; downloads models on first use).

## Lint (optional)

```bash
python -m pip install ruff
ruff check agent fabrication_assist
```

## Parity manifest (paths / symbols vs docs)

```bash
cd agent
python -m pytest tests/test_parity_manifest.py -q
```

## Tool inventory (optional)

```bash
python agent/scripts/generate_tool_inventory.py > tool-inventory.md
```

## README screenshots & GIF (optional, before tagging)

Regenerate **`readme-assets/`** so marketing images match current `/ui`:

```bash
pip install -r agent/requirements.txt -r agent/requirements-e2e.txt Pillow
python -m playwright install chromium
python scripts/capture_readme_assets.py
```

See [media/README.md](media/README.md).

## Release

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for full pre-tag steps including Web UI smoke and `/health` manual checks.

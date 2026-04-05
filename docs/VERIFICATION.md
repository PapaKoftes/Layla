# Verification bundle (CI parity)

Run these from the **`agent/`** directory so imports and `runtime_config.json` match CI.

## Default automated gate (same marker set as CI)

```bash
cd agent
python -m pytest tests/ -v --tb=short -m "not slow and not e2e_ui" --timeout=60
```

## With coverage floor (requires `pytest-cov` from `requirements.txt`)

```bash
cd agent
python -m pytest tests/ -m "not slow and not e2e_ui" --timeout=60 \
  --cov=. --cov-config=.coveragerc --cov-report=term-missing:skip-covered
```

The minimum **branch-aware** coverage is enforced in [`agent/.coveragerc`](../agent/.coveragerc) (`fail_under`, currently a conservative ratchet). Raise it gradually as tests grow.

GitHub Actions also runs a **Windows** job (`test-windows` in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)): same pytest marker set, **no** coverage floor, 120s per-test timeout.

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

## Release

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for full pre-tag steps including Web UI smoke and `/health` manual checks.

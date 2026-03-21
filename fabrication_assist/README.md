# Fabrication assist (root package)

This tree holds **infrastructure** for a pattern where:

- **Assist layer** — interaction, variant exploration, comparison framing, explanation, local session memory. It does **not** assert fabrication truth.
- **Deterministic kernel** — your own deterministic evaluator, invoked only through **`BuildRunner`** ([`fabrication_assist/assist/runner.py`](assist/runner.py)).

On **`main`**:

- **`StubRunner`** — synthetic **`ProductResult`** dicts (validated by Pydantic).
- **`SubprocessJsonRunner`** — runs **`python -m fabrication_assist.assist.echo_kernel`** with a temp JSON config (used in tests and as a reference integration).

## Layout

- `fabrication_assist/assist/` — `schemas`, `errors`, `layla_lite.assist()`, `echo_kernel`, session, variants, explain, runners, CLI
- `fabrication_assist/assist/knowledge/*.example.yaml` — committed examples; copy and extend locally
- `fabrication_assist/.assist_sessions/` — JSON sessions (gitignored)

## Quick use

```bash
# After: pip install -e .   OR   PYTHONPATH=<repo root>
python -m fabrication_assist.assist "CNC bracket, minimize machining time"
python -m fabrication_assist.assist --runner subprocess "CNC bracket"
python -m fabrication_assist.assist --dry-run "enclosure"
```

See **[docs/FABRICATION_ASSIST.md](../docs/FABRICATION_ASSIST.md)** (exit codes, flags, schemas) and **[knowledge/fabrication-assist-layer.md](../knowledge/fabrication-assist-layer.md)**.

## Import hygiene

Do not import `fabrication_assist` from `agent/main.py` or the agent loop on **`main`** unless you deliberately add an integration; keeps startup predictable and avoids tight coupling.

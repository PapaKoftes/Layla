# Self-running audit loop

A rotating, coverage-tracked, adversarially-verified **audit + auto-fix** loop for the whole codebase — not a single lens. One invocation = one *rotation*: pick the next risk dimension from the ledger, reality-anchor, fan-out finders, verify by refutation, root-cause triage, auto-fix the safe ones (green-gated), update the ledger.

## Files
- `config.json` — policy: autonomy, budget, severity gate, protected paths, test command. Edit freely.
- `ledger.json` — the dimension portfolio + convergence state. The loop reads it to choose what to audit and writes back after each round. Edit weights/cadence/lenses to steer coverage.
- `reports/round-<n>-<dimension>.md` — per-round report; **report-only findings that need a human land here.**
- `../../.claude/workflows/audit-loop.mjs` — the engine (a Workflow script).

## Run it as a tool
Full rotation:
```
Workflow({ name: "audit-loop" })
```
(or `Workflow({ scriptPath: ".claude/workflows/audit-loop.mjs" })` if the name doesn't resolve)

Cheap wiring smoke-test (no full suite, no fixes — validates plumbing only):
```
Workflow({ name: "audit-loop", args: { mode: "validate" } })
```

It runs in the background and its subagents do all the token-heavy work — it does **not** consume the interactive context per step.

## What it will and won't do to your repo
- **Auto-fixes only LOW/MEDIUM, mechanical, non-ambiguous findings.** critical/high + anything triage flags ambiguous → **report-only** (written to `reports/`, never auto-pushed).
- **Green-gated push:** applies fixes one at a time with scoped tests, then runs the FULL suite once. It pushes to `master` **only if there are no NEW failures vs the baseline** it measured at the start of the round. Any new failure → `git reset --hard` the whole round, push nothing, and the findings become report-only.
- **Never** stages/commits the protected operator-state files (see `config.protected_paths`).
- Every commit ends with the required `Co-Authored-By` trailer.

## Scheduling
It's registered on a cron (see `schedule`/CronList). Each firing = one rotation; it self-limits by `budget_tokens_per_round` and logs `ALL DIMENSIONS QUIESCENT` when every dimension has gone `quiescence_dry_rounds` rounds with no new confirmed findings — the natural stop signal. Pause/remove the cron any time via the schedule tool.

## Convergence
A dimension is `quiescent` after N consecutive dry rounds; new confirmed findings reset it. The loop keeps rotating through non-quiescent dimensions; when all are quiescent it drops to light maintenance sweeps. Reality-anchor runs every round regardless — a working product is the ground truth, not green tests.

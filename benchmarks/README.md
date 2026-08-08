# Coding benchmarks

Tracked pass@1 scorecards from `scripts/benchmark_coding.py` (REQ-74). The number
makes "the coding is good" measurable instead of asserted.

## Baselines (this hardware tier: 4-core / ~16GB / no-GPU — the friend's laptop)

Two tiers now: **core** (10 easy/medium fundamentals) and **hard** (12 discriminating
LeetCode-medium/hard: LCS, edit distance, decode_string, three_sum, spiral_order,
next_permutation, simplify_path, …). All runs are deterministic (temperature 0, seed 42).

| Model | Quant | core pass@1 | hard pass@1 | tok/s | date |
|---|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | Q4_K_M | **100% (10/10)** | **100% (12/12)** | 3.4 / 4.2 | 2026-07-15 |
| Qwen2.5-Coder-3B-Instruct | Q4_K_M | **100% (10/10)** | **100% (12/12)** | 6.6 / 9.6 | 2026-07-15 |

(Earlier: 7B core 100% @ 3.17 tok/s, 2026-06-29 — re-verified above on current code.)

## Honest reading
- **22/22 across both models.** Both the default (7B) and the lite (3B) coder solve
  every fundamentals problem AND every hard algorithmic problem — genuine confidence
  that focused, well-specified coding is solid, not just asserted.
- **The 3B matches the 7B on every problem at ~2.3× the speed** (9.6 vs 4.2 tok/s on
  the hard tier). On this CPU tier the 3B is the better *coding* default; the 7B's
  extra capacity only pays off on long-context / multi-file / ambiguous-NL work, which
  this set does not probe.
- Both tiers are now **saturated** by these models — a *separating* score needs harder,
  longer, or multi-file problems (e.g. full HumanEval-164 + repo-level tasks). 100% here
  means "no failures across 22 canonical problems," not "the ceiling was found."
- A third **`--xhard`** tier (5 OS-independent problems: largest_rectangle, coin_change, LIS,
  trap_rain_water, min_window) was added to probe for separation. Measured on an RTX 5060 Ti
  (GPU, sm_120 build): **7B 100% (5/5) @ 43.8 tok/s, 14B 100% (5/5) @ 23.0 tok/s** — *also*
  saturated. Confirms canonical LeetCode-hard does not separate these Coder models; genuine
  separation needs non-canonical work (repo-level, long-context, novel algorithms). The tier
  is intentionally OS-independent: `simplify_path` in the hard tier is `os.path`-sensitive
  (a solution using `os.path.abspath` passes on Linux, fails on Windows), so filesystem-path
  problems measure the host OS, not the model. Run with `--xhard`; it is not tied to any CI floor.

## Run it
```bash
python scripts/benchmark_coding.py --model models/<model>.gguf --out benchmarks/scorecard_<model>.json
python scripts/benchmark_coding.py --hard --model models/<model>.gguf --out benchmarks/scorecard_<model>-hard.json
python scripts/benchmark_coding.py --self-test   # validate the harness (no model)
```

## Kept current (do this when the model or coding path changes)

These numbers must not drift from the code. Two guards keep them honest:

1. **Nightly CI regression** — the `coding-benchmark` job in `.github/workflows/ci.yml`
   downloads the 3B coder and runs BOTH tiers (`test_benchmark_coding_model.py`) against
   floors (`LAYLA_BENCH_FLOOR` core, `LAYLA_BENCH_HARD_FLOOR` hard). A quality regression
   fails the build; it also runs on-demand via **workflow_dispatch**.
2. **Manual refresh on change** — when you swap the default model, change quant, or touch the
   generation/prompt path, regenerate the affected scorecard(s) with the commands above and
   update the table at the top of this file (and the summary table in the repo-root `README.md`).
   Both are committed artifacts, so the diff shows exactly how quality moved.

When you add a harder/longer problem set (e.g. full HumanEval-164 or repo-level tasks), extend
`PROBLEMS_HARD` in `scripts/benchmark_coding.py` — the CI guard and both tables pick it up
automatically.

# Coding benchmarks

Tracked pass@1 scorecards from `scripts/benchmark_coding.py` (REQ-74). The number
makes "the coding is good" measurable instead of asserted.

## Baselines (this hardware tier: 4-core / 16GB / no-GPU — the friend's laptop)

| Model | Quant | pass@1 | tok/s | n | date |
|---|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | Q4_K_M | **100% (10/10)** | 3.17 | 10 | 2026-06-29 |

## Honest reading
- The curated set is **10 easy-to-medium canonical functions** (below_zero, gcd,
  string_xor, merge_sorted, …). A strong coder model *should* ace these — and
  Qwen-Coder-7B does, confirming it is genuinely good at **focused, well-specified
  implementation** (consistent with the earlier finding: strong on edits/specs,
  weaker on complex from-scratch self-verification).
- So 100% here means "no regressions on the fundamentals," **not** "saturated." The
  set is not yet discriminating at the hard end.
- **Next**: drop in the official HumanEval-164 (same problem shape) and add harder
  multi-step problems for a separating score; then use it for benchmark-driven model
  selection (REQ-85) and to compare quants/sizes.

## Run it
```bash
python scripts/benchmark_coding.py --model models/<model>.gguf --out benchmarks/scorecard_<model>.json
python scripts/benchmark_coding.py --self-test   # validate the harness (no model)
```

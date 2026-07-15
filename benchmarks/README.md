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

## Run it
```bash
python scripts/benchmark_coding.py --model models/<model>.gguf --out benchmarks/scorecard_<model>.json
python scripts/benchmark_coding.py --hard --model models/<model>.gguf --out benchmarks/scorecard_<model>-hard.json
python scripts/benchmark_coding.py --self-test   # validate the harness (no model)
```

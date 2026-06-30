# Eval / Grounding Harness for Layla

**Researched:** 2026-06-29
**Question:** What lightweight, local-friendly eval/grounding harness should Layla adopt to measure answer quality and catch regressions, without a cloud judge?
**Verdict:** Adopt a **two-layer harness**: (1) an inline **NLI/MiniCheck grounding check** wired into the completion gate for RAG/retrieval answers, and (2) a **promptfoo golden-set regression suite** (20-50 prompts) running nightly in CI against Layla's own local GGUF model as both the system-under-test and the judge. Both run fully offline, no paid API.

---

## 1. The actual gap in Layla (grounded in code)

The completion gate is `passes_completion_gate()` in `agent/services/output_quality.py`. It only checks:

- `empty_response` / `too_short` (len < 20)
- `restates_goal` — Jaccard token similarity vs. the goal >= 0.70
- `no_successful_tool_steps` — if tools ran, at least one must have `result.ok`
- `looks_like_decision_json` — don't leak a decision blob

There is **zero correctness or grounding signal**. A confident, fluent, *wrong* answer passes every check. The post-run scorer `evaluate_outcome()` / `evaluate_validation_matrix()` in `agent/services/outcome_evaluation.py` is also purely process-based (did tools succeed, did it finish, were artifacts written) — it never inspects whether the *text* is true or supported.

The RAG path that most needs grounding: `agent/autonomous/chroma_retrieval.py` (`try_chroma_retrieval`) pulls a learning excerpt from the Chroma vector store and hands it back as context. Nothing verifies that the final answer is entailed by that excerpt. This is the seam where a grounding check belongs — Layla already has the `(answer, retrieved_context)` pair in hand.

**Local model reality** (from `agent/services/litellm_gateway.py`, `agent/services/dependency_recovery.py`, `agent/services/agent_task_runner.py`): inference is local GGUF via `llama-cpp-python`, `llama-server`, or Ollama (OpenAI-compatible endpoint). Any eval must assume *no cloud judge* and a *small* model. Test framework is pytest. Vector stores: Chroma + Qdrant.

---

## 2. Tooling landscape (offline, no paid API)

| Tool | What it is | Runs offline / no paid API? | Fit for Layla |
|------|------------|------------------------------|---------------|
| **promptfoo** | Declarative prompt/agent/RAG eval + CI runner (YAML test cases, assertions, thresholds) | **Yes** — deterministic asserts (`contains`, `regex`, `javascript`, `python`, `similar` via local embeddings) need no LLM at all; `llm-rubric` defaults to OpenAI but can point at a **local Ollama/llama-server** judge | **Primary choice for the golden-set / regression layer.** First-class GitHub Action, per-test `threshold`, fails the build on regression. |
| **DeepEval** | pytest-native LLM eval framework; `FaithfulnessMetric`, `AnswerRelevancyMetric`, G-Eval | **Yes** — any judge model incl. **Ollama** via `LangchainLLMWrapper`; metrics decompose answer into claims and check against `retrieved_context` | Strong fit *if* you want metrics expressed as pytest tests. But its faithfulness/relevancy metrics **require an LLM judge** — quality on a tiny local model is shaky. Good for offline nightly, risky for inline gating. |
| **Ragas** | RAG-specific metrics: faithfulness, answer-relevancy, context-precision/recall | **Yes** — judge + embeddings are configurable to local models | Stricter logical-entailment semantics than DeepEval. Heavier dependency footprint; metrics are LLM-judge-based, so same small-model caveat. Best as an *offline* reference, not an inline gate. |
| **lm-evaluation-harness** (EleutherAI) | Few-shot benchmark harness (MMLU-style multiple-choice, QA, classification); custom JSONL tasks | **Yes** — built for local HF / local-server models | **Wrong shape for Layla.** It evaluates *base-model* capability on closed benchmarks, not *agent answer grounding* against retrieved context. Use only if you ever want to track raw model capability across model swaps. |
| **OpenAI evals-style golden set** | Hand-authored input → expected-criteria pairs, scored by code or a grader model | **Yes** (pattern, not a dependency) | This *pattern* is exactly the golden suite; promptfoo is the cleaner implementation of it. |

### Which run with NO LLM judge at all
- **promptfoo deterministic assertions**: `contains-all`, `regex`, `is-json`, `javascript`/`python` custom asserts, `similar` (local sentence-embedding cosine). Zero LLM calls.
- **MiniCheck / NLI models** (below): a small classifier, not a chat model — runs on CPU, no API.
- **Embedding cosine** answer-relevancy heuristic (below).

---

## 3. Grounding / RAG metrics that work offline with a tiny model

The key insight from the research: **faithfulness/grounding does not need a big LLM judge and does not need ground-truth answers.** It only needs `(answer, retrieved_context)` and an *entailment* check. Three families:

### (a) NLI-based grounding — RECOMMENDED for Layla's inline check
Treat each answer sentence as a *hypothesis* and the retrieved context as the *premise*; score entailment. Two strong, small, CPU-capable options:

- **MiniCheck** (EMNLP 2024, `Liyan06/MiniCheck`) — purpose-built sentence-level fact-checker against grounding documents.
  - `MiniCheck-Flan-T5-Large` is **770M**, runs on CPU, "reaches GPT-4 performance" on the LLM-AggreFact benchmark at ~400x lower cost; smaller `roberta-large` / `deberta-v3-large` options exist for even tighter footprints.
  - API:
    ```python
    from minicheck.minicheck import MiniCheck
    scorer = MiniCheck(model_name='flan-t5-large', cache_dir='./ckpts')
    pred_label, raw_prob, _, _ = scorer.score(docs=[context], claims=[answer_sentence])
    # pred_label: 1 = supported, 0 = unsupported;  raw_prob in [0,1]
    ```
  - Split the answer into sentences first (MiniCheck is sentence-level). `faithfulness = mean(pred_label over sentences)`; any sentence with `raw_prob` below threshold = an ungrounded claim to flag.
- **Generic NLI cross-encoder** (e.g. a DeBERTa-v3 MNLI model via `sentence-transformers` CrossEncoder) — same premise/hypothesis entailment idea, broader availability, no extra dependency if sentence-transformers is already in the stack. Slightly less accurate than MiniCheck for the fact-check task but a fine fallback.

Both are **reference-free** (no golden answer needed) — ideal for production gating where you only have the answer and the context Layla retrieved.

### (b) Answer-relevancy without a judge
Detect "answered a different question" / evasive non-answers cheaply:
- Embed the user question and the answer (Layla already has an embedding stack for Chroma/Qdrant). **Low cosine = off-topic / non-responsive.** This is the reference-free relevancy signal; it complements grounding (grounding catches *made-up*, relevancy catches *off-topic*).

### (c) Cite-or-abstain pattern
The literature is blunt: >95% of open-source-LLM RAG answers contain at least one unattributed sentence, and post-hoc citation still hallucinates. The robust pattern for a *small* local model:
1. Prompt the model to **cite the retrieved chunk id(s)** per claim, OR explicitly **abstain** ("I don't have grounding for this") when context is insufficient.
2. **Verify the citations with the NLI check above** — don't trust the model's self-citation. If a cited sentence isn't entailed by its cited chunk, treat it as ungrounded.
3. If grounding score is below threshold and the model didn't abstain → the gate fails the answer (or downgrades it to "low confidence / unverified").

This converts "cite or abstain" from a prompt suggestion into an *enforced* gate, which is what Layla currently lacks.

---

## 4. Golden-set regression suite (20-50 prompts, nightly CI, tiny model)

Use **promptfoo** as the runner. Structure:

- **`promptfooconfig.yaml`** with `providers:` pointing at Layla's local endpoint (llama-server / Ollama OpenAI-compatible URL — the same one in `litellm_gateway` / `inference_router`). No cloud provider configured.
- **20-50 test cases** in a `tests:` JSONL/YAML file, each = a prompt + scored expectations. Mix of:
  - **Deterministic asserts** (no LLM): `contains-all` for must-mention facts, `regex` for format, `is-json`, custom `python:` assert that calls the MiniCheck grounding scorer on `(output, provided_context)` and returns a 0-1 score.
  - **`similar`** (local embedding cosine) for "semantically close to this reference answer".
  - **Optional `llm-rubric`** pointed at the *local* model for fuzzy quality — but keep these few and never make them the sole gate, because a tiny judge is noisy.
- **Per-test `threshold`**: combined weighted assertion score must exceed it; promptfoo marks pass/fail and exits non-zero on failures.
- **Categories to cover**: factual-QA-with-context (grounding), off-topic-detection (relevancy), abstention-when-no-context, tool-result-summarization correctness, regression-prone prompts that previously broke.

**CI**: the **promptfoo GitHub Action** runs the suite. Two triggers — on PR (catch prompt/model-change regressions) and **nightly `schedule:`** (catch model drift / non-determinism). Cache the MiniCheck checkpoint and the GGUF model in the runner to keep it cheap. Because everything is local, the CI job needs CPU + the small models, no secrets.

Keep the suite **small and high-signal** — 20-50 curated cases that each encode a real failure mode beat hundreds of shallow ones, and they run fast enough for nightly on CPU.

---

## 5. Completion-gate improvement: beyond lexical checks

How others detect "wrong/ungrounded" answers, mapped onto `passes_completion_gate()`:

| Signal | How to add to Layla's gate | Cost |
|--------|----------------------------|------|
| **Grounding (NLI/MiniCheck)** | When the answer was produced with retrieved context (e.g. via `try_chroma_retrieval`), run MiniCheck over answer sentences vs. context; fail if mean-support < threshold (e.g. 0.6) and the model didn't abstain. New reason: `ungrounded(score=…)`. | ~770M CPU model, sub-second per short answer |
| **Answer-relevancy (embedding cosine)** | Fail/flag if cosine(question, answer) is very low → `non_responsive`. Reuses existing embedding stack. | negligible |
| **Self-consistency / abstention honored** | If context is empty/weak and the model produced confident claims instead of abstaining → flag. Pairs with the cite-or-abstain prompt. | free (logic) |
| **Atomic-claim count unsupported** | From MiniCheck per-sentence labels, count sentences with label 0; expose `unsupported_claims: N` in the trace for the UI / planner. | included above |

Keep it **layered, not blocking-by-default**: emit a structured `grounding` block in the outcome trace (alongside the existing `validation_matrix`) with `faithfulness`, `relevancy`, `unsupported_claims`, and a boolean `grounding_pass`. Gate hard only on a clear threshold breach for RAG answers; otherwise downgrade confidence (mirrors `api_confidence_heuristic` already multiplying score on weak signals). This matches the production pattern from research: *lightweight NLI checks online (gate), heavier LLM-judge eval offline (nightly suite)*.

---

## 6. Eval plan for Layla (concrete)

**Tool choice**
- **Grounding (inline):** MiniCheck (`flan-t5-large`, CPU) — or a DeBERTa-v3 MNLI cross-encoder via the existing sentence-transformers stack as a no-new-heavy-dep fallback.
- **Relevancy (inline):** embedding cosine using Layla's current embedder (Chroma/Qdrant stack).
- **Regression suite:** promptfoo, local provider = Layla's llama-server/Ollama endpoint, deterministic + `python:` (MiniCheck) + `similar` asserts; sparing local `llm-rubric`.
- **(Optional offline metrics):** DeepEval pytest tests for faithfulness/answer-relevancy in nightly only, judge = local model — for richer reporting, never as the inline gate.

**Metrics**
- `faithfulness` = mean MiniCheck support over answer sentences (reference-free, vs. retrieved context).
- `relevancy` = cosine(question, answer).
- `unsupported_claims` = count of non-entailed sentences.
- `grounding_pass` = `faithfulness >= 0.6 and (relevancy >= τ or context_empty_and_abstained)`.

**Where it runs**
- *Inline*: new module `agent/services/grounding_eval.py`, called from the completion path for answers that carried retrieved context (wire at the `try_chroma_retrieval` / autonomous aggregate seam and into `passes_completion_gate` via a new optional `context` arg). Lazy-import MiniCheck like litellm is lazy-imported; gate behind a config flag (`grounding_eval_enabled`, default off until tuned) consistent with existing `runtime_safety.load_config()` toggles.
- *CI*: promptfoo GitHub Action on PR + nightly `schedule:`, models cached on the runner.

**How it gates**
- Inline: for RAG/retrieval answers, hard-fail with reason `ungrounded(score=…)` / `non_responsive` on threshold breach; otherwise attach a `grounding` block to the outcome trace and multiply `api_confidence_heuristic` like other weak signals. Non-RAG answers are unaffected (no context → no grounding gate, only the abstention check).
- CI: promptfoo per-test `threshold`; suite exits non-zero → build fails. Nightly run posts a drift report.

**Suggested rollout order**
1. Add `grounding_eval.py` + MiniCheck/NLI, expose metrics in the trace **without** gating (observe-only). Add pytest unit tests (the repo already has `test_completion_gate.py` to extend).
2. Stand up the 20-50-prompt promptfoo suite + nightly CI against the local model.
3. Once thresholds are calibrated on real traces, flip `grounding_eval_enabled` to gate RAG answers in the completion gate.

---

## Sources

- promptfoo — [LLM Rubric (judge config / local provider)](https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/llm-rubric/), [Assertions & metrics](https://www.promptfoo.dev/docs/configuration/expected-outputs/), [GitHub Action](https://github.com/promptfoo/promptfoo-action), [GitHub Actions integration](https://www.promptfoo.dev/docs/integrations/github-action/), [CI/CD integration](https://www.promptfoo.dev/docs/integrations/ci-cd/)
- DeepEval — [GitHub](https://github.com/confident-ai/deepeval), [Faithfulness metric](https://deepeval.com/docs/metrics-faithfulness), [Metrics intro](https://deepeval.com/docs/metrics-introduction), [RAGAS metrics in DeepEval](https://deepeval.com/docs/metrics-ragas)
- Ragas vs DeepEval — [comparison](https://medium.com/@sjha979/ragas-vs-deepeval-measuring-faithfulness-and-response-relevancy-in-rag-evaluation-2b3a9984bc77), [Confident AI RAG metrics](https://www.confident-ai.com/blog/rag-evaluation-metrics-answer-relevancy-faithfulness-and-more)
- lm-evaluation-harness — [EleutherAI GitHub](https://github.com/EleutherAI/lm-evaluation-harness), [model guide](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/model_guide.md)
- MiniCheck — [GitHub / README](https://github.com/Liyan06/MiniCheck), [Flan-T5-Large model card](https://huggingface.co/lytang/MiniCheck-Flan-T5-Large), [paper (arXiv:2404.10774)](https://arxiv.org/abs/2404.10774)
- NLI-based faithfulness — [123ofAI: NLI hallucination detection](https://123ofai.com/qnalab/system-design/blocks/faithfulness), [Benchmarking LLM Faithfulness in RAG (arXiv:2505.04847)](https://arxiv.org/pdf/2505.04847)
- Cite-or-abstain / attribution — [Grounded attributions & learning to refuse (arXiv:2409.11242)](https://arxiv.org/pdf/2409.11242), [Why citation-based RAG still hallucinates](https://yaihq.com/research/citation-based-rag-still-hallucinates)
- Reference-free relevancy / RAG eval — [Evidently AI: RAG evaluation guide](https://www.evidentlyai.com/llm-guide/rag-evaluation), [Deepchecks: answer relevancy / faithfulness](https://deepchecks.com/rag-evaluation-metrics-answer-relevancy-faithfulness-accuracy/)
- Golden-set regression in CI — [Promptfoo unit-testing guide](https://www.mager.co/blog/2026-02-23-promptfoo-llm-validation), [Testing AI agents in CI (golden traces)](https://medium.com/@meryemmsakinn/end-vibe-driven-development-testing-ai-agents-in-ci-pipelines-promptfoo-golden-traces-b9b222b23d72)

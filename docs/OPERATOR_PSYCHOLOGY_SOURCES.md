# Operator psychology / behavior sources — reconsideration guide

**Purpose:** Choose how Layla uses psychology-informed material for **collaboration, reflection, and communication** — not clinical assessment. All use must align with [`ETHICAL_AI_PRINCIPLES.md`](ETHICAL_AI_PRINCIPLES.md) §11 (no diagnostic labels, no DSM/ICD as identity).

---

## Tier A — Already in the repo (recommended first)

No extra pip packages. Enable via `runtime_config.json` and/or rely on Chroma + `knowledge/`.

| Asset | Role | How it reaches the model |
|--------|------|---------------------------|
| [`knowledge/echo-psychology-frameworks.md`](../knowledge/echo-psychology-frameworks.md) | CBT, DBT, IFS, polyvagal, Johari, guardrails | RAG when `use_chroma` + reflective/research-style goals (`_needs_knowledge_rag` in `agent_loop.py`); `priority: core` |
| [`knowledge/echo-behavioral-patterns.md`](../knowledge/echo-behavioral-patterns.md) | Habits, work cognition, Zeigarnik, planning fallacy | Same RAG path; `domain: behavioral-patterns` |
| [`knowledge/cassandra-cognitive-biases.md`](../knowledge/cassandra-cognitive-biases.md) | System 1/2, heuristics, biases (for *reasoning hygiene*) | RAG; Cassandra aspect in front matter |
| [`agent/cognitive_lens.txt`](../agent/cognitive_lens.txt) | Short lens roster (Carpenter, Assembly, …) | `enable_cognitive_lens: true` → injected in `_build_system_head` |
| [`agent/behavioral_rhythm.txt`](../agent/behavioral_rhythm.txt) | Optional rhythm copy | `enable_behavioral_rhythm: true` |
| [`agent/lens_knowledge/*.md`](../agent/lens_knowledge/) | Per-lens summaries | `enable_lens_knowledge: true` |
| `direct_feedback_enabled`, `pin_psychology_framework_excerpt` | Blunt collaboration + Echo/Lilith pin | See [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) |
| `style_profile` key **`collaboration`** | Heuristic pace/directness (non-clinical) | `enable_style_profile: true`; `services/style_profile.py` |

**Verdict:** Prefer tuning **these** and operator-written `knowledge/*.md` before adding libraries.

---

## Tier B — Optional local knowledge (operator-owned)

Add under repo `knowledge/` (usually gitignored). Re-index when Chroma is on. See [RUNBOOKS.md — Operator-local psychology texts](RUNBOOKS.md#operator-local-psychology-texts-copyright--ethics).

**Fits non-clinical “read the operator” goals:**

- **Communication / org psychology** (your summaries): feedback styles, psychological safety, clarity, async norms.
- **Motivational interviewing** (principles only): open questions, affirmations, reflections — *not* as therapy for a patient.
- **Big Five / OCEAN** as *vocabulary for preferences* (“tends detail-oriented / abstract”) — never as fixed clinical trait scores inferred from chat.
- **HCI / cognitive load** for tooling and explanation depth (Sweller-style, chunking) — engineering companion angle.

**Poor fit or high risk:**

- Pasting **DSM/ICD criteria** or proprietary manuals into the repo (copyright + misuse for “diagnosis”).
- Any corpus whose purpose is **automated personality classification** from user text.

---

## Tier C — Optional Python libraries (generally *not* required)

Layla already has **sentence-transformers**, **Chroma**, **keybert**, and LLM reasoning. Extra “psych” packages rarely improve *ethical* collaboration and often encourage **labeling**.

| Idea | Example stacks | Recommendation |
|------|----------------|----------------|
| Readability / length | `textstat`, simple Flesch-style | **Optional** only if you add a small internal tool to suggest “simpler wording” — **do not** use scores to classify the person. |
| Sentiment | `vaderSentiment`, `TextBlob` | **Discouraged for operator modeling** — coarse, gameable, risks stereotyping. If used at all: aggregate diagnostics on *assistant* copy quality, not user profiling. |
| Deep NLP pipelines | `spacy` + large models | **Heavy**; little unique value vs LLM + RAG for this use case. |
| “Personality from text” / psychometrics APIs | various | **Do not integrate** for operator-facing diagnosis or storage of labels. |

If you add an optional dependency for experiments, keep it **out of** default `requirements.txt`; document in a comment block or `requirements-psych-optional.txt` (new file only if you want — simplest is to **document only** without new file unless user insists).

---

## Tier D — Research tools (Nyx / evidence), not profiling

- [`knowledge/nyx-research-databases.md`](../knowledge/nyx-research-databases.md) — PubMed, trials, etc., for **factual research**.
- arXiv / web search in tools — for **topics**, not for scoring the operator’s psyche.

Use these to **ground claims** in general science, not to infer private mental-health status.

---

## Configuration checklist (behavioral depth without new deps)

1. `use_chroma: true` and curated `knowledge/*.md` with clear front matter.
2. Turn on **`enable_style_profile`** if you want **`collaboration`** snapshots.
3. Optionally enable **`enable_cognitive_lens`**, **`enable_behavioral_rhythm`**, **`enable_lens_knowledge`** if the text files are maintained.
4. Set **`direct_feedback_enabled`** if you want explicit blunt collaboration (still non-clinical).
5. Keep **`pin_psychology_framework_excerpt`** on for Echo/Lilith unless token budget is too tight.

---

## Summary

- **Best ROI:** committed + local `knowledge/` docs, existing Echo/Cassandra references, config flags above, and `collaboration` style profile.
- **Libraries:** default stance is **none** for “psychology of the user”; optional readability tools only for **text quality**, not identity inference.
- **Research:** Nyx stack for **world** knowledge, not **operator diagnosis**.

For ethics and crisis wording, always cross-check [`ETHICAL_AI_PRINCIPLES.md`](ETHICAL_AI_PRINCIPLES.md) §11 and [`knowledge/echo-psychology-frameworks.md`](../knowledge/echo-psychology-frameworks.md).

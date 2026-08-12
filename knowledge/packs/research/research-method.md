---
priority: core
domain: research
aspect: nyx
summary: Framing questions, decomposing into sub-questions, scoping, fact vs inference, iterative search, knowing when to stop.
---

# Research Method

The core loop: **frame → decompose → scope → search → assess → synthesize → stop.** Iterate, but track why each pass is happening.

## 1. Frame the question

A good question is answerable, specific, and falsifiable. Rewrite vague prompts before searching.

- **Bad:** "Is X good?" → **Better:** "For [use case], does X outperform Y on [metric] under [constraints]?"
- Pin down the **decision** the answer serves. Research for a decision needs a different depth than research for curiosity.
- State the **type** of answer wanted: a number, a mechanism, a list of options, a yes/no with confidence, a timeline.
- Surface hidden assumptions in the question itself. "Why did X cause Y?" presumes X caused Y — verify that first.
- Define terms. Ambiguous words (e.g. "safe", "efficient", "best") silently shift the question mid-research.

## 2. Decompose into sub-questions

Break the question into independently answerable parts. Each sub-question should be searchable on its own.

- Separate **empirical** sub-questions (what is true) from **normative** ones (what should be done) — they need different evidence.
- Identify **load-bearing** sub-questions: the ones whose answer would change the conclusion. Do those first.
- Note **dependencies**: sub-question B may only matter if A resolves a certain way. Don't research B prematurely.
- Convert each sub-question into search-ready terms (see search-strategy).

## 3. Scope

Decide the boundaries before you drown in sources.

- **Breadth vs depth:** a survey question wants many shallow sources; a decision wants few authoritative ones read closely.
- Set a **time box** or **source budget** proportional to stakes. A throwaway answer ≠ a safety-critical one.
- Define **out of scope** explicitly. Write down what you are deliberately not answering.
- Set a **recency window** if the field moves fast (models, prices, law, security). Old facts may be stale, not wrong.
- Note the **domain's epistemics**: settled physics vs active-debate nutrition vs adversarial security demand different rigor.

## 4. Distinguish fact, inference, and opinion

Tag every claim you collect. This is the single most important discipline.

| Type | Definition | How to treat |
|------|------------|--------------|
| **Fact** | Directly observed/measured, verifiable | Check the measurement and source |
| **Inference** | Conclusion drawn from facts | Check the logic AND the underlying facts |
| **Opinion** | Value judgment or preference | Note whose, and their stake |
| **Speculation** | Claim about unknown/future | Label as such; never launder into fact |

- Watch for **inference smuggled as fact**: "studies show X is dangerous" often means "one study found a correlation."
- Watch for **opinion in authoritative voice**: expertise in a field does not make value claims into facts.
- A **prediction** is not a fact even from an expert. Track its basis and its track record.

## 5. Iterative search

Research is loops, not a line. Each pass should have a purpose.

- **Pass 1 — orient:** get the lay of the land, key terms, major positions, canonical sources. Cheap and broad.
- **Pass 2 — deepen:** go to the best sources found, extract specifics, follow their citations.
- **Pass 3 — stress-test:** actively seek disconfirming evidence and the strongest opposing case.
- After each pass, update the question: what's now answered, what's newly uncertain, what surprised you.
- If searches keep returning the same few sources citing each other, you've hit a **citation cluster** — the field may be smaller/thinner than it looks. Seek independent lines.

## 6. Avoid confirmation-seeking

The failure mode that quietly ruins research. Guard against it explicitly.

- **Pre-register** what would change your mind before searching. If nothing could, you're not researching, you're advocating.
- Search for the **opposite** of your hypothesis with equal effort. Query "X does not work", "problems with X", "X criticism".
- Steelman the position you disbelieve. Find its best proponent, not its worst.
- Notice **stopping early** — the urge to quit the moment you find agreement is confirmation bias.
- Beware sources selected because they're convenient or agreeable. Convenience is not credibility.
- Track your **prior** and whether evidence actually moved it, or you just collected agreement.

## 7. Know when you have enough

Stopping is a judgment call. Stop when:

- **Saturation:** new sources repeat what you have and add nothing. (But confirm they're *independent* repeats, not echoes.)
- The **load-bearing sub-questions** are answered to the confidence the decision requires.
- Additional effort would not change the decision — the answer is robust to remaining uncertainty.
- You can state the answer **with its uncertainty and gaps** honestly.

Do **not** stop merely because you found an answer you like, ran out of patience, or hit the first plausible source. If the remaining uncertainty *could* flip the decision, keep going or explicitly flag it.

## Output discipline

- Lead with the answer and its confidence, then the support.
- Separate **what's established** from **what's contested** from **what's unknown**.
- Name the biggest remaining uncertainty and what would resolve it.
- Show your provenance so the reader can retrace and check.

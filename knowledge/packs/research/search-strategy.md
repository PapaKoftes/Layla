---
priority: support
domain: research
aspect: nyx
summary: Query craft, operators, synonyms, following citations, multiple angles, paywalls/preprints, primary vs summary.
---

# Search Strategy

Search is a craft. The goal is not "find a page" but "efficiently locate the strongest evidence and its counter-evidence."

## Query craft

Start broad to learn vocabulary, then narrow with the terms the field actually uses.

- **Orient first:** a loose query reveals the domain's jargon, key names, and canonical works. Harvest those terms for round two.
- **Use the field's language.** Practitioners and papers use specific terms; lay phrasing misses the best sources.
- **Vary specificity:** if too many results, add constraints; if too few, drop or generalize terms.
- **Synonyms & variants:** try alternate spellings, acronyms and their expansions, older vs newer names for the same concept, and adjacent disciplines' terms for the same idea.
- **One concept per query first**, then combine once you know each returns good results.

## Operators (portable across most engines)

- **`"exact phrase"`** — force multi-word terms to stay together.
- **`-term`** — exclude a sense you don't want (disambiguate homonyms).
- **`site:`** — restrict to a domain (a journal, a standards body, a docs site).
- **`filetype:`** — find PDFs (papers, reports, spec sheets), datasets (csv/xlsx).
- **`OR`** — capture synonyms in one query: `(termA OR termB) context`.
- **`intitle:` / `inurl:`** — require the term in prominent position for higher-relevance hits.
- **Date filters** — constrain to a recency window for fast-moving topics; widen for foundational work.
- Operator support varies by engine and degrades over time — verify behavior rather than assuming.

## Narrowing and broadening (deliberately)

- **Too broad / noisy:** add domain terms, use phrases, exclude the wrong sense, restrict site/date.
- **Too narrow / empty:** drop the most specific word, generalize the concept, try synonyms, remove filters, search the parent topic.
- If a query returns junk, **change the terms, not just the page number.** Page 2 is rarely the fix.

## Following citations (backward and forward)

Citation trails are often faster than search.

- **Backward (cited-by-this):** read a good source's references to find the primary sources and prior art it rests on. Trace claims to origin.
- **Forward (cites-this):** find newer work that cites a key paper — reveals replications, refutations, extensions, and current consensus.
- **Snowball:** one authoritative source's bibliography can seed an entire literature. Look for review/survey articles — they're citation goldmines.
- Note **who cites whom**: a tight self-citing cluster may signal a niche or an echo chamber; broad independent citation signals robustness.

## Multiple angles

Never rely on one search path.

- Attack from different framings: the problem, the solution, the mechanism, the critique, the application.
- Search for the **counter-position** deliberately: "limitations of", "criticism of", "failed to replicate", "problems with".
- Try different **source types**: papers, reviews, standards, docs, practitioner writeups, datasets — each surfaces different truths.
- Search in the **communities** where the topic lives (specialist forums, official docs, regulatory filings), not just the open web.

## Paywalls and preprints

- **Paywalled paper:** look for an author-hosted copy, a preprint version, an institutional repository copy, or the accepted manuscript. The abstract + methods often suffice to judge relevance before committing.
- **Preprints:** valuable for recency but **not peer-reviewed** — treat findings as provisional. Check whether a peer-reviewed version later appeared and whether conclusions changed.
- **Don't cite the press release** when the paper is available — releases overstate. Get the paper.
- If you can only access a summary, say so and flag that you did not verify against the primary.

## Primary literature vs summaries — when to go where

**Use summaries/secondary** when:
- Orienting in an unfamiliar field.
- The claim is settled, uncontested, and low-stakes.
- You need context, history, or a map of positions.

**Go to primary** when:
- The claim is **load-bearing** for a decision.
- The claim is **contested** or surprising.
- Summaries disagree, or a summary's claim seems too strong.
- You need exact numbers, methods, or the precise wording (law, spec, data).
- The stakes are high enough that a misread summary would be costly.

## Efficiency habits

- Skim abstract → methods → limitations → results, in that order, to judge relevance fast.
- Keep a running list of terms, key sources, and dead ends so you don't re-search the same ground.
- Timebox each search thread; if a thread stops yielding, switch angles rather than grinding.

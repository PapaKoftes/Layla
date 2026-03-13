---
priority: core
domain: research-methods
aspect: nyx
---

# Research Methods & Tools — Nyx's Complete Reference

Systematic methods for finding, evaluating, and synthesizing knowledge. The difference between knowing how to Google and actually knowing how to research.

---

## Academic Search — Operators and Databases

### Google Scholar operators
```
"exact phrase"               # phrase match
author:feynman               # author filter
site:arxiv.org               # domain filter
filetype:pdf                 # file type
intitle:neural               # term in title
after:2022 before:2024       # date range
related:doi.org/10.xxx       # related papers
```

### Semantic Scholar
- `semanticscholar.org` — free, AI-enhanced, citation graphs
- Open API: `api.semanticscholar.org/graph/v1/paper/search?query=...`
- Shows citation counts, influential citations, open access PDFs
- Recommends related papers based on semantic similarity

### arXiv
- Preprints in CS, physics, math, biology, economics
- Search at `arxiv.org/search/` or `arxiv.org/find/`
- Categories: cs.AI, cs.LG (machine learning), cs.CV, quant-ph, math.CO
- API: `export.arxiv.org/api/query?search_query=ti:transformer&max_results=10`
- Every paper has a stable ID: `arxiv.org/abs/2303.08774`

### PubMed / MEDLINE
- Biomedical and life sciences; authoritative for health/psychology
- MeSH terms (Medical Subject Headings) make searches precise
- Filters: Publication Type (Review, Clinical Trial, Meta-Analysis), Dates, Species

### JSTOR / ACM Digital Library / IEEE Xplore
- JSTOR: humanities, social sciences, older journals
- ACM: computing, software engineering
- IEEE: electrical engineering, electronics, applied CS

### Google Dataset Search
- `datasetsearch.research.google.com` — for finding raw data
- Also: `kaggle.com/datasets`, `huggingface.co/datasets`, `paperswithcode.com/datasets`

---

## Boolean Search Logic

```
term1 AND term2     # both required (default for most engines)
term1 OR term2      # either
NOT term            # exclude
(A OR B) AND C      # grouping
"exact phrase"      # phrase matching
term*               # wildcard (prefix matching on many systems)
term~1              # fuzzy match (1 edit distance, in some systems)
```

**Effective query construction:**
1. Start with the core concept in 2-3 terms
2. Identify synonyms and variants for each term
3. Build: `(term1 OR synonym1) AND (term2 OR synonym2) AND (constraint)`
4. If too many results: add AND constraints
5. If too few: replace AND with OR, remove constraints, broaden synonyms

---

## Statistics — Methods Reference

### Descriptive statistics
- **Mean** (average): sensitive to outliers
- **Median**: middle value; better for skewed distributions
- **Mode**: most frequent value
- **Standard deviation (σ)**: average distance from mean; ≈68% within ±1σ for normal distribution
- **IQR** (interquartile range): Q3 - Q1; robust to outliers
- **Skewness**: asymmetry of distribution (right-skewed = long tail right)
- **Kurtosis**: tail heaviness; high kurtosis = more extreme outliers

### Probability distributions
| Distribution | When to use |
|---|---|
| Normal (Gaussian) | Many natural phenomena, CLT applies |
| Binomial | Counting successes in N binary trials |
| Poisson | Count of events in fixed time/space |
| Exponential | Time between events (memoryless) |
| Uniform | Equal probability over range |
| Beta | Probability of probabilities (0-1 bounded) |
| Pareto | Power law phenomena (80/20 rule) |

### Hypothesis testing
1. **State null hypothesis H₀** (no effect, no difference)
2. **Choose significance level α** (typically 0.05 = 5% false positive rate)
3. **Choose test** based on data type and distribution
4. **Compute test statistic** and **p-value**
5. **Interpret**: if p < α, reject H₀ (not "prove H₁")

**Common tests:**
| Test | When to use |
|------|-------------|
| t-test (independent) | Compare means of two groups |
| t-test (paired) | Before/after on same subjects |
| ANOVA | Compare means of 3+ groups |
| Chi-square | Categorical data, independence test |
| Mann-Whitney U | Non-parametric alternative to t-test |
| Pearson correlation | Linear relationship between continuous variables |
| Spearman correlation | Monotonic relationship, non-parametric |
| Fisher's exact test | Small sample categorical data |

**p-value misinterpretations:**
- p-value is NOT the probability the null hypothesis is true
- p-value is NOT the probability the result is a false positive
- p-value IS the probability of getting results at least as extreme as observed, assuming H₀ is true
- Statistical significance ≠ practical significance (effect size matters)

### Effect sizes
| Measure | Context | Interpretation |
|---------|---------|----------------|
| Cohen's d | Mean difference | 0.2 = small, 0.5 = medium, 0.8 = large |
| r (correlation) | Correlation | 0.1 = small, 0.3 = medium, 0.5 = large |
| η² (eta²) | ANOVA | Proportion of variance explained |
| Odds Ratio | Categorical/clinical | OR=2 means 2× more likely |
| Number Needed to Treat | Clinical | N patients for 1 additional benefit |

### Bayesian inference basics
```
P(H|D) = P(D|H) × P(H) / P(D)
posterior = likelihood × prior / marginal likelihood

# Updating beliefs:
# Prior: what we believed before the data
# Likelihood: how probable is the data given the hypothesis
# Posterior: updated belief after seeing the data
```
Key advantage over frequentist: quantifies uncertainty about hypotheses directly, can incorporate prior knowledge, handles small samples better.

---

## Meta-Analysis & Systematic Review

### Process
1. **Registration**: pre-register the review protocol (PROSPERO database)
2. **Search**: systematic search of multiple databases with documented query
3. **Screening**: title/abstract → full text, with inclusion/exclusion criteria
4. **Data extraction**: standardized form for each included study
5. **Quality assessment**: risk of bias tools (Cochrane RoB, Newcastle-Ottawa)
6. **Synthesis**: narrative (when heterogeneous) or meta-analysis (when homogeneous)
7. **GRADE**: rate certainty of evidence

### Effect size pooling in meta-analysis
- Fixed-effects model: assumes all studies estimate same true effect (homogeneous population)
- Random-effects model: assumes studies estimate different but related true effects (appropriate when populations differ)
- Heterogeneity: I² statistic (0-100%; >75% = substantial; suggests random-effects or meta-regression)
- Funnel plot: check for publication bias (asymmetry suggests smaller negative studies weren't published)

### Quality of evidence hierarchy (GRADE)
1. Systematic reviews / RCTs (highest)
2. Non-randomized controlled studies
3. Cohort studies
4. Case-control studies
5. Cross-sectional studies
6. Case series / expert opinion (lowest)

---

## Critical Appraisal Framework

For any empirical paper, ask:
1. **What was the research question?** Is it clearly defined and answerable?
2. **What was the study design?** Is it appropriate for the question?
3. **How was the sample selected?** Is it representative? What are the selection biases?
4. **What was measured and how?** Are the measurements valid and reliable?
5. **What were the confounders?** Were they controlled?
6. **What were the results?** Magnitude + direction + confidence interval
7. **Are the conclusions supported by the results?** Watch for overclaiming
8. **Who funded it?** Does funding source create conflicts of interest?
9. **Can it be replicated?** Is enough detail provided?
10. **What's the generalizability?** To whom do results apply?

**Common research biases:**
- **Selection bias**: sample doesn't represent target population
- **Confirmation bias**: seeking only supportive evidence
- **Publication bias**: negative results don't get published
- **Measurement bias**: systematic error in how outcome was measured
- **Recall bias**: participants remember exposures differently based on outcome
- **Attrition bias**: differential dropout in RCTs
- **Hawthorne effect**: behavior changes when being observed
- **Lead time bias**: screening detects disease earlier, appears to improve survival

---

## Data Analysis Methods

### Exploratory Data Analysis (EDA) workflow
```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("data.csv")
df.head()           # first rows
df.info()           # dtypes, non-null counts
df.describe()       # count, mean, std, min, quartiles, max
df.isnull().sum()   # missing values per column
df.nunique()        # unique values per column

# Distribution
df["column"].hist(bins=30)
df["column"].value_counts(normalize=True)  # proportions

# Correlations
df.corr()           # Pearson correlation matrix
df.corr("spearman") # Spearman (rank-based)

# Group analysis
df.groupby("category")["value"].agg(["mean","std","count"])
```

### Text analysis tools
- **TF-IDF**: term frequency × inverse document frequency — identifies important terms
- **LDA (Latent Dirichlet Allocation)**: topic modeling — finds latent topics in documents
- **Cosine similarity**: measures similarity between document vectors (0=orthogonal, 1=identical)
- **BERT embeddings**: semantic similarity that handles synonyms and context

### Network analysis
```python
import networkx as nx
G = nx.DiGraph()
G.add_edge("paper_A", "paper_B")  # citation
nx.degree_centrality(G)            # how many connections
nx.betweenness_centrality(G)       # how many shortest paths pass through
nx.pagerank(G)                     # importance by citation quality
nx.community.greedy_modularity_communities(G)  # detect communities
```

---

## Reference Management

**Formats:**
- **BibTeX** (`.bib`): used by LaTeX, exported by most databases
- **RIS**: universal format, imported by Zotero/Mendeley/EndNote
- **CSL-JSON**: JSON-based, used by Pandoc and modern tools

**Citation styles:**
- **APA** (Psychology): Author, A. A. (Year). Title. Journal, vol(issue), pages. DOI
- **Chicago**: Two systems — author-date (sciences) and notes-bibliography (humanities)
- **IEEE**: [1] A. Author, "Title," Journal, vol. X, no. Y, pp. Z-Z, Year
- **Vancouver**: Numbered in order of appearance; used in medicine

**Zotero as research infrastructure:**
- Browser connector saves papers with one click
- Groups for collaborative bibliography
- RSS feeds from journals — automatic new paper tracking
- Better BibTeX plugin for LaTeX integration
- ZotFile for automatic PDF renaming and organization

"""Inline RAG grounding — cite-or-abstain over retrieved context (BL-100 / REQ-30).

Given a generated answer and the passages it was meant to be grounded in, score each claim
(sentence) for support against those passages and produce a `grounding` block: which claims
are supported (with the best-matching source), which are unsupported, an overall score, and
an optional abstain recommendation. This is the #1 correctness lever — it turns confident
hallucinations into either a citation or an "I don't know from what I have".

Scoring is PLUGGABLE. The default is a model-free lexical scorer (content-token containment)
— CPU, deterministic, zero-dep — which reliably catches claims with NO support in the context
(the dominant hallucination signal). Plug an NLI / MiniCheck entailment model via `set_scorer`
for higher precision on paraphrase when a model is available; the pipeline is unchanged.

Deliberately non-invasive: `check_grounding` is pure (answer + passages + cfg → dict). Wiring
it into the live answer path is gated by `grounding_enabled` so it can be measured before it
changes any behavior.
"""
from __future__ import annotations

import re
from typing import Callable

# A scorer maps (claim, [passages]) → (support in [0,1], best_passage_index or -1).
Scorer = Callable[[str, list[str]], "tuple[float, int]"]

_STOPWORDS = frozenset(
    "a an the is are was were be been being of to in on at for and or but if then else with "
    "as by from into over under this that these those it its it's you your i we they he she "
    "do does did done has have had will would can could should may might must not no yes "
    "there here their our his her them us me my mine ours yours what which who whom whose "
    "how when where why than too very just also about above below up down out off".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]*")
# Sentence splitter: break on . ! ? followed by space+capital/quote/digit; keep it simple and
# robust rather than perfect (grounding operates per-sentence, small mis-splits are harmless).
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def _content_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall(text or ""):
        # Keep internal punctuation (llama.cpp, file.py) but strip trailing/leading dots/commas
        # so a sentence-final "Paris." matches "Paris" in a passage.
        t = raw.strip("._/+-").lower()
        if len(t) > 1 and t not in _STOPWORDS:
            out.add(t)
    return out


def split_claims(answer: str) -> list[str]:
    """Split an answer into candidate factual claims (sentences), skipping the parts that
    aren't groundable assertions: questions, code/fences, list bullets w/o content, greetings."""
    if not answer or not answer.strip():
        return []
    # Drop fenced code blocks — they aren't prose claims to ground.
    text = re.sub(r"```.*?```", " ", answer, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", " ", text)
    claims: list[str] = []
    for raw in _SENT_SPLIT.split(text.replace("\n", " ")):
        s = raw.strip(" \t-*•").strip()
        if not s:
            continue
        if s.endswith("?"):            # questions aren't assertions
            continue
        if len(_content_tokens(s)) < 2:  # too short / no substantive content to ground
            continue
        claims.append(s)
    return claims


def lexical_scorer(claim: str, passages: list[str]) -> "tuple[float, int]":
    """Model-free support: fraction of the claim's content tokens present in the best passage.
    Deterministic and cheap; catches zero-support (hallucinated) claims well. Returns (0, -1)
    when there are no passages or the claim has no content tokens."""
    ctoks = _content_tokens(claim)
    if not ctoks or not passages:
        return 0.0, -1
    best_score, best_idx = 0.0, -1
    for i, p in enumerate(passages):
        ptoks = _content_tokens(p)
        if not ptoks:
            continue
        overlap = len(ctoks & ptoks) / len(ctoks)
        if overlap > best_score:
            best_score, best_idx = overlap, i
    return best_score, best_idx


_scorer: Scorer = lexical_scorer


def set_scorer(fn: Scorer) -> None:
    """Install an entailment-grade scorer (e.g. NLI / MiniCheck). fn(claim, passages) → (score, idx)."""
    global _scorer
    _scorer = fn or lexical_scorer


def reset_scorer() -> None:
    global _scorer
    _scorer = lexical_scorer


def check_grounding(answer: str, passages: list[str], cfg: dict | None = None) -> dict:
    """Score *answer*'s claims against *passages* and return a grounding block.

    Returns a dict:
      {enabled, overall, supported, unsupported: [{claim, score}],
       claims: [{text, supported, score, source}], abstain, mode}
    `overall` is the fraction of substantive claims that are supported (1.0 if there are none).
    `abstain` is True only in mode="abstain" when a substantive claim is unsupported.
    """
    cfg = cfg or {}
    mode = str(cfg.get("grounding_mode", "flag")).lower()  # off | flag | abstain
    if mode == "off" or not cfg.get("grounding_enabled", False):
        return {"enabled": False, "overall": 1.0, "supported": 0, "unsupported": [], "claims": [], "abstain": False, "mode": mode}

    min_support = float(cfg.get("grounding_min_support", 0.35))
    passages = [p for p in (passages or []) if isinstance(p, str) and p.strip()]
    claims = split_claims(answer)

    verdicts: list[dict] = []
    unsupported: list[dict] = []
    supported_n = 0
    for c in claims:
        score, idx = _scorer(c, passages)
        ok = score >= min_support
        verdicts.append({"text": c, "supported": ok, "score": round(score, 3), "source": idx})
        if ok:
            supported_n += 1
        else:
            unsupported.append({"claim": c, "score": round(score, 3)})

    n = len(claims)
    overall = 1.0 if n == 0 else supported_n / n
    abstain = mode == "abstain" and len(unsupported) > 0 and n > 0
    return {
        "enabled": True,
        "overall": round(overall, 3),
        "supported": supported_n,
        "unsupported": unsupported,
        "claims": verdicts,
        "abstain": abstain,
        "mode": mode,
    }


def should_abstain(grounding: dict) -> bool:
    """Whether the caller should abstain / hedge rather than assert an ungrounded answer."""
    return bool(grounding and grounding.get("enabled") and grounding.get("abstain"))


def ground_answer(answer: str, query: str, cfg: dict | None = None, *, k: int = 5, aspect_id: str = "") -> dict:
    """One-call integration for the answer path: pull the retrieved passages for *query* from
    the knowledge store and ground *answer* against them, mapping each claim's source index to
    the real source path for citation. Inert + zero-cost (no retrieval) when grounding is off,
    so this is safe to call unconditionally from the reasoning handler.
    """
    cfg = cfg or {}
    mode = str(cfg.get("grounding_mode", "flag")).lower()
    if mode == "off" or not cfg.get("grounding_enabled", False):
        return {"enabled": False, "overall": 1.0, "supported": 0, "unsupported": [], "claims": [], "abstain": False, "mode": mode}
    try:
        from layla.memory.vector_store import get_knowledge_chunks_with_sources
        chunks = get_knowledge_chunks_with_sources(query, k=k, aspect_id=aspect_id) or []
    except Exception:
        chunks = []
    passages = [str(c.get("text", "")) for c in chunks]
    sources = [str(c.get("source", "")) for c in chunks]
    result = check_grounding(answer, passages, cfg)
    # Replace the source INDEX with the real source path for each supported claim.
    for claim in result.get("claims", []):
        idx = claim.get("source", -1)
        claim["source"] = sources[idx] if isinstance(idx, int) and 0 <= idx < len(sources) else ""
    return result

"""
Learning quality filter. Reject low-quality entries before saving.
Reject: length < 40, uncertainty phrases. If >300 chars, summarize before storing.
"""

UNCERTAINTY_PHRASES = frozenset((
    "maybe", "not sure", "uncertain", "i think", "perhaps",
    "might be", "could be", "possibly", "i don't know",
))
MIN_LENGTH = 40
MAX_LENGTH_BEFORE_SUMMARIZE = 300


def filter_learning(content: str, summarize_fn=None, min_length: int | None = None) -> tuple[bool, str, str]:
    """
    Check if learning passes quality filter.
    Returns (pass, filtered_content, rejection_reason).
    If pass is True, filtered_content is the content to store (possibly summarized).

    min_length: override the 40-char floor. That floor is a PROXY for "is this worth
    keeping", calibrated against an extractor that guessed at insights in the assistant's
    prose. A subject-verified operator fact carries a DIRECT signal of worth, so the proxy
    is obsolete for it — and at 40 the choke point silently ate the single most valuable
    row type in the store ('Operator preference: I prefer tea' is 33 chars → too_short_33).
    Default None keeps 40 for every existing writer: this widens nothing by accident.
    """
    if not content or not isinstance(content, str):
        return False, "", "empty_or_invalid"
    c = content.strip()
    floor = MIN_LENGTH if min_length is None else max(1, int(min_length))
    if len(c) < floor:
        return False, "", f"too_short_{len(c)}"
    lower = c.lower()
    lower_opening = lower[:60]
    for phrase in UNCERTAINTY_PHRASES:
        # Reject hedged statements only when they appear in the opening clause,
        # not when factual content later contains words like "might".
        if phrase in lower_opening:
            return False, "", "uncertainty_phrase"
    if len(c) > MAX_LENGTH_BEFORE_SUMMARIZE and summarize_fn:
        try:
            summary = summarize_fn(c)
            if summary and len(summary.strip()) >= MIN_LENGTH:
                return True, summary.strip()[:800], ""
        except Exception:
            pass
    return True, c[:800], ""

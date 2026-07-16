"""Layla's own system prompt must never be stored as something she "learned".

Observed live: 4 of 32 rows in the operator's learnings table were verbatim system-prompt text or
internal prompt-context blocks — e.g. a byte-exact copy of a system_head_builder line
("This is a written TEXT chat: you are typing, not speaking…") and the KG block header
("Knowledge graph associations: ValueError; Hello.; …").

Why it mattered beyond noise — the loop was already CLOSED, with physical evidence:
    learning -> knowledge-graph node -> "Knowledge graph associations:" block in the next prompt
    -> the 3B model regurgitates it -> extracted as a new learning -> its tokens spawn new nodes
Graph nodes 'ValueError', 'Hello.', 'TEXT' and 'talking' were harvested from the bleed rows
themselves. Left alone, Layla's memory fills with her own instructions and crowds out real knowledge.

Two layers, tested here:
  1. SOURCE (run_finalizer): the extractor read the RAW `reason` step while the router sanitized only
     the text it SHOWS — so the user saw a clean reply while the extractor ate the bleed. It now
     sanitizes first. This is not symptom-filtering: the extractor was reading the wrong variable.
     (The true source — a 3B failing its output-discipline instruction — is not fixable in code.)
  2. FLOOR (distill.is_memory_junk): the shared chokepoint for the ~10 other writers (distill, tools,
     scheduler jobs, ingestion) that never touch the router.
"""
import re
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from layla.memory.distill import is_memory_junk  # noqa: E402

# Verbatim rows recovered from the operator DB — the regression these guards exist for.
REAL_POISON = [
    "This is a written TEXT chat: you are typing, not speaking — never mention audio, voice, "
    "microphones, or 'talking'. Talk like a real, sharp person messaging: natural and direct.",
    "Knowledge graph associations: ValueError; Hello.; Input must be a non-negative... To add two "
    "and two, you simply count up to four. No need for complex logic here.",
    "**Core**: Implement, debug, architect, ship.",
    "**Voice Contract**: Blunt and surgical — target the problem, not the person.",
]
# Prompt blocks that would close the feedback loop if stored.
PROMPT_BLOCKS = [
    "Things I remember: the user prefers tea.",
    "Relevant memories: the user is called Mina.",
    "Recent learnings: something the model echoed back.",
    "Knowledge graph associations: A; B; C",
]
# Legitimate learnings. A filter that eats these is WORSE than the bug it fixes — it would silently
# destroy real memory. Includes deliberate traps: header-like words used as ordinary content.
LEGIT = [
    "The user prefers concise answers without preamble.",
    "Validate the existence of the key before sorting.",
    "Use enumerate() to iterate with an index in Python.",
    "Focus on readability when reviewing this codebase.",
    "Voice Contract negotiations concluded in 2019.",
    "The user remembers things better when given examples.",
    "Relevant memories were discussed at the meeting.",
]


def test_real_poisoned_rows_are_rejected():
    for content in REAL_POISON:
        assert is_memory_junk(content), f"system-prompt bleed must never be stored: {content[:60]!r}"


def test_prompt_context_blocks_are_rejected():
    # Anchored at content start: storing these closes the learning -> graph -> prompt -> learning loop.
    for content in PROMPT_BLOCKS:
        assert is_memory_junk(content), f"prompt block must never be stored: {content[:60]!r}"


def test_legitimate_learnings_are_not_eaten():
    for content in LEGIT:
        assert not is_memory_junk(content), f"FALSE POSITIVE — real learning rejected: {content!r}"


def test_run_finalizer_sanitizes_before_extracting():
    # The extractor must receive the CLEANED reply, never the raw `reason` step. If this wiring is
    # removed, the bleed silently returns and nothing else fails.
    src = (AGENT / "services" / "agent" / "run_finalizer.py").read_text(encoding="utf-8")
    assert "clean_reply_text" in src, "run_finalizer must sanitize the reply before learning extraction"
    # Grab the whole args=... line at the extractor's call site (nested parens make a [^)]* capture wrong).
    m = re.search(r"target=auto_extract_learnings_fn,\s*\n\s*(args=.*)\n", src)
    assert m, "auto_extract_learnings_fn call site not found"
    args = m.group(1)
    assert "learn_text" in args, (
        f"the extractor must be passed the SANITIZED text (learn_text), not the raw step. Got: {args}"
    )
    assert "final_text" not in args, f"raw final_text must not be handed to the extractor. Got: {args}"

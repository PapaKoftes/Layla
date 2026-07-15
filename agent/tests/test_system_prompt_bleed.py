"""Regression: a weak local model regurgitates its own system-prompt tail (the Output-discipline
block, the per-aspect 'Reply as … only' anchor, or the injected '### REFERENCE' capability list) AFTER
its real answer. Measured live at ~33% of /v1 and ~66% of /agent trivial turns before the fix. Both
paths route replies through response_builder.strip_junk_from_reply, so it is the single choke point.

Each sample below is a REAL leak captured from the live instance; the fix must keep the answer and drop
the bleed. The negatives guard against over-truncation of legitimate replies."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.response_builder import strip_junk_from_reply  # noqa: E402

# Phrases that must NEVER survive into a user-facing reply (verbatim system-prompt text).
_BLEED_PHRASES = [
    "written TEXT chat",
    "private stage direction",
    "Match length to the message",
    "No theatrical or roleplay",
    "Reply as Morrigan only",
    "Reply as her only",
    "Do not output labels or repeat instructions",
    "never mention audio, voice",
    "REFERENCE",
    "[END]",
    "[End of message]",
]

# (raw_leak, must_start_with) — real captures. The answer is always the leading prose.
_LEAK_SAMPLES = [
    (
        "Four. To add two and two, you simply combine them to get four. This is a written TEXT "
        "chat: you are typing, not speaking — never mention audio, voice, microphones. No theatrical "
        "or roleplay openings. Reply as Morrigan only, in her style.",
        "Four.",
    ),
    (
        "The capital of France is Paris. ---\n\nThis is a written TEXT chat: you are typing, not "
        "speaking. Your persona and style notes are private stage direction.",
        "The capital of France is Paris.",
    ),
    (
        "Apple. \n\n[END] To clarify, if you need another fruit or a different kind of answer, let me know.",
        "Apple.",
    ),
    (
        "Hello there. ### REFERENCE\n\n- **Core**: Implement, debug, architect, refactor.\n- **Voices**: morrigan, nyx.",
        "Hello there.",
    ),
    (
        "The capital of France is Paris. This is a written TEXT chat: you are typing, not speaking.",
        "The capital of France is Paris.",
    ),
    (
        "Paris. \n\n[End of message] ```plaintext\nThis is a written TEXT chat: you are typing.\n```",
        "Paris.",
    ),
    (
        "Reply with ONLY your message to the user, as plain conversational prose.",  # whole reply IS the bleed
        None,  # → empty is acceptable (better than leaking); assert no bleed phrase survives
    ),
]

# Legit replies that MUST be preserved intact (over-truncation guard).
_CLEAN_SAMPLES = [
    "Here are the references you asked for:\n\n## References\n- Smith 2020\n- Doe 2021",
    "Please reply as soon as you can; I only need a yes or no.",
    "The answer is 4. No further explanation needed.",
    "```python\ndef add(a, b):\n    return a + b  # this is a written note, not TEXT chat scaffold\n```",
]


def _assert_no_bleed(out: str):
    low = out.lower()
    for phrase in _BLEED_PHRASES:
        if phrase == "REFERENCE":
            assert "### reference" not in low and "\nreference" not in low, f"leaked REFERENCE scaffold: {out!r}"
        else:
            assert phrase.lower() not in low, f"leaked system-prompt phrase {phrase!r}: {out!r}"


def test_leak_samples_drop_bleed_keep_answer():
    for raw, must_start in _LEAK_SAMPLES:
        out = strip_junk_from_reply(raw)
        _assert_no_bleed(out)
        if must_start is not None:
            assert out.startswith(must_start), f"answer not preserved: expected start {must_start!r}, got {out!r}"


def test_clean_samples_are_not_over_truncated():
    for raw in _CLEAN_SAMPLES:
        out = strip_junk_from_reply(raw)
        # The core answer token must survive.
        assert out.strip(), f"legit reply wrongly emptied: {raw!r}"
        # 'References' (title-case) and code comments must NOT be treated as scaffold.
        if "## References" in raw:
            assert "References" in out, f"legit References section wrongly stripped: {out!r}"
        if "reply as soon" in raw.lower():
            assert "yes or no" in out, f"legit 'reply as soon' sentence wrongly truncated: {out!r}"


def test_bleed_regex_is_shared_by_both_paths():
    # /agent (routers/agent.py) and /v1 (routers/openai_compat.py) both call clean_reply_text →
    # strip_junk_from_reply, so this single fix covers both. Assert the helper exists + is wired.
    from services.agent import response_builder as rb
    assert hasattr(rb, "_strip_system_prompt_bleed")
    assert rb._strip_system_prompt_bleed("ok. This is a written TEXT chat: x") == "ok."


def test_reasoning_tree_summary_does_not_leak_system_prompt():
    # Wiring the reasoning-tree into the UI exposed final_summary/outcome, which are built from RAW step
    # results and can carry the model's bleed. They must run through the same cleaner as the visible reply.
    from services.infrastructure.agent_task_runner import _build_reasoning_tree_summary
    leaked = "Hi there, Mina. How are you today? \n\n---\n\nThis is a written TEXT chat: you are typing. Reply as Morrigan only."
    state = {"steps": [{"action": "reason", "result": leaked}], "status": "finished", "original_goal": "say hi"}
    out = _build_reasoning_tree_summary(state)
    blob = (out["final_summary"] + " " + " ".join(n["outcome_summary"] for n in out["nodes"])).lower()
    for phrase in ("written text chat", "reply as morrigan", "stage direction"):
        assert phrase not in blob, f"reasoning tree leaked: {phrase!r} in {out['final_summary']!r}"
    assert "hi there" in out["final_summary"].lower(), "the real answer must survive"

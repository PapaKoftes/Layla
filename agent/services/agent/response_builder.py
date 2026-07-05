"""
Response text cleaning and formatting for the agent loop.

Extracted from agent_loop.py — Phase 2 decomposition.
These functions clean model output before it reaches the user.
"""
import json
import logging
import re
import time
from collections.abc import Callable

logger = logging.getLogger("layla")


def is_junk_reply(content: str) -> bool:
    """True if content is junk that must never reach the user.

    Catches:
    - empty / whitespace-only
    - repeated 'assistant: I replied.' echo loops
    - raw decision-JSON blobs (model confusing tool-decision format with final reply)
    """
    if not content or not content.strip():
        return True
    s = content.strip().lower()
    if s == "i replied." or s == "assistant: i replied.":
        return True
    remainder = re.sub(r"\s*assistant\s*:\s*i\s+replied\.\s*", " ", s, flags=re.IGNORECASE).strip()
    if len(remainder) < 15 and ("assistant" in s and "i replied" in s):
        return True
    stripped = content.strip()
    if stripped.startswith("{"):
        _decision_keys = ("\"action\"", "\"tool\"", "\"thought\"", "\"ok\"", "\"objective_complete\"", "\"args\"")
        hits = sum(1 for k in _decision_keys if k in stripped)
        if hits >= 2:
            return True
    return False


# Signals that a question genuinely needs tools/context (workspace, memory, web, exec,
# or the user's own data) — if any appears, it is NOT self-contained and the agent should
# be free to use tools. Kept as multi-word phrases so common words don't over-trigger.
_NEEDS_TOOLS_SIGNALS = (
    # workspace / files / code-in-repo
    "this file", "the file", "this repo", "the repo", "this project", "my project",
    "the code", "this code", "my code", "the codebase", "workspace", "directory",
    "read ", "open ", "edit ", "create a file", "write a file", "save ", "delete ",
    "list dir", "list the", "in the folder", "the function ", "this function",
    # memory / recall / personal data
    "remember", "recall", "we discussed", "did we", "last time", "earlier you",
    "my note", "our conversation", "what did we", "what's my", "what is my", "my name",
    "my todo", "my goal", "my plan",
    # web / current events
    "search for", "google", "look up", "latest", "current news", "today's", "weather",
    "browse", "http://", "https://", "www.",
    # exec / system
    "run ", "execute", "install", "pip ", "npm ", "git ", "the terminal", "shell command",
    "compile", "build the",
    # file write / path operations
    "write path", "write to", "with content", "append to", "save to", "overwrite",
    "output to", "into the file", "write file",
)

# a filesystem path (Windows drive, or a path starting with / ./ ../ ~/) → needs a tool.
# Deliberately narrow so casual slashes ("km/h", "and/or") don't trigger it.
_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|(?:^|\s)(?:\.{1,2}/|~/|/)[\w.-]+/")
_FILENAME_RE = re.compile(
    r"\b[\w-]+\.(?:txt|py|json|md|js|ts|jsx|tsx|csv|ya?ml|html?|css|xml|cpp?|hpp?|java|go|"
    r"rs|sh|toml|ini|log|pdf|png|jpe?g|gguf|env|cfg|sql|rb|php)\b",
    re.IGNORECASE,
)


def is_self_contained_question(goal: str) -> bool:
    """True when a goal is answerable from the model alone — no tools/files/memory/web.

    Used to keep the agent from wasting its tool budget (and hitting max-tool-calls) on
    general-knowledge / math / writing / translation / reasoning questions it can just
    answer. Conservative: any signal that real context is needed returns False.
    """
    g = (goal or "").strip()
    gl = g.lower()
    if len(g) < 3 or len(g) > 2000:
        return False
    if any(sig in gl for sig in _NEEDS_TOOLS_SIGNALS):
        return False
    # a filesystem path or a filename with a known extension → a tool is needed
    if _PATH_RE.search(g) or _FILENAME_RE.search(g):
        return False
    # a lone possessive "my"/"our" often implies personal data → let the loop decide
    if re.search(r"\b(my|our)\b", gl) and "?" in gl:
        return False
    return True


def looks_like_raw_tool_dict(text: str) -> bool:
    """True when `text` is a dumped tool-result dict leaking through as an 'answer'.

    The agent sometimes finishes a run having only made tool calls (no natural-language
    reason step); the raw `{"ok": false, "error": ...}` then leaks to the user. Detect
    that shape so callers can synthesize a real answer instead of showing JSON.
    """
    t = (text or "").strip()
    if not (t.startswith("{") and t.endswith("}")):
        return False
    try:
        d = json.loads(t)
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    keys = set(d.keys())
    return bool(keys & {"ok", "error", "reason", "_deterministic_return", "_empty_output", "message"})


def synthesize_direct_answer(goal: str, *, aspect_id: str = "", max_tokens: int = 320) -> str:
    """Answer the user's question directly from the model (no tools).

    The escape hatch for trivial Q&A the agent wrongly routed into (failed) tool calls:
    ask the model to just answer. Best-effort — returns "" if the model is unavailable.
    """
    g = (goal or "").strip()
    if not g:
        return ""
    try:
        from services.llm.llm_gateway import run_completion
        prompt = (
            "Answer the user's question or request directly, correctly, and concisely. "
            "Do not mention tools, files, or steps — just give the answer.\n\n"
            f"User: {g}\nAnswer:"
        )
        out = run_completion(prompt, max_tokens=max_tokens, temperature=0.2, stream=False)
        if isinstance(out, dict):
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
            text = clean_response_text(text)
            text = truncate_at_next_user_turn(text).strip()
            if text and not looks_like_raw_tool_dict(text):
                return text
    except Exception as e:  # noqa: BLE001
        logger.debug("synthesize_direct_answer failed: %s", e)
    return ""


def quick_reply_for_trivial_turn(goal: str) -> str:
    """Return instant deterministic replies for tiny chat turns."""
    g = (goal or "").strip()
    if not g:
        return ""
    gl = g.lower()
    if gl.startswith("reply exactly "):
        exact = g[len("reply exactly "):].strip().strip("\"'`")
        return exact[:120]
    if gl.startswith("say exactly "):
        exact = g[len("say exactly "):].strip().strip("\"'`")
        return exact[:120]
    if gl in {"ok", "okay", "yes", "yep", "no", "nope"}:
        return "Got it."
    if re.match(
        r"^(how are you( doing)?|what'?s up|wassup|how'?s it going|you good)\??$",
        gl,
    ):
        return "I'm good. What do you need?"
    return ""


def truncate_at_next_user_turn(text: str) -> str:
    """Keep only the first reply; cut at the first 'User:' so we don't save/show the model continuing the dialogue."""
    if not text or not text.strip():
        return (text or "").strip()
    t = text.strip()
    if re.match(r"^\s*User\s*:", t, re.IGNORECASE):
        m = re.search(r"^\s*User\s*:[^\n]*?\s+([A-Za-z]+)\s*:", t, re.IGNORECASE)
        if m:
            t = t[m.start(1):].strip()
        else:
            first_line_end = t.find("\n")
            if first_line_end != -1:
                t = t[first_line_end + 1:].strip()
            else:
                t = ""
    m = re.search(r"\n\s*User\s*:", t, re.IGNORECASE)
    if m:
        return t[:m.start()].strip()
    m = re.search(r"\s+User\s*:", t, re.IGNORECASE)
    if m:
        return t[:m.start()].strip()
    return t


def strip_junk_from_reply(text: str) -> str:
    """Remove repeated 'assistant: I replied.' and other junk from a reply before saving/displaying."""
    if not text or not text.strip():
        return (text or "").strip()
    t = text.strip()
    for _ in range(50):
        prev = t
        t = re.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", t, count=1, flags=re.IGNORECASE).strip()
        if t == prev:
            break
    # Strip control markers that leak anywhere in the reply.
    t = re.sub(r"\s*\[EARNED_TITLE[^\]]*\]\s*", " ", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s*\[REFUSED[^\]]*\]\s*", " ", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s*\[merg[^\]]*\]?\s*$", "", t, flags=re.IGNORECASE).strip()
    # Cut everything from a leaked internal 'Objective:' echo onward (anywhere but the very
    # start, so a legitimate answer that opens with the word isn't truncated).
    _obj = re.search(r"(?:^|\s)Objective\s*:", t, re.IGNORECASE)
    if _obj and _obj.start() > 0:
        t = t[:_obj.start()].strip()
    # Drop a *degenerate* tail: trailing lines that are only code-fences, lone single
    # characters, or blank — the shape a looping model emits after its real answer.
    # Conservative: only remove the run when it clearly loops (>=2 bare fences, or a lone
    # single char) so a legitimate single closing ``` of a real code block is preserved.
    _lines = t.split("\n")
    _tail_len = 0
    _fences = _lonechars = 0
    for _ln in reversed(_lines):
        if re.fullmatch(r"\s*(?:`{2,}|[A-Za-z]?)\s*", _ln or ""):
            _tail_len += 1
            if re.fullmatch(r"\s*`{2,}\s*", _ln or ""):
                _fences += 1
            elif re.fullmatch(r"\s*[A-Za-z]\s*", _ln or ""):
                _lonechars += 1
        else:
            break
    if _tail_len and (_fences >= 2 or _lonechars >= 1):
        t = "\n".join(_lines[: len(_lines) - _tail_len]).strip()
    # A dangling fence left INLINE at the end of a content line ("…olleh\". ```") is junk;
    # a fence on its own line (a real code block's close) is preceded by a newline, so the
    # `\S` lookbehind spares it.
    t = re.sub(r"(?<=\S)[ \t]*`{3,}[ \t]*$", "", t).strip()
    t = re.sub(r"^(Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\s*:\s*", "", t).strip()
    t = re.sub(r"\[System:\s*Your last response[^\]]*\]\s*", "", t, flags=re.IGNORECASE | re.DOTALL).strip()
    for _marker in (r"(?:^|\n)\s*#{1,3}\s*(TASK|CONTEXT|SCRATCHPAD|REPO)\b", r"(?:^|\n)\s*Current goal\s*:", r"(?:^|\n)\s*\[Active aspect\s*:", r"(?:^|\n)\s*Last user message\s*:", r"(?:^|\n)\s*Repo snapshot\s*:", r"(?:^|\n)\s*Repo structure\s*:", r"(?:^|\n)\s*##", r"(?:^|\s)Echo\s*\(patterns/preferences\)\s*:", r"(?:^|\n)\s*ECHO\s*:"):
        m = re.search(_marker, t, re.IGNORECASE)
        if m:
            t = t[:m.start()].strip()
    if is_junk_reply(t):
        return ""
    return t


def clean_response_text(text: str) -> str:
    """Strip echoed system head, instruction-like lines, and junk from model output."""
    if not text:
        return ""
    if text[0].lower() == "n" and len(text) > 4 and text[1:].strip().lower().startswith("you are layla"):
        text = text[1:].strip()
    paragraphs = text.split("\n\n")
    while paragraphs and paragraphs[0].strip():
        first = paragraphs[0].strip().lower()
        if first.startswith("you are layla") and ("use the identity" in first or "rules below" in first):
            paragraphs.pop(0)
        else:
            break
    text = "\n\n".join(paragraphs).strip()
    _echo_pat = re.compile(
        r"\s*\[[\w\s]+\]\s*\(You are[\s\S]*?(?=\)\.\s|\s*\[[\w\s]+\]\s*\(You are|\s*assistant\s*:|\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    for _ in range(20):
        prev = text
        text = _echo_pat.sub("", text, count=1).strip()
        if text == prev:
            break
    if re.match(r"^\s*assistant\s*:\s*", text, re.IGNORECASE):
        text = re.sub(r"^\s*assistant\s*:\s*", "", text, count=1, flags=re.IGNORECASE).strip()
    for _ in range(50):
        prev = text
        text = re.sub(r"^\s*assistant\s*:\s*I\s+replied\.\s*", "", text, count=1, flags=re.IGNORECASE).strip()
        if text == prev:
            break
    if is_junk_reply(text):
        text = ""
    lines = text.split("\n")
    while lines:
        first = lines[0].strip()
        if re.match(r"^\[[\w\s]+\]\s*\(?", first) or first.startswith("[ACTIVE ASPECT:"):
            lines.pop(0)
            continue
        if first.startswith("You are ") and ("aspect" in first.lower() or " the " in first[:80]):
            lines.pop(0)
            continue
        if first.lower() in ("assistant:", "assistant", "i replied."):
            lines.pop(0)
            continue
        if is_junk_reply(first):
            lines.pop(0)
            continue
        break
    text = "\n".join(lines).strip()
    if not text or text.lower().strip() == "assistant:" or is_junk_reply(text):
        text = ""
    return text


def iter_with_response_pacing(tokens, pacing_ms: int):
    """Minimum delay between successive streamed chunks (final reply path only). Caps at 10s per gap."""
    try:
        ms = int(pacing_ms or 0)
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        yield from tokens
        return
    delay = max(0.0, min(10.0, ms / 1000.0))
    first = True
    for t in tokens:
        if not first:
            time.sleep(delay)
        first = False
        yield t

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
    # exec / system. NB "install " keeps the trailing space so the imperative ("install numpy")
    # triggers but the adjective ("installed features", "what's installed") does NOT — the latter
    # is a question about state she can answer directly, not a command to run.
    "run ", "execute", "install ", "pip ", "npm ", "git ", "the terminal", "shell command",
    "compile", "build the",
    # file write / path operations
    "write path", "write to", "with content", "append to", "save to", "overwrite",
    "output to", "into the file", "write file",
)

# The subset of tool signals a general how-to / explain question would NEVER contain —
# memory/personal/web/exec. These VETO the general-QA fast-path shortcut (unlike the soft
# file/read/open/code signals, which a legitimate "how do I read a file?" question does mention).
_HARD_TOOL_SIGNALS = (
    "remember", "recall", "we discussed", "did we", "last time", "earlier you",
    "my note", "our conversation", "what did we", "what's my", "what is my", "my name",
    "my todo", "my goal", "my plan", "my project", "my code",
    "search for", "google", "look up", "latest", "current news", "today's", "weather",
    "browse", "http://", "https://", "www.",
    "run ", "execute", "install ", "pip ", "npm ", "git ", "the terminal", "shell command",
)

# a filesystem path (Windows drive, or a path starting with / ./ ../ ~/) → needs a tool.
# Deliberately narrow so casual slashes ("km/h", "and/or") don't trigger it.
_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|(?:^|\s)(?:\.{1,2}/|~/|/)[\w.-]+/")
_FILENAME_RE = re.compile(
    r"\b[\w-]+\.(?:txt|py|json|md|js|ts|jsx|tsx|csv|ya?ml|html?|css|xml|cpp?|hpp?|java|go|"
    r"rs|sh|toml|ini|log|pdf|png|jpe?g|gguf|env|cfg|sql|rb|php)\b",
    re.IGNORECASE,
)

# A general how-to / explain / define / code-generation question is answerable from the model
# itself even when it mentions read/open/write/file/code — it asks ABOUT a concept, it does not
# ask Layla to operate on the user's files. Without this, "how do I read a file in python?"
# trips the broad "read " signal below and gets routed into (failing) tool calls.
_GENERAL_QA_PREFIXES = (
    "how do i", "how do you", "how can i", "how would i", "how to", "how does", "how is",
    "what is", "what's", "what are", "what does", "whats the", "explain", "define", "describe",
    "why ", "when should", "when do", "difference between", "compare ", "pros and cons",
    "write a function", "write a python", "write a script", "give me an example",
    "show me an example", "example of", "teach me", "help me understand", "can you explain",
)
# Signals that a question points at a CONCRETE file/repo/workspace (these genuinely need tools
# and so must veto the general-QA short-circuit above).
_WORKSPACE_REF_SIGNALS = (
    "this file", "the file", "this repo", "the repo", "this project", "my project",
    "the code", "this code", "my code", "the codebase", "workspace", "in the folder",
    "the function ", "this function", "my note", "our conversation",
)


def is_self_contained_question(goal: str) -> bool:
    """True when a goal is answerable from the model alone — no tools/files/memory/web.

    Used to keep the agent from wasting its tool budget (and hitting max-tool-calls) on
    general-knowledge / math / writing / translation / reasoning questions it can just
    answer. Conservative: any signal that real context is needed returns False.
    """
    g = (goal or "").strip()
    gl = g.lower()
    if not g or len(g) > 2000:
        return False
    # Greetings / acknowledgements / tiny chit-chat → answer directly in a SINGLE voice
    # (no tools, no planning, and critically no multi-aspect deliberation — for "hi" that
    # concatenated several aspects' greetings into a repeating loop with stray [REFUSED:] tags).
    if re.match(
        r"^(hi+|hey+|hello+|yo|sup|hiya|howdy|greetings|gm|gn|"
        r"good\s?(morning|afternoon|evening|night)|thx|thanks?|thank\s?you|ty|"
        r"ok(ay)?|k|yes|yep|yeah|no|nope|cool|nice|great|awesome|sure|"
        r"how\s?are\s?you|how'?s\s?it\s?going|what'?s\s?up|wassup|hru)[\s!.?,]*$",
        gl,
    ):
        return True
    # Non-greeting inputs shorter than 3 chars ("x", "?") aren't real questions — let the loop decide.
    if len(g) < 3:
        return False
    # General how-to / explain / code-generation Q&A is self-contained even when it mentions
    # file/read/write/code words — but only if it doesn't point at a concrete file/repo/path AND
    # carries no hard tool signal (memory/personal/web/exec, e.g. "what's my name?").
    _points_at_workspace = bool(
        _PATH_RE.search(g) or _FILENAME_RE.search(g)
        or any(s in gl for s in _WORKSPACE_REF_SIGNALS)
    )
    _hard = any(s in gl for s in _HARD_TOOL_SIGNALS) or bool(re.search(r"\b(my|our)\b", gl) and "?" in gl)
    if not _points_at_workspace and not _hard and any(gl.startswith(p) for p in _GENERAL_QA_PREFIXES):
        return True
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
    # Strip a markdown code fence — models almost always wrap JSON in ```json … ```.
    _m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.DOTALL | re.IGNORECASE)
    if _m:
        t = _m.group(1).strip()
    if not ((t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))):
        return False
    try:
        d = json.loads(t)
    except Exception:
        return False
    # Unwrap a single-element list wrapper: [{"ok": false, …}].
    if isinstance(d, list):
        d = d[0] if len(d) == 1 and isinstance(d[0], dict) else None
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
    # A leading fake "User:" turn (any case) — strip it, keep the real reply that follows.
    if re.match(r"^\s*User\s*:", t, re.IGNORECASE):
        m = re.search(r"^\s*User\s*:[^\n]*?\s+([A-Za-z]+)\s*:", t, re.IGNORECASE)
        if m:
            t = t[m.start(1):].strip()
        else:
            first_line_end = t.find("\n")
            t = t[first_line_end + 1:].strip() if first_line_end != -1 else ""
    # Cut where the model starts role-playing the NEXT turn as "User:", "You:" or "Human:".
    # Case-SENSITIVE (capitalized tag) + word boundary so an ordinary "thank you:" is not
    # mistaken for a turn, and only at a real boundary (line start / after newline / after
    # sentence-ending punctuation) — e.g. "…grass is green. You: hey there".
    for mt in re.finditer(r"\b(?:User|You|Human)\s*:", t):
        i = mt.start()
        prev = t[:i].rstrip()
        if i == 0 or t[i - 1] == "\n" or (prev and prev[-1] in ".!?"):
            cut = t[:i].strip()
            return cut if cut else t
    return t


# Bracketed control/scaffold tags stripped from streamed + final output. The trailing
# alternation matches per-aspect deliberation scaffold like "[⚔ MORRIGAN]" / "[✦ NYX]"
# (the [^\]]* before the name absorbs the sigil) so multi-aspect debate lines can never
# leak into a reply even if deliberation is somehow triggered.
_STREAM_MARKER_RE = re.compile(
    r"\[(?:EARNED_TITLE|TOOL|REFUSED|INQUIRY|MERGE|THINK|PLAN|STEP|ANSWER|CONCLUSION|"
    r"ASPECT|NOTE|SYSTEM|CONTEXT|Active aspect|"
    r"[^\]]*\b(?:MORRIGAN|NYX|ECHO|ERIS|CASSANDRA|LILITH))\b[^\]]*\]",
    re.IGNORECASE,
)

# Canonical persona/aspect labels. A weak model routinely opens its reply with a speaker tag that
# MIRRORS the UI's own aspect chip ("Morrigan:", "⚔ Morrigan:", "**Morrigan:**", "## Morrigan",
# "Layla ⚔ Morrigan:", a bare sigil) — so the same tag renders TWICE ("two tags, one broken").
# The old strip only caught the bare `Name:` form. _strip_leading_speaker_label() below covers the
# full decorated/sigil/heading/Layla/newline vocabulary, NAME-GATED so a real heading ("## Overview")
# or prose that merely starts with a word is never touched.
_ASPECT_NAMES_BASE = ("Layla", "Morrigan", "Nyx", "Echo", "Eris", "Cassandra", "Lilith")
_ASPECT_SIGILS = "⚔✦◎⚡⌖⊛"


def _strip_leading_speaker_label(t: str, extra_names: tuple[str, ...] = ()) -> str:
    """Remove a leading speaker/persona label that mirrors the UI's aspect chip.

    NAME-GATED: the label must contain 'Layla', a Layla sigil, or a (built-in or custom) aspect
    name — so a legitimate markdown heading ('## Overview') or prose beginning with an ordinary
    word is never stripped. Handles: bare 'Morrigan:', 'Layla:', sigil forms '⚔ Morrigan[:]',
    markdown '**Morrigan:**' / '## Morrigan' / '> Morrigan:', name-on-its-own-line 'Morrigan\\n',
    the composite 'Layla ⚔ Morrigan:', and a bare leading sigil. Only strips when real prose
    follows (never nukes the whole reply — that would trip the empty-reply fallback)."""
    if not t:
        return t
    names = tuple(n for n in (_ASPECT_NAMES_BASE + tuple(extra_names)) if n)
    if not names:
        return t
    name_alt = "|".join(re.escape(n) for n in names)
    sig = "[" + _ASPECT_SIGILS + "]"
    core = r"(?:Layla\b[ \t]*)?(?:" + sig + r"[ \t]*)?(?:(?:" + name_alt + r")\b[ \t]*)?"
    # Case 1 — colon-terminated, optionally wrapped in markdown emphasis/heading/blockquote.
    pat_colon = re.compile(
        r"^[ \t]*(?:>[ \t]*)?(?:#{1,3}[ \t]*)?(?:[*_]{1,2})?[ \t]*"
        r"(?P<label>" + core + r")(?:[*_]{1,2})?[ \t]*:[ \t]*(?:[*_]{1,2}[ \t]*)?",
        re.IGNORECASE,
    )
    # Case 2 — the label sits alone on the first line (newline-terminated).
    pat_line = re.compile(
        r"^[ \t]*(?:>[ \t]*)?(?:#{1,3}[ \t]*)?(?:[*_]{1,2})?[ \t]*"
        r"(?P<label>" + core + r")(?:[*_]{1,2})?[ \t]*\n+",
        re.IGNORECASE,
    )
    # Case 3 — DECORATED label (heading/emphasis/blockquote/sigil present) then whitespace+prose.
    # A bare name+space is intentionally NOT matched here (that needs a colon/newline) so prose
    # like "Echo the input back" is untouched.
    pat_dec = re.compile(
        r"^[ \t]*(?P<deco>(?:>[ \t]*)|(?:#{1,3}[ \t]*)|(?:[*_]{1,2})|(?:" + sig + r"[ \t]*))"
        r"(?:>[ \t]*|#{1,3}[ \t]*|[*_]{1,2}|[ \t])*"
        r"(?P<label>" + core + r")(?:[*_]{1,2})?[ \t]+(?=\S)",
        re.IGNORECASE,
    )

    def _has_token(label: str) -> bool:
        if re.search(sig, label):
            return True
        return bool(re.search(r"\b(?:" + name_alt + r")\b", label, re.IGNORECASE))

    for pat in (pat_colon, pat_line, pat_dec):
        m = pat.match(t)
        if not m:
            continue
        label = m.group("label") or ""
        deco = m.groupdict().get("deco") or ""
        if not _has_token(label) and not re.search(sig, deco):
            continue
        rest = t[m.end():].lstrip()
        if not rest:
            return t  # never nuke the whole reply
        return rest
    return t


def stream_safe_prefix(raw: str, already_emitted: int) -> tuple[str, int]:
    """Incremental marker filter for the streaming hot path.

    Returns ``(delta, new_emitted_len)`` — the next chunk safe to send to the client and the
    updated emitted length. Holds back everything from an UNCLOSED ``[`` (a marker still being
    generated) and strips any COMPLETE ``[MARKER …]`` before emitting, so control tags never
    flash mid-stream. The final done-frame still runs full strip_junk_from_reply.
    """
    safe_end = len(raw)
    lb = raw.rfind("[")
    if lb != -1 and "]" not in raw[lb:]:
        safe_end = lb  # a bracket is open — hold from it until it closes (or the stream ends)
    clean = _STREAM_MARKER_RE.sub("", raw[:safe_end])
    # Before anything is emitted, a leading speaker label ("Morrigan:", "⚔ Morrigan", "**Nyx:**")
    # must never flash live. Strip a COMPLETE one; while the buffer could still be a partial label
    # mid-generation (short, no terminator yet), hold so we never paint half a tag. Once emission
    # has started the label is already gone/handled, so only gate on already_emitted == 0.
    if already_emitted == 0 and clean:
        _stripped = _strip_leading_speaker_label(clean)
        if _stripped != clean:
            clean = _stripped
        elif _maybe_partial_leading_label(clean):
            return "", 0
    if len(clean) <= already_emitted:
        return "", already_emitted
    return clean[already_emitted:], len(clean)


def _maybe_partial_leading_label(s: str) -> bool:
    """True if ``s`` (the not-yet-emitted stream head) could still be an in-progress speaker label
    that hasn't terminated. Conservative: only holds a SHORT head that either opens with markdown/
    sigil decoration or is a strict prefix of an aspect/Layla name, and only until a ':'/newline or
    clear non-label content arrives — so ordinary replies are never delayed more than a token."""
    if not s or "\n" in s or ":" in s:
        return False
    head = s.lstrip()
    if not head or len(head) > 32:
        return False
    if re.match(r"^(?:>|#{1,3}|[*_]{1,2}|[" + _ASPECT_SIGILS + r"])", head):
        return True
    low = head.lower()
    for _n in _ASPECT_NAMES_BASE:
        nl = _n.lower()
        if nl.startswith(low) and low != nl:          # still typing the name
            return True
        if low.startswith(nl) and len(low) <= len(nl) + 2:  # name done, terminator not yet here
            return True
    return False


def _collapse_repetition(text: str) -> str:
    """Cut a reply where it degenerates into repeated / near-duplicate sentences.

    Small local models loop — e.g. "Hi! What do you need? Hi there, can you clarify? Hello
    again, could you be specific?" — one greeting restated a dozen ways. Keep the first coherent
    run: walk sentences and stop at the first one whose 5-word normalized prefix was already
    seen. Conservative: only engages on 4+ sentences so it never touches a normal short reply,
    and it does NOT run inside fenced code blocks (repeated lines there can be legitimate).
    """
    if not text or len(text) < 120 or "```" in text:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(parts) < 4:
        return text
    # Greeting loop: the model restates a greeting several *different* ways ("Greetings…
    # Hello! … Hi there … Hello again …"). Lexical prefixes differ, so detect repeated greeting
    # OPENERS and cut at the second one — keeping the first clean greeting + its follow-up.
    _greet = re.compile(r"^(hi|hey+|hello|greetings|hiya|howdy|yo|sup)\b", re.IGNORECASE)
    greet_idxs = [i for i, p in enumerate(parts) if _greet.match(p.strip())]
    if len(greet_idxs) >= 2:
        cut = greet_idxs[1]
        return (" ".join(parts[:cut]).strip() or parts[0].strip())
    # General loop: cut at the first sentence whose 5-word normalized prefix already appeared.
    seen: set[str] = set()
    kept: list[str] = []
    for p in parts:
        norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", p.lower())).strip()
        key = " ".join(norm.split()[:5])
        if key and len(key) > 6 and key in seen:
            break
        if key:
            seen.add(key)
        kept.append(p)
    out = " ".join(kept).strip()
    return out or text


_FENCE_BLOCK_RE = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)


def _collapse_duplicate_blocks(text: str) -> str:
    """Remove a trailing fenced code block that is a byte-identical reprint of an earlier one.

    A looping/KV-retried generation re-emits its answer, so the reply ends with the SAME
    ```code``` block it already showed (the 'code block then mangled duplicate' bug). The
    generic prose de-duper skips anything containing a fence, so this is the fence-safe path:
    it only cuts when the LAST block exactly matches an earlier block (normalized whitespace),
    dropping the duplicate and any lead-in prose after the original — never touching a reply
    whose fenced blocks are all distinct, and never editing content inside a single block.
    """
    if not text or text.count("```") < 4:
        return text
    blocks = list(_FENCE_BLOCK_RE.finditer(text))
    if len(blocks) < 2:
        return text

    def _norm(m):
        return re.sub(r"\s+", " ", m.group(0)).strip().lower()

    last = blocks[-1]
    last_norm = _norm(last)
    for b in blocks[:-1]:
        if _norm(b) == last_norm:
            # everything from the last (duplicate) block to the end is a reprint — cut it,
            # then trim a dangling lead-in line if it too duplicates earlier prose.
            head = text[: last.start()].rstrip()
            return head
    return text


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
    # Unbracketed 'REFUSED: reason' — a small model appends a fake refusal tail AFTER an actual
    # answer ("int x = 0;\nREFUSED: too broad"). It's leaked control scaffolding, not prose, so cut
    # from a line-anchored REFUSED: to the end. Case-SENSITIVE (the marker is always upper-case) so
    # legit prose like "the request was refused: here's why" is untouched.
    t = re.sub(r"(?:^|\n)[ \t]*REFUSED[ \t]*:.*\Z", "", t, flags=re.DOTALL).strip()
    # Catch-all for the rest of the internal scaffolding vocabulary a small model echoes
    # (INQUIRY, MERGE, THINK, PLAN, STEP, ANSWER, CONCLUSION, ASPECT, …) so no bracketed
    # control tag survives into the visible reply.
    t = re.sub(
        r"\s*\[(?:INQUIRY|MERGE|THINK|PLAN|STEP|ANSWER|CONCLUSION|ASPECT|NOTE|SYSTEM|CONTEXT)\b[^\]]*\]\s*",
        " ", t, flags=re.IGNORECASE,
    ).strip()
    # '[Active aspect: NAME]' is a self-contained control marker: remove just the bracket
    # (like EARNED_TITLE) so a *leading* leak keeps the real answer that follows it, rather
    # than truncating-to-end and dropping the whole reply.
    t = re.sub(r"\s*\[Active aspect[^\]]*\]\s*", " ", t, flags=re.IGNORECASE).strip()
    # Per-aspect deliberation scaffold like '[⚔ MORRIGAN]' / '[✦ NYX]' — strip the bracket so a
    # stray debate line can never render as part of a reply (defense-in-depth; deliberation is
    # off by default). The [^\]]* before the name absorbs the sigil.
    t = re.sub(
        r"\s*\[[^\]]*\b(?:MORRIGAN|NYX|ECHO|ERIS|CASSANDRA|LILITH)\b[^\]]*\]\s*",
        " ", t, flags=re.IGNORECASE,
    ).strip()
    # Generic control-marker catch-all: small models INVENT bracketed ALL-CAPS scaffold tags
    # ([AFFIRMATIVE: …], [OBSERVATION: …]) we can't enumerate. Strip any "[ALLCAPS: …]" token
    # — the colon form is the scaffold shape. Case-SENSITIVE and colon-REQUIRED so code stays
    # intact (dict[KEY], arr[IDX], a bare "[ERROR]" log line, and "[1]" citations are all safe).
    t = re.sub(r"\s*\[[A-Z][A-Z0-9_]{2,}\s*:[^\]]*\]\s*", " ", t).strip()
    # Trailing self-name restart: after a finished sentence the model sometimes appends its own
    # name (and echoes the user) as a fake new turn — "…journey begin. Layla. Hello." Strip a
    # dangling "<Name>." (+ optional echoed greeting) that follows sentence-ending punctuation.
    t = re.sub(
        r"(?<=[.!?])\s+(?:Layla|Morrigan|Nyx|Echo|Eris|Cassandra|Lilith)\s*[.:]?\s*"
        r"(?:hi|hey|hello|sup|yo)?\s*[.!?]?\s*$",
        "", t, flags=re.IGNORECASE,
    ).strip()
    t = re.sub(r"\s*\[merg[^\]]*\]?\s*$", "", t, flags=re.IGNORECASE).strip()
    # A lone, dangling '[' at the very end (the stream ended mid-marker, or the model emitted a
    # stray open bracket). stream_safe_prefix holds it mid-stream but it survives into the final
    # text. Strip a trailing '[' with nothing but whitespace after it (keeps real "arr[0]" etc.).
    t = re.sub(r"\s*\[\s*$", "", t).strip()
    # Truncated trailing control marker: an open bracket + marker-ish text with NO closing ']'
    # because the stream hit max_tokens mid-marker, e.g. "…\n[Active aspect" or "…[EARNED_TITLE".
    t = re.sub(
        r"\[\s*(?:Active aspect|EARNED_TITLE|TOOL|REFUSED|INQUIRY|MERGE|SYSTEM|CONTEXT|ASPECT|NOTE|STEP|PLAN|THINK)[^\]]*$",
        "", t, flags=re.IGNORECASE,
    ).strip()
    # Empty / label-only code fence the model left dangling (```plaintext\n\n``` or a lone ```lang).
    t = re.sub(r"```[a-zA-Z]*\s*```", "", t).strip()
    # A dangling OPENING fence at the very end: require a language tag (```python) so a legitimate
    # BARE closing ``` of a real code block is preserved — matching ```\s*$ would eat it.
    t = re.sub(r"```[a-zA-Z]+\s*$", "", t).strip()
    # Immediate duplicated 2-4 word phrase ("To Layla To Layla" → "To Layla") — a small-model echo.
    for _ in range(3):
        _prev = t
        t = re.sub(r"\b(\w[\w']*(?:\s+\w[\w']*){1,3})\s+\1\b", r"\1", t).strip()
        if t == _prev:
            break
    # Cut from a leaked internal '[TOOL: …]' framing marker onward (and a trailing rule
    # left before it), e.g. "…the country.\n---\n[TOOL: markdown]\n# Research …".
    _tool = re.search(r"\[TOOL\b", t, re.IGNORECASE)
    if _tool:
        t = t[:_tool.start()].strip()
    t = re.sub(r"(?:\s*-{3,}\s*)+$", "", t).strip()
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
    # Leading speaker/persona label — "Morrigan:", "⚔ Morrigan:", "**Morrigan:**", "## Morrigan",
    # "Layla ⚔ Morrigan:", a bare sigil — the "two tags, one broken" leak. Name-gated so a real
    # heading ("## Overview") is untouched. Runs BEFORE the section-header truncation below, so a
    # leading "## Morrigan" is DE-LABELED (the answer after it is kept) rather than truncated away.
    t = _strip_leading_speaker_label(t).strip()
    t = re.sub(r"\[System:\s*Your last response[^\]]*\]\s*", "", t, flags=re.IGNORECASE | re.DOTALL).strip()
    # A prompt-section header (## SYSTEM / ## TASK / …) can leak MID-LINE when the small model
    # echoes the scaffold after its answer ("… here?  ## SYSTEM\n\n<repeats the prompt>"). The
    # line-anchored markers below only catch it at a line start, so truncate at the uppercase
    # section name anywhere. Case-SENSITIVE on purpose: a natural '## Context' heading in prose
    # is title-case, so an ALL-CAPS '## CONTEXT' is unambiguously leaked scaffolding.
    _mecho = re.search(r"#{1,3}[ \t]*(?:SYSTEM|TASK|CONTEXT|SCRATCHPAD|REPO|OBJECTIVE|INSTRUCTIONS)\b", t)
    if _mecho:
        t = t[: _mecho.start()].strip()
    # NOTE: a bare "(?:^|\n)\s*##" used to live in this tuple and truncated the reply at the FIRST
    # markdown heading — so ANY legitimate answer opening with "## Overview" / "## Steps" was cut to
    # EMPTY and replaced by the "Sorry — I couldn't generate a response" fallback. Removed. Scaffold
    # headers stay covered: the case-sensitive _mecho cut above handles "## SYSTEM"/"## TASK"/…, and
    # the first pattern below truncates a leaked lowercase scaffold header by its known section name.
    for _marker in (r"(?:^|\n)\s*#{1,3}\s*(SYSTEM|TASK|CONTEXT|SCRATCHPAD|REPO|OBJECTIVE|INSTRUCTIONS)\b", r"(?:^|\n)\s*Current goal\s*:", r"(?:^|\n)\s*Last user message\s*:", r"(?:^|\n)\s*Repo snapshot\s*:", r"(?:^|\n)\s*Repo structure\s*:", r"(?:^|\s|\[)Echo\s*\(patterns/preferences\)\s*:", r"(?:^|\n)\s*\[?ECHO\s*:"):
        m = re.search(_marker, t, re.IGNORECASE)
        if m:
            t = t[:m.start()].strip()
    t = _collapse_repetition(t)
    t = _collapse_duplicate_blocks(t)  # fence-safe: cut a reprinted trailing code block
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
    # De-label a leading persona/speaker tag on the reasoning_handler path too (parity with
    # strip_junk_from_reply) — this path had NO leading-name strip at all, so "Layla:"/"⚔ Morrigan:"
    # leaked straight through the deliberation/reasoning replies.
    text = _strip_leading_speaker_label(text).strip()
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

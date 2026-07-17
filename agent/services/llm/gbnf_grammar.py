"""
gbnf_grammar.py — native GBNF constrained decoding for the agent decision JSON.

Constrained decoding via llama.cpp's own grammar sampler costs **zero extra
dependency**: llama-cpp-python compiles a GBNF string into a ``LlamaGrammar`` and the
sampler is then only allowed to emit tokens the grammar permits. Unlike a generic
JSON-schema constraint, a hand-built grammar can pin:

  * ``action``          -> {tool, reason, think, none}
  * ``priority_level``  -> {low, medium, high}
  * ``tool``            -> the *exact set of currently valid tool names* (∪ null)

so a small model physically cannot emit an unparseable decision or hallucinate a
tool that does not exist — the single biggest reliability failure on 3B/7B models.

The grammar *builder* is pure string manipulation with no ``llama_cpp`` import, so it
unit-tests without the inference engine; the tests compile the output with
``LlamaGrammar.from_string`` to prove it is well-formed GBNF. The *runner* imports
``llama_cpp`` lazily and returns ``None`` on any miss so callers fall through to the
existing outlines -> instructor -> plain-parse chain.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger("layla")

# Canonical, permissive JSON scaffolding. `string` uses `[^"\\] | "\\" .` rather than
# the strict escape set — for *generation* a permissive terminal is fine (the model
# rarely emits control chars) and it avoids GBNF hex-escape portability worries.
_JSON_SCAFFOLD = (
    'ws      ::= [ \\t\\n]*\n'
    'string  ::= "\\"" ( [^"\\\\] | "\\\\" . )* "\\""\n'
    'number  ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?\n'
    'boolean ::= "true" | "false"\n'
    'null    ::= "null"\n'
    'value   ::= object | array | string | number | boolean | null\n'
    'array   ::= "[" ws ( value (ws "," ws value)* )? ws "]"\n'
    'object  ::= "{" ws ( string ws ":" ws value (ws "," ws string ws ":" ws value)* )? ws "}"'
)

_ACTIONS = ("tool", "reason", "think", "none")
_PRIORITIES = ("low", "medium", "high")


def escape_gbnf_literal(s: str) -> str:
    """Escape a Python string for inclusion inside a GBNF double-quoted terminal."""
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def _json_string_terminal(s: str) -> str:
    """GBNF terminal that matches the JSON string literal "s" (quotes included).

    e.g. read_file -> the 4 source chars '"\\"read_file\\""', which as GBNF matches
    the 11 characters «"read_file»".
    """
    return '"\\"' + escape_gbnf_literal(s) + '\\""'


def _alternation(values: Iterable[str]) -> str:
    lits = [_json_string_terminal(v) for v in values]
    return " | ".join(lits)


def build_decision_grammar(valid_tools: Iterable[str] | None) -> str:
    """
    Build a GBNF grammar constraining output to one AgentDecision JSON object.

    ``action`` is required and first; every other key is optional but must appear in a
    fixed canonical order (a minor constraint small models handle well, and the
    downstream parser normalises regardless). ``tool`` is restricted to the deduped
    ``valid_tools`` plus ``null``; if ``valid_tools`` is empty it falls back to a free
    ``string`` so the grammar is always well-formed.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in valid_tools or ():
        name = (t or "").strip()
        if name and name not in seen:
            seen.add(name)
            cleaned.append(name)

    tool_rule = (_alternation(cleaned) + " | null") if cleaned else "string"

    root = (
        'root ::= "{" ws '
        '"\\"action\\"" ws ":" ws action '
        '( ws "," ws "\\"tool\\"" ws ":" ws tool )? '
        '( ws "," ws "\\"args\\"" ws ":" ws object )? '
        '( ws "," ws "\\"thought\\"" ws ":" ws string )? '
        '( ws "," ws "\\"priority_level\\"" ws ":" ws priority )? '
        '( ws "," ws "\\"objective_complete\\"" ws ":" ws boolean )? '
        '( ws "," ws "\\"revised_objective\\"" ws ":" ws string )? '
        'ws "}"'
    )

    return "\n".join(
        [
            root,
            f"action ::= {_alternation(_ACTIONS)}",
            f"tool ::= {tool_rule}",
            f"priority ::= {_alternation(_PRIORITIES)}",
            _JSON_SCAFFOLD,
        ]
    ) + "\n"


def gbnf_decoding_available() -> bool:
    """True if llama.cpp's grammar sampler is importable (no model needed to check)."""
    try:
        from llama_cpp import LlamaGrammar  # noqa: F401

        return True
    except Exception:
        return False


def run_gbnf_agent_decision(
    llm: Any,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    valid_tools: frozenset[str],
) -> dict | None:
    """
    Generate one agent decision under a GBNF grammar on a local llama.cpp model.

    Returns the normalised decision dict (via ``decision_schema.parse_decision``), or
    ``None`` if llama_cpp/grammar is unavailable or generation fails — so the caller
    falls through to the existing outlines/instructor/plain chain.
    """
    try:
        from llama_cpp import LlamaGrammar
    except Exception:
        return None

    try:
        grammar_text = build_decision_grammar(valid_tools)
        grammar = LlamaGrammar.from_string(grammar_text, verbose=False)
    except Exception as e:
        logger.debug("gbnf: grammar build/compile failed: %s", e)
        return None

    try:
        out = llm.create_completion(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            grammar=grammar,
            stream=False,
        )
    except Exception as e:
        logger.debug("gbnf: constrained completion failed: %s", e)
        return None

    try:
        text = (out.get("choices") or [{}])[0].get("text") or ""
    except Exception:
        text = ""
    if not text.strip():
        return None

    try:
        from decision_schema import parse_decision

        return parse_decision(text, valid_tools)
    except Exception as e:
        logger.debug("gbnf: parse_decision failed: %s", e)
        return None


# ── operator-fact extraction grammar (BL-376) ───────────────────────────────
_SUBJECTS = ("user", "world", "none")
_MEM_TYPES = ("preference", "correction", "identity", "episodic")


def build_memory_grammar() -> str:
    """Build a GBNF grammar constraining output to one operator-fact JSON object.

    Mirrors build_decision_grammar: enum-pinned keys in a fixed canonical order. A 3B
    physically cannot emit a `subject` outside {user, world, none} nor invent a type —
    which is what makes the `subject != "user"` hard-reject *enforceable* rather than
    hopeful. All four keys are required: a partial object is a parse failure, not a
    default, because a defaulted `subject` would be a guess and guessing is the bug.
    """
    root = (
        'root ::= "{" ws '
        '"\\"subject\\"" ws ":" ws subject ws "," ws '
        '"\\"type\\"" ws ":" ws memtype ws "," ws '
        '"\\"fact\\"" ws ":" ws string ws "," ws '
        '"\\"durable\\"" ws ":" ws boolean '
        'ws "}"'
    )
    return "\n".join(
        [
            root,
            f"subject ::= {_alternation(_SUBJECTS)}",
            f"memtype ::= {_alternation(_MEM_TYPES)}",
            _JSON_SCAFFOLD,
        ]
    ) + "\n"


def run_gbnf_memory_extraction(
    llm: Any, prompt: str, *, max_tokens: int = 96, temperature: float = 0.0
) -> dict | None:
    """One grammar-constrained operator-fact extraction. ``None`` on ANY miss.

    There is deliberately no degraded path that returns unvalidated text: the caller
    MUST treat None as "extract nothing", never as "store the raw output". Storing
    unvalidated model output is precisely how the learnings table filled with docstrings.
    """
    try:
        from llama_cpp import LlamaGrammar
    except Exception:
        return None
    try:
        grammar = LlamaGrammar.from_string(build_memory_grammar(), verbose=False)
    except Exception as e:
        logger.debug("gbnf: memory grammar build/compile failed: %s", e)
        return None
    try:
        out = llm.create_completion(
            prompt, max_tokens=max_tokens, temperature=temperature, grammar=grammar, stream=False
        )
        text = (out.get("choices") or [{}])[0].get("text") or ""
    except Exception as e:
        logger.debug("gbnf: memory extraction failed: %s", e)
        return None
    if not text.strip():
        return None
    try:
        import json as _json

        v = _json.loads(text)
    except Exception:
        return None
    return v if isinstance(v, dict) else None

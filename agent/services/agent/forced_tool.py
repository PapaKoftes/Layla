"""Forced first tool for an explicit file-creation request (like an API's ``tool_choice``).

MEASURED on jinx-20b (GPU, real production decision prompts, real GBNF grammar, 3 samples per cell): for
"Create a file named notes_a.txt containing banana" the model chose ``think``/``reason`` in every sample
under every prompt variant tried — reworded aspect biases, a write_file few-shot, both. Yet when it DID pick
write_file (unconstrained fallback) it filled ``{"path": "probe_write.txt", "content": "banana"}`` exactly.
Selection is the failure, argument-filling is fine, so the operator's explicit instruction selects the tool
and the model fills the arguments. Nothing is bypassed: write_file still goes through allow_write + the
approval gate.

Deliberately narrow — it fires only when ALL hold:
  * writes are allowed for this request and write_file is offered;
  * this is the first decision (nothing but the pre-read probe has run) and nothing was written yet;
  * the message is an instruction, not a question ("how do I create a file in Python?" never fires);
  * it uses a create/write/save-style verb and names exactly one concrete filename;
  * it does not also ask to read / summarize / convert something first (that must run before the write).
"""
from __future__ import annotations

import re

_WRITE_VERBS = re.compile(r"\b(create|write|make|save|put|store|generate)\b", re.IGNORECASE)
_READ_FIRST = re.compile(
    r"\b(read|summari[sz]e|summary of|based on|from the|copy|convert|translate|analy[sz]e|look at|open|"
    r"extract|rewrite|refactor|fix|edit|update|modify|append)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"^\s*(how|what|why|when|where|which|who|explain|should|is|are|does|do|did|can i)\b", re.IGNORECASE)
_POLITE_REQUEST = re.compile(r"^\s*(can|could|would|will) you\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_FILENAME = re.compile(r"(?<![\w.])[\w\-]+(?:[/\\][\w\-]+)*\.[A-Za-z][A-Za-z0-9]{0,5}\b")


def _wants_new_file(m: str) -> bool:
    if _QUESTION.match(m) or (m.endswith("?") and not _POLITE_REQUEST.match(m)):
        return False
    if not _WRITE_VERBS.search(m) or _READ_FIRST.search(m):
        return False
    return len(set(_FILENAME.findall(_URL.sub(" ", m)))) == 1


def _named_existing_file(m: str, workspace_root: str) -> str | None:
    """The single filename the message names, if it exists under the workspace."""
    if not workspace_root:
        return None
    names = set(_FILENAME.findall(_URL.sub(" ", m)))
    if len(names) != 1:
        return None
    from pathlib import Path

    name = next(iter(names)).replace("\\", "/")
    try:
        root = Path(workspace_root).expanduser().resolve()
        p = (root / name).resolve()
        return name if p.is_file() and p.is_relative_to(root) else None
    except (OSError, ValueError):
        return None


def forced_first_tool(message: str, *, allow_write: bool, valid_tools, steps, workspace_root: str = "") -> str | None:
    """``write_file`` for an explicit create-one-named-file request; ``read_file`` when the message names one
    file that EXISTS in the workspace (live: asked "What is the secret token in probe_token.txt?" the model
    listed the folder and invented the token — answering about a named file without reading it); else None."""
    for s in steps or []:
        if (s or {}).get("action") != "pre_read_probe":
            return None  # first decision only
    m = (message or "").strip()
    if not m:
        return None
    tools = valid_tools or ()
    if allow_write and "write_file" in tools and _wants_new_file(m):
        return "write_file"
    if "read_file" in tools and _named_existing_file(m, workspace_root):
        return "read_file"
    return None

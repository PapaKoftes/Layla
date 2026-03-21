"""Fabrication assist: variants, explain, session — no FastAPI agent loop coupling on main."""

from fabrication_assist.assist.explain import format_comparison_table, summarize_best
from fabrication_assist.assist.layla_lite import assist, parse_intent
from fabrication_assist.assist.runner import BuildRunner, StubRunner, SubprocessJsonRunner
from fabrication_assist.assist.session import AssistSession, default_session_path, load_session, save_session
from fabrication_assist.assist.variants import load_knowledge_dir, propose_variants

__all__ = [
    "assist",
    "AssistSession",
    "BuildRunner",
    "SubprocessJsonRunner",
    "default_session_path",
    "format_comparison_table",
    "load_knowledge_dir",
    "load_session",
    "parse_intent",
    "propose_variants",
    "save_session",
    "StubRunner",
    "summarize_best",
]

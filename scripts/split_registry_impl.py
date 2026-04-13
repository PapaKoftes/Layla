#!/usr/bin/env python3
"""Split agent/layla/tools/registry_body.py into impl/*.py by domain manifests."""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_BODY = ROOT / "agent" / "layla" / "tools" / "registry_body.py"
DOMAINS = ROOT / "agent" / "layla" / "tools" / "domains"
IMPL = ROOT / "agent" / "layla" / "tools" / "impl"

DOMAIN_TO_IMPL = {
    "file": "file_ops",
    "code": "code",
    "git": "git",
    "web": "web",
    "memory": "memory",
    "system": "system",
    "data": "data",
    "analysis": "analysis",
    "automation": "automation",
    "general": "general",
    "geometry": "geometry",
}

HEADER = '''"""Tool implementations — domain: {impl_name}."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {{}}
'''


def load_fn_to_impl() -> dict[str, str]:
    fn_map: dict[str, str] = {}
    for p in sorted(DOMAINS.glob("*.py")):
        if p.name == "__init__.py":
            continue
        stem = p.stem
        impl = DOMAIN_TO_IMPL.get(stem)
        if not impl:
            print("warning: unknown domain file", p.name)
            continue
        txt = p.read_text(encoding="utf-8")
        ns: dict = {}
        exec(compile(txt, str(p), "exec"), ns, ns)
        tools = ns.get("TOOLS") or {}
        for tool_name, meta in tools.items():
            if not isinstance(meta, dict):
                continue
            fn_key = str(meta.get("fn_key", tool_name))
            if fn_key in fn_map and fn_map[fn_key] != impl:
                raise RuntimeError(f"collision: {fn_key} in {fn_map[fn_key]} and {impl}")
            fn_map[fn_key] = impl
    return fn_map


def main() -> None:
    src = REGISTRY_BODY.read_text(encoding="utf-8")
    tree = ast.parse(src)

    funcs: list[tuple[str, int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.end_lineno:
                raise RuntimeError(f"no end_lineno for {node.name}")
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            funcs.append((node.name, start, node.end_lineno))
    funcs.sort(key=lambda x: x[1])

    lines = src.splitlines(keepends=True)
    fn_to_impl = load_fn_to_impl()

    buckets: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    unassigned: list[str] = []
    for name, start, end in funcs:
        impl = fn_to_impl.get(name)
        if impl is None:
            unassigned.append(name)
            impl = "general"
        buckets[impl].append((name, start, end))

    if unassigned:
        print("unassigned (general):", ", ".join(sorted(unassigned)))

    IMPL.mkdir(parents=True, exist_ok=True)

    impl_order = [
        "file_ops",
        "git",
        "system",
        "code",
        "web",
        "memory",
        "data",
        "analysis",
        "automation",
        "geometry",
        "general",
    ]
    for impl in impl_order:
        items = sorted(buckets.get(impl, []), key=lambda x: x[1])
        parts = [HEADER.format(impl_name=impl)]
        for _name, start, end in items:
            chunk = "".join(lines[start - 1 : end])
            if not chunk.endswith("\n"):
                chunk += "\n"
            parts.append(chunk)
            parts.append("\n")
        out_name = f"{impl}.py"
        out_path = IMPL / out_name
        out_path.write_text("".join(parts), encoding="utf-8")
        print("wrote", out_path.relative_to(ROOT), len(items), "functions")

    new_body = '''"""Tool implementations aggregated from :mod:`layla.tools.impl` submodules."""
from __future__ import annotations
from typing import Any

# Injected by layla.tools.registry after TOOLS is assembled.
TOOLS: dict[str, Any] = {}

import layla.tools.impl.analysis as analysis
import layla.tools.impl.automation as automation
import layla.tools.impl.code as code
import layla.tools.impl.data as data
import layla.tools.impl.file_ops as file_ops
import layla.tools.impl.general as general
import layla.tools.impl.geometry as geometry
import layla.tools.impl.git as git
import layla.tools.impl.memory as memory
import layla.tools.impl.system as system
import layla.tools.impl.web as web

_IMPL_MODULES = (
    file_ops,
    git,
    system,
    code,
    web,
    memory,
    data,
    analysis,
    automation,
    geometry,
    general,
)

for _m in _IMPL_MODULES:
    for _name in dir(_m):
        if _name.startswith("_"):
            continue
        _obj = getattr(_m, _name)
        if callable(_obj):
            globals()[_name] = _obj
'''
    REGISTRY_BODY.write_text(new_body, encoding="utf-8")
    print("rewrote", REGISTRY_BODY.relative_to(ROOT))


if __name__ == "__main__":
    main()

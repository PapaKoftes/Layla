"""Backward compatibility -- module moved to services/tools/tool_allowlist_context.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.tools.tool_allowlist_context")
_sys.modules[__name__] = _real

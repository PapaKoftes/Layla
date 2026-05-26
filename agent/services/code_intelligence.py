"""Backward compatibility -- module moved to services/workspace/code_intelligence.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.code_intelligence")
_sys.modules[__name__] = _real

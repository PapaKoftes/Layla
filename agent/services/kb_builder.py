"""Backward compatibility -- module moved to services/workspace/kb_builder.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.kb_builder")
_sys.modules[__name__] = _real

"""Backward compatibility -- module moved to services/workspace/code_indexer.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.code_indexer")
_sys.modules[__name__] = _real

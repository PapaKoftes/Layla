"""Backward compatibility -- module moved to services/workspace/repo_indexer.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.repo_indexer")
_sys.modules[__name__] = _real

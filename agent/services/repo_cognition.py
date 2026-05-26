"""Backward compatibility -- module moved to services/workspace/repo_cognition.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.repo_cognition")
_sys.modules[__name__] = _real

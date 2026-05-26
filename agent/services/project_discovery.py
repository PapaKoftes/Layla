"""Backward compatibility -- module moved to services/workspace/project_discovery.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.workspace.project_discovery")
_sys.modules[__name__] = _real

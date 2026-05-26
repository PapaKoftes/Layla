"""Backward compatibility -- module moved to services/memory/project_memory.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.project_memory")
_sys.modules[__name__] = _real

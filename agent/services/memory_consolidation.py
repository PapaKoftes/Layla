"""Backward compatibility -- module moved to services/memory/memory_consolidation.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.memory_consolidation")
_sys.modules[__name__] = _real

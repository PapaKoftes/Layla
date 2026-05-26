"""Backward compatibility -- module moved to services/memory/working_memory.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.working_memory")
_sys.modules[__name__] = _real

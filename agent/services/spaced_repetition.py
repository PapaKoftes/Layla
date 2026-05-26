"""Backward compatibility -- module moved to services/memory/spaced_repetition.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.spaced_repetition")
_sys.modules[__name__] = _real

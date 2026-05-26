"""Backward compatibility -- module moved to services/memory/golden_examples.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.golden_examples")
_sys.modules[__name__] = _real

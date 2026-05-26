"""Backward compatibility -- module moved to services/llm/structured_gen.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.structured_gen")
_sys.modules[__name__] = _real

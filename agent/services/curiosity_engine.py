"""Backward compatibility -- module moved to services/memory/curiosity_engine.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.memory.curiosity_engine")
_sys.modules[__name__] = _real

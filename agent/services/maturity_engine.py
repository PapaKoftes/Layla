"""Backward compatibility -- module moved to services/personality/maturity_engine.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.maturity_engine")
_sys.modules[__name__] = _real

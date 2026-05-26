"""Backward compatibility -- module moved to services/personality/evolution.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.evolution")
_sys.modules[__name__] = _real

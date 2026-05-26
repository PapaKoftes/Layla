"""Backward compatibility -- module moved to services/personality/aspect_behavior.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.aspect_behavior")
_sys.modules[__name__] = _real

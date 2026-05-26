"""Backward compatibility -- module moved to services/personality/frame_modifier.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.frame_modifier")
_sys.modules[__name__] = _real

"""Backward compatibility -- module moved to services/personality/style_profile.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.personality.style_profile")
_sys.modules[__name__] = _real

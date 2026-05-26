"""Backward compatibility -- module moved to services/safety/auth.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.auth")
_sys.modules[__name__] = _real

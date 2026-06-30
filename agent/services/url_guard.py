"""Backward compatibility -- module moved to services/safety/url_guard.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.url_guard")
_sys.modules[__name__] = _real

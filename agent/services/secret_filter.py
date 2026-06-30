"""Backward compatibility -- module moved to services/safety/secret_filter.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.safety.secret_filter")
_sys.modules[__name__] = _real

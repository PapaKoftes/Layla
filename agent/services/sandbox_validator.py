"""Backward compatibility -- module moved to services/sandbox/sandbox_validator.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.sandbox.sandbox_validator")
_sys.modules[__name__] = _real

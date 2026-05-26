"""Backward compatibility -- module moved to services/infrastructure/crash_handler.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.crash_handler")
_sys.modules[__name__] = _real

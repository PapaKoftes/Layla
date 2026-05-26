"""Backward compatibility -- module moved to services/infrastructure/degraded.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.degraded")
_sys.modules[__name__] = _real

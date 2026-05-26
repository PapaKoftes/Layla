"""Backward compatibility -- module moved to services/infrastructure/failure_recovery.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.failure_recovery")
_sys.modules[__name__] = _real

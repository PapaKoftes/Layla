"""Backward compatibility -- module moved to services/infrastructure/self_improvement.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.self_improvement")
_sys.modules[__name__] = _real

"""Backward compatibility -- module moved to services/infrastructure/reflection_engine.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.reflection_engine")
_sys.modules[__name__] = _real

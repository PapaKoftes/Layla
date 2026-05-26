"""Backward compatibility -- module moved to services/infrastructure/setup_engine.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.setup_engine")
_sys.modules[__name__] = _real

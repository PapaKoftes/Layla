"""Backward compatibility -- module moved to services/infrastructure/config_cache.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.config_cache")
_sys.modules[__name__] = _real

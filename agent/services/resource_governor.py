"""Backward compatibility -- module moved to services/infrastructure/resource_governor.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.resource_governor")
_sys.modules[__name__] = _real

"""Backward compatibility -- module moved to services/infrastructure/provider_health.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.provider_health")
_sys.modules[__name__] = _real

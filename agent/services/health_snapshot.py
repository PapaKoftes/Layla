"""Backward compatibility -- module moved to services/observability/health_snapshot.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.health_snapshot")
_sys.modules[__name__] = _real

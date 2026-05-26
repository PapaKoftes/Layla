"""Backward compatibility -- module moved to services/observability/structured_log.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.structured_log")
_sys.modules[__name__] = _real

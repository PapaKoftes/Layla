"""Backward compatibility -- module moved to services/observability/trace_export.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.trace_export")
_sys.modules[__name__] = _real

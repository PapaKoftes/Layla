"""Backward compatibility -- module moved to services/observability/performance_monitor.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.performance_monitor")
_sys.modules[__name__] = _real

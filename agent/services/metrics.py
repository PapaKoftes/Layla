"""Backward compatibility -- module moved to services/observability/prom_metrics.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.prom_metrics")
_sys.modules[__name__] = _real

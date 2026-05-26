"""Backward compatibility -- module moved to services/observability/request_tracer.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.observability.request_tracer")
_sys.modules[__name__] = _real

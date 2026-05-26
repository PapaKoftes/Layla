"""Backward compatibility -- module moved to services/context/context_attribution.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.context.context_attribution")
_sys.modules[__name__] = _real

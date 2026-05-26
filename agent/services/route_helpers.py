"""Backward compatibility -- module moved to services/infrastructure/route_helpers.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.route_helpers")
_sys.modules[__name__] = _real

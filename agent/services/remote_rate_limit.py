"""Backward compatibility -- module moved to services/infrastructure/remote_rate_limit.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.remote_rate_limit")
_sys.modules[__name__] = _real

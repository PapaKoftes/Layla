"""Backward compatibility -- module moved to services/infrastructure/worker_os_limits.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.worker_os_limits")
_sys.modules[__name__] = _real

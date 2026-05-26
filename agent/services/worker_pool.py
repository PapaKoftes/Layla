"""Backward compatibility -- module moved to services/infrastructure/worker_pool.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.worker_pool")
_sys.modules[__name__] = _real

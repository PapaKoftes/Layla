"""Backward compatibility -- module moved to services/infrastructure/system_optimizer.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.system_optimizer")
_sys.modules[__name__] = _real

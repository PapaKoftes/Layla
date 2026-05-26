"""Backward compatibility -- module moved to services/infrastructure/reasoning_strategies.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.reasoning_strategies")
_sys.modules[__name__] = _real

"""Backward compatibility -- module moved to services/infrastructure/german_mode.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.infrastructure.german_mode")
_sys.modules[__name__] = _real
